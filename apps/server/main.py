"""Demo backend with unified auth and two-level user-data storage."""

from pathlib import Path
from typing import Annotated, Literal, Optional
import json
import re

from fastapi import FastAPI, Header, HTTPException, status, Request, File, UploadFile, Form, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import load_config, Config
from app.session import SessionManager
from app.openai_proxy import OpenAIProxy
from app.filesystem import DatabaseManager, SidebarStructure, SidebarProject, SidebarFolder, SidebarSession

# Import filesystem operations
from app.filesystem_operations import (
    BatchOperationRequest,
    BatchOperationResponse,
    process_batch_operations,
)

# Import workspace/session managers for sidebar queries
from app.workspace_manager import get_user_workspaces, get_workspace_folders
from app.session_manager import get_user_sessions, update_session

# Import new database components
from app.database import init_db, close_db, get_db, init_database_config
from app.api_routes import router as api_router
from app.dependencies import get_current_user
from app.models import User
from app.auth import decode_access_token, get_user_by_id
from sqlalchemy.ext.asyncio import AsyncSession

# Import audio transcription abstraction layer
from app.audio_transcription import (
    TranscriptionProviderFactory,
    TranscriptionConfig,
    AudioEncoding,
)
from app.google_speech_provider import GoogleSpeechProvider  # noqa: F401 (registers provider)
from app.openai_whisper_provider import OpenAIWhisperProvider  # noqa: F401 (registers provider)
from app.elevenlabs_provider import ElevenLabsProvider  # noqa: F401 (registers provider)
from app.google_speech import GoogleSpeechClient

from app.openai_schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    CompletionRequest,
    CompletionResponse,
    EmbeddingsRequest,
    EmbeddingsResponse,
    ModelsResponse,
)

# === Configuration ===
app_root = Path(__file__).parent
db_toml_path = app_root / "db.toml"
sidebar_json_path = app_root / "sidebar.json"
config_path = app_root / "config.toml"

# Global config, session manager, and OpenAI proxy (initialized on startup)
config: Config | None = None
database_manager: DatabaseManager | None = None
session_manager: SessionManager | None = None
openai_proxy: OpenAIProxy | None = None
google_speech_client: GoogleSpeechClient | None = None
audio_transcription_provider = None  # Audio transcription provider instance
google_fallback_transcription_provider = None  # Runtime fallback provider

# === FastAPI App ===
app = FastAPI(title="Demo Backend", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include new API router
app.include_router(api_router, prefix="/api", tags=["api"])


def get_google_runtime_fallback_provider():
    """Get or initialize Google Speech fallback provider for runtime failures."""
    global google_fallback_transcription_provider

    if config is None:
        return None

    google_provider_config = config.audio_transcription.google_speech
    if not google_provider_config or not google_provider_config.get("project_id"):
        return None

    if google_fallback_transcription_provider is not None:
        return google_fallback_transcription_provider

    try:
        google_fallback_transcription_provider = TranscriptionProviderFactory.create_provider(
            "google_speech",
            google_provider_config,
        )
        print("✅ Runtime Google fallback provider initialized")
        return google_fallback_transcription_provider
    except Exception as e:
        print(
            f"⚠️  Warning: Failed to initialize runtime Google fallback provider: {e}")
        return None


async def get_ws_user_by_token(token: str | None) -> User | None:
    """Resolve authenticated user for WebSocket requests using JWT token."""
    if not token:
        return None

    payload = decode_access_token(token)
    if not payload:
        return None

    user_id_raw = payload.get("sub")
    if not user_id_raw:
        return None

    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError):
        return None

    db_gen = get_db()
    try:
        db = await anext(db_gen)
    except StopAsyncIteration:
        return None

    try:
        return await get_user_by_id(db, user_id)
    finally:
        await db_gen.aclose()


async def persist_session_transcription(
    session_id: int,
    user_id: int,
    transcription: str,
) -> None:
    """Persist session transcription text for the owner user (best-effort)."""
    normalized = transcription.strip()
    if not normalized:
        return

    db_gen = get_db()
    try:
        db = await anext(db_gen)
    except StopAsyncIteration:
        return

    try:
        updated = await update_session(
            db,
            session_id=session_id,
            user_id=user_id,
            transcription=normalized,
        )
        if updated is None:
            print(
                f"⚠️  Could not persist transcription: session {session_id} not found for user {user_id}"
            )
    except Exception as exc:
        print(f"⚠️  Failed to persist session transcription: {exc}")
    finally:
        await db_gen.aclose()


# === Models ===
class SuccessResponse(BaseModel):
    success: bool = True
    userId: str | None = None


class SessionResponse(BaseModel):
    """Response for session creation."""

    session_id: str
    created_at: str
    user_id: str | None = None


class SessionInfoResponse(BaseModel):
    """Detailed session information."""

    session_id: str
    user_id: str | None
    created_at: str
    last_accessed: str
    metadata: dict


class AIConfigResponse(BaseModel):
    """AI model configuration (without sensitive tokens)."""

    text_model: dict
    multimodal_model: dict
    speech_model: dict


class MetadataRequest(BaseModel):
    """Request to update session metadata."""
    metadata: dict


# === Initialization ===
@app.on_event("startup")
async def startup_event():
    """Initialize application components on startup."""
    global config, database_manager, session_manager, openai_proxy, google_speech_client, audio_transcription_provider

    # Load configuration first
    try:
        config = load_config(config_path)
        print(f"✅ Configuration loaded from {config_path}")
    except Exception as e:
        print(f"❌ Failed to load configuration: {e}")
        raise

    # Initialize MySQL database with config
    try:
        database_url = config.mysql.get_database_url()
        print(
            f"🔗 Connecting to MySQL: {config.mysql.username}@{config.mysql.address}:{config.mysql.port}/{config.mysql.database}")
        init_database_config(database_url)
        await init_db()
        print("✅ MySQL database initialized")
    except Exception as e:
        print(f"⚠️  Warning: Failed to initialize MySQL database: {e}")
        print("   Falling back to TOML-based storage")

    database_manager = DatabaseManager(db_toml_path)

    # Migration logic: if sidebar.json exists and we should migrate it
    if sidebar_json_path.exists():
        try:
            # If db.toml was just created with default data, we can overwrite it with migrated data
            # Or we can check if it's the default data.
            # For simplicity, if sidebar.json exists, we migrate it once and rename it.
            print(f"🔄 Migrating {sidebar_json_path} to {db_toml_path}")
            import json
            with open(sidebar_json_path, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                database_manager.save_structure(SidebarStructure(**old_data))
            # Rename old file to avoid re-migration
            sidebar_json_path.rename(
                sidebar_json_path.with_suffix(".json.bak"))
            print(f"✅ Migration successful")
        except Exception as e:
            print(f"⚠️ Migration failed: {e}")

    # Initialize session manager and other components
    try:
        session_manager = SessionManager(
            timeout_minutes=config.system.session_timeout_minutes,
            max_sessions_per_user=config.system.max_sessions_per_user,
            db_manager=database_manager
        )
        openai_proxy = OpenAIProxy(config)
        print(f"   Text model: {config.text_model.name}")
        print(f"   Multimodal model: {config.multimodal_model.name}")
        print(f"   Speech model: {config.speech_model.name}")
        print(f"✅ OpenAI API proxy initialized")

        # Initialize audio transcription provider (new abstraction layer)
        if config.audio_transcription.is_valid():
            try:
                provider_type = config.audio_transcription.provider
                provider_config = config.audio_transcription.get_provider_config()

                audio_transcription_provider = TranscriptionProviderFactory.create_provider(
                    provider_type,
                    provider_config
                )
                print(
                    f"✅ Audio transcription provider initialized: {provider_type}")
            except Exception as e:
                print(
                    f"⚠️  Warning: Failed to initialize audio transcription provider: {e}")

        # Initialize Google Speech v1 client if configured (legacy support)
        if config.google_speech.enabled and config.google_speech.credentials_path:
            google_speech_client = GoogleSpeechClient(
                project_id=config.google_speech.project_id,
                location=config.google_speech.location,
                recognizer_id=config.google_speech.recognizer_id,
                credentials_path=config.google_speech.credentials_path,
            )
            print(f"✅ Google Speech v1 client initialized (legacy)")
            print(f"   Credentials: {config.google_speech.credentials_path}")
        else:
            print("ℹ️  Google Speech v1 client not configured or disabled")

    except Exception as e:
        print(f"⚠️  Warning: Failed to load config: {e}")
        print("   Session and AI features will be limited")


# === Routes ===

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"ok": True}


@app.get("/api/filesystem", response_model=SidebarStructure)
async def get_filesystem(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve the authenticated user's sidebar structure.
    """
    workspaces = await get_user_workspaces(db, current_user.id)
    projects: list[SidebarProject] = []

    for ws in workspaces:
        folders = await get_workspace_folders(db, ws.id)
        sessions = await get_user_sessions(db, current_user.id, workspace_id=ws.id)

        extra_data = ws.extra_data or {}
        raw_session_folder_ids = extra_data.get("session_folder_ids", [])
        session_folder_ids = {
            int(value)
            for value in raw_session_folder_ids
            if isinstance(value, int) or (isinstance(value, str) and value.isdigit())
        }

        folder_sessions: dict[int | None, list] = {}
        for s in sessions:
            fid = getattr(s, "folder_id", None)
            folder_sessions.setdefault(fid, []).append(s)

        items: list[SidebarSession | SidebarFolder] = []
        for f in folders:
            children = [
                SidebarSession(id=s.id, name=s.title)
                for s in folder_sessions.pop(f.id, [])
            ]

            # Session sidebar only shows folders explicitly created by session API
            # or folders that currently contain sessions.
            if f.id in session_folder_ids or len(children) > 0:
                items.append(SidebarFolder(
                    id=f.id, name=f.name, children=children))

        for s in folder_sessions.pop(None, []):
            items.append(SidebarSession(id=s.id, name=s.title))

        projects.append(SidebarProject(id=ws.id, name=ws.name, items=items))

    if not projects:
        projects.append(
            SidebarProject(
                id=0,
                name=f"{current_user.username}'s Workspace",
                items=[]
            )
        )

    return SidebarStructure(projects=projects)


@app.post("/api/filesystem", response_model=BatchOperationResponse)
async def batch_filesystem_operations(
    body: BatchOperationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Execute batch file system operations.

    This endpoint accepts an array of operations (CREATE, UPDATE, DELETE, MOVE)
    and executes them in order within a single transaction.

    Requires authentication via JWT token.
    """
    # Process batch operations
    response = await process_batch_operations(
        db=db,
        user_id=current_user.id,
        operations=body.operations
    )

    # Commit if all operations succeeded
    if response.success:
        await db.commit()
    else:
        # Rollback on any failure
        await db.rollback()

    return response


@app.post("/api/sessions", response_model=SessionResponse)
async def initialize_session(current_user: User = Depends(get_current_user)):
    """Initialize a new session with empty context/transcription."""
    if session_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session management not available",
        )

    session = session_manager.create_session(user_id=current_user.id)

    return SessionResponse(
        session_id=session.session_id,
        created_at=session.created_at.isoformat(),
        user_id=session.user_id,
    )


# === Session Management Routes ===
@app.post("/api/session", response_model=SessionResponse)
async def create_session(current_user: User = Depends(get_current_user)):
    """
    Create a new session with a unique UUID.
    The session ID is used to track user interactions.
    """
    if session_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session management not available",
        )

    session = session_manager.create_session(user_id=current_user.id)

    return SessionResponse(
        session_id=session.session_id,
        created_at=session.created_at.isoformat(),
        user_id=session.user_id,
    )


@app.get("/api/session/{session_id}", response_model=SessionInfoResponse)
async def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    """Get session information by session ID."""
    if session_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session management not available",
        )

    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or expired",
        )

    return SessionInfoResponse(
        session_id=session.session_id,
        user_id=session.user_id,
        created_at=session.created_at.isoformat(),
        last_accessed=session.last_accessed.isoformat(),
        metadata=session.metadata,
    )


@app.delete("/api/session/{session_id}", response_model=SuccessResponse)
async def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    """Delete a session."""
    if session_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session management not available",
        )

    deleted = session_manager.delete_session(session_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    return SuccessResponse()


@app.put("/api/session/{session_id}", response_model=SuccessResponse)
async def update_session(
    session_id: str,
    body: MetadataRequest,
    current_user: User = Depends(get_current_user),
):
    """Update session metadata."""
    if session_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session management not available",
        )

    session_manager.update_session_metadata(session_id, body.metadata)
    return SuccessResponse()


# === AI Configuration Routes ===
@app.get("/api/ai/config", response_model=AIConfigResponse)
async def get_ai_config(current_user: User = Depends(get_current_user)):
    """
    Get AI model configuration (without API tokens).
    Returns model names and endpoints for client-side reference.
    """
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration not available",
        )

    # Return config without exposing API tokens
    return AIConfigResponse(
        text_model={
            "name": config.text_model.name,
            "endpoint": config.text_model.endpoint,
            "description": config.text_model.description,
        },
        multimodal_model={
            "name": config.multimodal_model.name,
            "endpoint": config.multimodal_model.endpoint,
            "description": config.multimodal_model.description,
        },
        speech_model={
            "name": config.speech_model.name,
            "endpoint": config.speech_model.endpoint,
            "description": config.speech_model.description,
        },
    )


# === Cleanup ===
@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup resources on shutdown."""
    if openai_proxy is not None:
        await openai_proxy.close()

    # Close database connections
    try:
        await close_db()
        print("✅ Database connections closed")
    except Exception as e:
        print(f"⚠️  Warning: Error closing database: {e}")


# === OpenAI API Compatible Routes ===
@app.post("/v1/chat/completions")
async def openai_chat_completions(
    request: ChatCompletionRequest,
    authorization: Annotated[str | None, Header()] = None,
):
    """
    OpenAI-compatible chat completions endpoint.
    Supports both streaming and non-streaming responses.
    """
    if openai_proxy is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI proxy not available",
        )

    result = await openai_proxy.chat_completion(request, authorization)

    # Handle streaming response
    if request.stream:
        # Type narrowing: if stream is True, result is AsyncIterator[str]
        return StreamingResponse(
            result,  # type: ignore
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
    else:
        # Non-streaming response: result is ChatCompletionResponse
        return result


@app.post("/v1/completions")
async def openai_completions(
    request: CompletionRequest,
    authorization: Annotated[str | None, Header()] = None,
):
    """
    OpenAI-compatible text completions endpoint (legacy).
    Supports both streaming and non-streaming responses.
    """
    if openai_proxy is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI proxy not available",
        )

    result = await openai_proxy.completion(request, authorization)

    # Handle streaming response
    if request.stream:
        # Type narrowing: if stream is True, result is AsyncIterator[str]
        return StreamingResponse(
            result,  # type: ignore
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
    else:
        # Non-streaming response: result is CompletionResponse
        return result


@app.post("/v1/embeddings", response_model=EmbeddingsResponse)
async def openai_embeddings(
    request: EmbeddingsRequest,
    authorization: Annotated[str | None, Header()] = None,
):
    """OpenAI-compatible embeddings endpoint."""
    if openai_proxy is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI proxy not available",
        )

    return await openai_proxy.embeddings(request, authorization)


@app.get("/v1/models", response_model=ModelsResponse)
async def openai_list_models(
    authorization: Annotated[str | None, Header()] = None,
):
    """OpenAI-compatible models list endpoint."""
    if openai_proxy is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI proxy not available",
        )

    return await openai_proxy.list_models()


# === Translation Route (single-shot, no session recording) ===
class TranslateRequest(BaseModel):
    """Request body for the translate endpoint."""
    text: str = Field(..., description="Text to translate (may contain multiple paragraphs)")
    to: str = Field(..., description="Target language name or BCP-47 code, e.g. 'English', 'zh-CN'")
    model: str | None = Field(default=None, description="Override model name")


class TranslateResponse(BaseModel):
    """Response body for the translate endpoint."""
    translation: str


@app.post("/v1/translate", response_model=TranslateResponse)
async def translate_text(
    request: TranslateRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Translate text via AI model direct call (single-shot, not recorded).
    Uses the configured text model through OpenAI-compatible API.
    """
    if openai_proxy is None or config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI service not available",
        )

    model_config = config.text_model
    if not model_config.is_valid():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Text model not configured",
        )

    system_prompt = (
        f"You are a professional {request.to} native translator who needs to "
        f"fluently translate text into {request.to}.\n\n"
        "## Translation Rules\n"
        "1. Output ONLY the translated content, without explanations or additional "
        "content (such as \"Here's the translation:\" or \"Translation as follows:\")\n"
        "2. The returned translation must maintain exactly the same number of "
        "paragraphs and format as the original text\n"
        "3. For content that should not be translated (such as proper nouns, code, "
        "etc.), keep the original text.\n"
        "4. Do NOT wrap the output in quotes or any markup. Return the raw translated text only."
    )

    import httpx as _httpx

    headers = {
        "Authorization": f"Bearer {model_config.api_token}",
        "Content-Type": "application/json",
    }

    body: dict = {
        "model": request.model or model_config.name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.text},
        ],
        "temperature": 0.3,
    }

    endpoint_url = f"{model_config.endpoint}/chat/completions"

    try:
        async with _httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(endpoint_url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        translation = content.strip()

        return TranslateResponse(translation=translation)

    except _httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Upstream translation API error: {e.response.text}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Translation error: {str(e)}",
        )


# === Audio Transcription Routes (New Abstraction Layer) ===
@app.post("/v1/audio/transcriptions")
async def transcribe_audio(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    model: str = Form(default="default"),
    session_id: int | None = Form(default=None),
    language: str | None = Form(default=None),
    prompt: str | None = Form(default=None),
    response_format: Literal["json", "text", "srt",
                             "verbose_json", "vtt"] = Form(default="json"),
    temperature: float = Form(default=0.0),
    timestamp_granularities: list[str] | None = Form(default=None),
):
    """
    OpenAI-compatible audio transcription endpoint.

    Accepts audio file upload and returns transcription result.
    Automatically uses the configured provider (Google Speech or OpenAI Whisper).

    Args:
        file: Audio file to transcribe
        model: Model to use (ignored, uses configured provider)
        language: Language of the audio (ISO-639-1 format)
        prompt: Optional text to guide the model's style
        response_format: Format of the response
        temperature: Sampling temperature (0-1)
        timestamp_granularities: Timestamp granularities (e.g., ["word", "segment"])

    Returns:
        Transcription result in the requested format
    """
    if audio_transcription_provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio transcription service not available. Please configure a provider.",
        )

    if config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configuration not available",
        )

    try:
        # Read file content
        audio_content = await file.read()

        # Determine encoding from file extension
        file_ext = file.filename.split(
            ".")[-1].lower() if file.filename else "opus"
        encoding_map = {
            "opus": AudioEncoding.OPUS,
            "mp3": AudioEncoding.MP3,
            "mp4": AudioEncoding.MP4,
            "mpeg": AudioEncoding.MPEG,
            "mpga": AudioEncoding.MPGA,
            "m4a": AudioEncoding.M4A,
            "wav": AudioEncoding.WAV,
            "webm": AudioEncoding.WEBM,
        }
        encoding = encoding_map.get(file_ext, AudioEncoding.OPUS)

        # Build transcription config
        transcription_config = TranscriptionConfig(
            encoding=encoding,
            language=language if language else config.audio_transcription.default_language,
            enable_timestamps=(response_format == "verbose_json"),
            enable_word_timestamps=(
                timestamp_granularities is not None
                and "word" in timestamp_granularities
            ),
        )

        provider_in_use = audio_transcription_provider

        # Transcribe file (with runtime fallback to Google Speech)
        try:
            result = await provider_in_use.transcribe_file(
                audio_content,
                transcription_config
            )
        except Exception as primary_error:
            fallback_provider = get_google_runtime_fallback_provider()
            if fallback_provider is None or fallback_provider is provider_in_use:
                raise primary_error

            print(
                f"⚠️  Primary transcription provider failed, falling back to Google Speech: {primary_error}"
            )
            result = await fallback_provider.transcribe_file(
                audio_content,
                transcription_config
            )

        # Persist transcript to the linked session when provided.
        transcript_text = (result.text or "").strip()
        if session_id is not None and transcript_text:
            updated = await update_session(
                db,
                session_id=session_id,
                user_id=current_user.id,
                transcription=transcript_text,
            )
            if updated is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Session not found",
                )

        # Format response based on response_format
        if response_format == "text":
            return result.text
        elif response_format == "verbose_json":
            return {
                "task": "transcribe",
                "language": result.language,
                "duration": result.duration,
                "text": result.text,
                "segments": [
                    {
                        "id": idx,
                        "seek": 0,
                        "start": seg.start_time,
                        "end": seg.end_time,
                        "text": seg.text,
                        "tokens": [],
                        "temperature": temperature,
                        "avg_logprob": 0.0,
                        "compression_ratio": 1.0,
                        "no_speech_prob": 0.0,
                    }
                    for idx, seg in enumerate(result.segments)
                ],
                "words": [
                    {
                        "word": word.word,
                        "start": word.start,
                        "end": word.end,
                    }
                    for word in result.words
                ] if result.words else None,
            }
        else:  # json (default)
            return {
                "text": result.text,
            }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription failed: {str(e)}"
        )


@app.websocket("/v1/audio/transcriptions/ws")
async def transcribe_audio_stream_ws(
    websocket: WebSocket,
    token: str | None = None,
    session_id: int | None = None,
    encoding: str = "opus",
    sample_rate: int = 48000,
    language: str | None = None,
):
    """
    WebSocket endpoint for real-time streaming audio transcription.

    The client sends binary audio frames; the server replies with JSON text
    messages containing transcription chunks, finishing with a `[DONE]` text
    frame.

    Query Parameters (same as the POST /stream endpoint):
        token: JWT token (required for browser WebSocket authentication)
        encoding: Audio encoding (default: opus)
        sample_rate: Sample rate in Hz (default: 48000)
        language: Language code (e.g., "zh-CN"), comma-separated for multiple
    """
    await websocket.accept()

    current_user = await get_ws_user_by_token(token)
    if current_user is None:
        await websocket.send_json({"error": "Authentication required"})
        await websocket.close(code=4401)
        return

    if audio_transcription_provider is None and get_google_runtime_fallback_provider() is None:
        await websocket.send_json({"error": "Audio transcription service not available"})
        await websocket.close(code=1011)
        return

    if config is None:
        await websocket.send_json({"error": "Configuration not available"})
        await websocket.close(code=1011)
        return

    # Parse encoding
    try:
        audio_encoding = AudioEncoding(encoding.lower())
    except ValueError:
        await websocket.send_json({"error": f"Unsupported encoding: {encoding}"})
        await websocket.close(code=1003)
        return

    # Parse language
    if language:
        languages = [lang.strip() for lang in language.split(",")]
    else:
        languages = config.audio_transcription.default_language

    transcription_config = TranscriptionConfig(
        encoding=audio_encoding,
        sample_rate=sample_rate,
        language=languages,
        enable_timestamps=True,
        enable_word_timestamps=True,
    )

    import asyncio

    # Async queue that bridges WebSocket binary frames → async generator
    audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def audio_from_ws():
        """Yield audio bytes received via WebSocket until sentinel None."""
        while True:
            chunk = await audio_queue.get()
            if chunk is None:
                return
            yield chunk

    async def receive_audio():
        """Read binary frames from the WebSocket and enqueue them."""
        try:
            while True:
                data = await websocket.receive()
                if data["type"] == "websocket.disconnect":
                    break
                if "bytes" in data and data["bytes"]:
                    await audio_queue.put(data["bytes"])
        except WebSocketDisconnect:
            pass
        finally:
            # Signal end-of-stream to the audio generator
            await audio_queue.put(None)

    async def transcribe_and_send():
        """Run the transcription provider and push results back via WebSocket."""
        import logging
        _ws_log = logging.getLogger("stt.ws")
        provider = audio_transcription_provider or get_google_runtime_fallback_provider()

        committed_text = ""
        last_partial_sent = ""

        def canonicalize(text: str) -> str:
            return re.sub(r"\s*([,.;:!?，。！？；：])\s*", r"\1", re.sub(r"\s+", " ", text.strip())).lower()

        def slice_after_canonical_prefix(prefix_text: str, full_text: str) -> str:
            prefix_canonical = canonicalize(prefix_text)
            full_canonical = canonicalize(full_text)

            if not prefix_canonical:
                return full_text.strip()
            if full_canonical == prefix_canonical:
                return ""
            if not full_canonical.startswith(prefix_canonical):
                return full_text.strip()

            for idx in range(len(full_text) + 1):
                if canonicalize(full_text[:idx]) == prefix_canonical:
                    return full_text[idx:].strip()

            return full_text.strip()

        try:
            async for chunk in provider.transcribe_stream(
                audio_from_ws(),
                transcription_config,
            ):
                raw_text = (chunk.text or "").strip()
                if not raw_text:
                    continue

                text_to_send = raw_text
                if chunk.is_final:
                    # Final events should append only new committed text.
                    text_to_send = slice_after_canonical_prefix(
                        committed_text, raw_text)
                    if not text_to_send:
                        continue

                    committed_text = f"{committed_text} {text_to_send}".strip(
                    ) if committed_text else text_to_send
                    last_partial_sent = ""
                else:
                    # Partial events should represent only uncommitted tail.
                    text_to_send = slice_after_canonical_prefix(
                        committed_text, raw_text)
                    if not text_to_send:
                        continue

                    if canonicalize(text_to_send) == canonicalize(last_partial_sent):
                        continue
                    last_partial_sent = text_to_send

                _ws_log.info(
                    "STT chunk | final=%s text=%r",
                    chunk.is_final,
                    text_to_send[:120],
                )
                event_data: dict = {
                    "text": text_to_send,
                    "is_final": chunk.is_final,
                    "confidence": chunk.confidence,
                    "language": chunk.language,
                    "start_time": chunk.start_time,
                    "end_time": chunk.end_time,
                    "metadata": chunk.metadata,
                }
                if chunk.words:
                    event_data["words"] = [
                        {"word": w.word, "start": w.start, "end": w.end}
                        for w in chunk.words
                    ]
                await websocket.send_text(json.dumps(event_data, ensure_ascii=False))
        except Exception as e:
            try:
                await websocket.send_json({"error": str(e)})
            except Exception:
                pass

        # Send completion marker
        try:
            await websocket.send_text("[DONE]")
        except Exception:
            pass

        if session_id is not None and committed_text.strip():
            await persist_session_transcription(
                session_id=session_id,
                user_id=current_user.id,
                transcription=committed_text,
            )

    # Run receiver and sender concurrently
    recv_task = asyncio.create_task(receive_audio())
    send_task = asyncio.create_task(transcribe_and_send())

    try:
        await asyncio.gather(recv_task, send_task)
    except Exception:
        recv_task.cancel()
        send_task.cancel()
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
