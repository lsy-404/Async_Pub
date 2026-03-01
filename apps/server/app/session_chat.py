"""Session-scoped LLM chat orchestration with simple context and server tools.

Design constraints for current migration stage:
- No migrated sober persona; only a lightweight neutral system instruction.
- No pinpoint mode.
- Context window is intentionally simple: last 10 rounds (up to 20 messages).
- Keep context-related tools available on the server side.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from fastapi import HTTPException, status
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import load_config
from app.models import Material, Message, Session
from app.session_manager import create_message
from app.workspace_manager import create_material, get_or_create_user_root_workspace


BASE_DIR = Path(__file__).resolve().parents[1]
TEXT_LIKE_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".json",
    ".csv",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".sql",
    ".yaml",
    ".yml",
    ".toml",
    ".xml",
    ".html",
    ".css",
}


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class SummaryIndexEntry:
    heading_no: int
    title: str
    chunk_id: str
    chunk_offset: int
    chunk_length: int
    created_at: str


SUMMARY_DIR = BASE_DIR / "user-data" / "summaries"
SUMMARY_DIR.mkdir(parents=True, exist_ok=True)


def _build_openai_client_and_model() -> tuple[AsyncOpenAI, str, Any]:
    config_path = BASE_DIR / "config.toml"
    config = load_config(config_path)
    model_config = config.text_model
    if not model_config.is_valid():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Text model configuration is invalid",
        )

    client = AsyncOpenAI(
        api_key=model_config.api_token,
        base_url=model_config.endpoint,
    )
    return client, model_config.name, config


async def _get_recent_session_messages(
    db: AsyncSession,
    session_id: int,
    rounds: int = 10,
) -> list[dict[str, Any]]:
    max_messages = max(1, rounds * 2)
    rows = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(max_messages)
    )
    messages = list(rows.scalars().all())
    messages.reverse()

    payload: list[dict[str, Any]] = []
    for m in messages:
        payload.append(
            {
                "role": m.role,
                "content": m.content,
            }
        )
    return payload


def _extract_text_snippets(text: str, keyword: str, window: int) -> list[str]:
    matches: list[str] = []
    if not text:
        return matches

    lower_text = text.lower()
    lower_keyword = keyword.lower()

    idx = lower_text.find(lower_keyword)
    while idx != -1:
        start = max(0, idx - window)
        end = min(len(text), idx + len(keyword) + window)
        snippet = text[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        matches.append(snippet)
        idx = lower_text.find(lower_keyword, idx + len(lower_keyword))

    return matches


async def _tool_search_context(
    db: AsyncSession,
    session: Session,
    keyword: str,
    occurrences: int = 5,
    window: int = 100,
) -> dict[str, Any]:
    if not keyword.strip():
        return {"error": "keyword is required"}

    results: list[dict[str, Any]] = []

    # Search all session messages (full session, not only last 10 rounds).
    msg_rows = await db.execute(
        select(Message)
        .where(Message.session_id == session.id)
        .order_by(Message.created_at.asc())
    )
    for msg in msg_rows.scalars().all():
        snippets = _extract_text_snippets(msg.content or "", keyword, window)
        for snippet in snippets:
            results.append(
                {
                    "source": f"message:{msg.id}",
                    "type": "message",
                    "role": msg.role,
                    "created_at": msg.created_at.isoformat(),
                    "snippet": snippet,
                }
            )
            if occurrences != -1 and len(results) >= occurrences:
                return {
                    "keyword": keyword,
                    "count": len(results),
                    "results": results,
                }

    # Search workspace materials as supplemental context.
    if session.workspace_id is not None:
        material_rows = await db.execute(
            select(Material)
            .where(Material.workspace_id == session.workspace_id)
            .order_by(Material.created_at.asc())
        )
        for material in material_rows.scalars().all():
            text_sources: list[tuple[str, str]] = []

            if material.raw_content:
                text_sources.append(("raw_content", material.raw_content))

            if material.file_path:
                file_path = BASE_DIR / material.file_path
                suffix = file_path.suffix.lower()
                if suffix in TEXT_LIKE_SUFFIXES and file_path.exists():
                    try:
                        file_text = file_path.read_text(encoding="utf-8")
                        text_sources.append(("file", file_text))
                    except Exception:
                        # Best-effort text extraction only.
                        pass

            for source_kind, source_text in text_sources:
                snippets = _extract_text_snippets(
                    source_text or "", keyword, window)
                for snippet in snippets:
                    results.append(
                        {
                            "source": f"material:{material.id}",
                            "type": "material",
                            "title": material.title,
                            "source_kind": source_kind,
                            "created_at": material.created_at.isoformat(),
                            "snippet": snippet,
                        }
                    )
                    if occurrences != -1 and len(results) >= occurrences:
                        return {
                            "keyword": keyword,
                            "count": len(results),
                            "results": results,
                        }

    return {
        "keyword": keyword,
        "count": len(results),
        "results": results,
    }


async def _tool_get_out_of_context_file(
    db: AsyncSession,
    session: Session,
    filenames: list[str],
) -> dict[str, Any]:
    if not filenames:
        return {"error": "filenames is required"}

    if session.workspace_id is None:
        return {"error": "session is not bound to a workspace"}

    materials_result = await db.execute(
        select(Material)
        .where(Material.workspace_id == session.workspace_id)
        .order_by(Material.created_at.desc())
    )
    materials = list(materials_result.scalars().all())

    out: dict[str, Any] = {}
    for filename in filenames:
        matched: Material | None = None
        requested = filename.strip().lower()
        for m in materials:
            title_match = (m.title or "").strip().lower() == requested
            basename_match = False
            if m.file_path:
                basename_match = Path(
                    m.file_path).name.strip().lower() == requested
            if title_match or basename_match:
                matched = m
                break

        if not matched:
            out[filename] = {"error": "file not found in workspace materials"}
            continue

        if matched.raw_content:
            out[filename] = {
                "type": "text",
                "contentType": "text/plain",
                "title": matched.title,
                "content": matched.raw_content,
            }
            continue

        if matched.file_path:
            file_path = BASE_DIR / matched.file_path
            if not file_path.exists():
                out[filename] = {
                    "error": "file path exists in DB but file is missing"}
                continue

            suffix = file_path.suffix.lower()
            if suffix in TEXT_LIKE_SUFFIXES:
                try:
                    text = file_path.read_text(encoding="utf-8")
                    out[filename] = {
                        "type": "text",
                        "contentType": "text/plain",
                        "title": matched.title,
                        "content": text,
                    }
                except Exception as exc:
                    out[filename] = {
                        "error": f"failed to read text file: {exc}"}
            else:
                out[filename] = {
                    "type": "unsupported",
                    "contentType": "application/octet-stream",
                    "title": matched.title,
                    "content": "Binary file retrieval is not supported yet in Async server migration stage.",
                }
            continue

        out[filename] = {"error": "material has no retrievable content"}

    return out


async def _tool_web_search(
    config,
    query: str,
    max_results: int = 5,
) -> dict[str, Any]:
    cleaned_query = query.strip()
    if not cleaned_query:
        return {"error": "query is required"}

    max_results = max(1, min(max_results, 10))

    web_search_cfg = getattr(config, "web_search", None)
    if web_search_cfg is None or not web_search_cfg.is_valid():
        return {"error": "web_search configuration is missing or invalid"}

    endpoint = web_search_cfg.endpoint
    api_token = web_search_cfg.api_token
    freshness = web_search_cfg.freshness or "one_month"

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                endpoint,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_token}",
                },
                json={
                    "query": cleaned_query,
                    "freshness": freshness,
                    "count": max_results,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        return {"error": f"web search failed: {exc}"}

    raw_results = (
        payload.get("data", {}).get("webSearch", {}).get("results")
        or payload.get("data", {}).get("webPages", {}).get("value")
        or payload.get("results")
        or payload.get("data")
        or []
    )

    results: list[dict[str, Any]] = []
    if isinstance(raw_results, list):
        for item in raw_results[:max_results]:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            snippet = (
                str(item.get("snippet") or "").strip()
                or str(item.get("description") or "").strip()
                or str(item.get("summary") or "").strip()
            )
            name = (
                str(item.get("name") or "").strip()
                or str(item.get("title") or "").strip()
                or (snippet[:50] if snippet else "Search Result")
            )
            results.append(
                {
                    "url": url,
                    "displayUrl": str(item.get("displayUrl") or "").strip() or url,
                    "name": name,
                    "snippet": snippet,
                }
            )

    return {
        "query": cleaned_query,
        "count": len(results),
        "results": results[:max_results],
    }


def _get_server_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="web_search",
            description="Search the web for up-to-date public information and return concise result snippets with URLs.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (1-10).",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        ),
        ToolDefinition(
            name="search_context",
            description="Search keyword snippets across full session history and workspace materials.",
            parameters={
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "Keyword or phrase to search for.",
                    },
                    "occurrences": {
                        "type": "integer",
                        "description": "Max results to return. Use -1 to return all matches.",
                        "default": 5,
                    },
                    "window": {
                        "type": "integer",
                        "description": "Characters before/after match to include in snippet.",
                        "default": 100,
                    },
                },
                "required": ["keyword"],
            },
        ),
        ToolDefinition(
            name="get_out_of_context_file",
            description="Retrieve text content from workspace materials by filename/title when content is out of current context window.",
            parameters={
                "type": "object",
                "properties": {
                    "filenames": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filenames or material titles to retrieve.",
                    }
                },
                "required": ["filenames"],
            },
        ),
        ToolDefinition(
            name="list_summary_headings",
            description="List numbered summary headings for this session's transcript summary document.",
            parameters={"type": "object", "properties": {}},
        ),
        ToolDefinition(
            name="get_summary_chunk",
            description="Retrieve the original transcript chunk mapped to a summary heading/chunk_id.",
            parameters={
                "type": "object",
                "properties": {
                    "heading_no": {
                        "type": "integer",
                        "description": "Heading number (e.g., 1,2,3).",
                    },
                    "chunk_id": {
                        "type": "string",
                        "description": "Chunk identifier returned by list_summary_headings (e.g., '600-900').",
                    },
                },
                "anyOf": [
                    {"required": ["heading_no"]},
                    {"required": ["chunk_id"]},
                ],
            },
        ),
    ]


async def _execute_tool_call(
    db: AsyncSession,
    session: Session,
    config,
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    if tool_name == "web_search":
        return await _tool_web_search(
            config=config,
            query=str(args.get("query", "")),
            max_results=int(
                args.get(
                    "max_results",
                    getattr(getattr(config, "web_search", None),
                            "default_count", 5),
                )
            ),
        )

    if tool_name == "search_context":
        return await _tool_search_context(
            db=db,
            session=session,
            keyword=str(args.get("keyword", "")),
            occurrences=int(args.get("occurrences", 5)),
            window=int(args.get("window", 100)),
        )

    if tool_name == "get_out_of_context_file":
        filenames = args.get("filenames")
        if not isinstance(filenames, list):
            return {"error": "filenames must be an array"}
        return await _tool_get_out_of_context_file(
            db=db,
            session=session,
            filenames=[str(x) for x in filenames],
        )

    if tool_name == "list_summary_headings":
        snapshot = await get_session_summary_snapshot(db, session)
        return {
            "updated_at": snapshot.get("updated_at"),
            "headings": snapshot.get("index", []),
            "transcription_length": len((session.transcription or "").strip()),
        }

    if tool_name == "get_summary_chunk":
        snapshot = await get_session_summary_snapshot(db, session)
        index_entries = snapshot.get("index", []) or []
        heading_no = args.get("heading_no")
        chunk_id = args.get("chunk_id")

        target_entry: dict[str, Any] | None = None
        for item in index_entries:
            if heading_no is not None and item.get("heading_no") == heading_no:
                target_entry = item
                break
            if chunk_id is not None and str(item.get("chunk_id")) == str(chunk_id):
                target_entry = item
                break

        if not target_entry:
            return {"error": "summary section not found"}

        transcription = (session.transcription or "").strip()
        if not transcription:
            return {"error": "session transcription is empty"}

        offset = int(target_entry.get("chunk_offset", 0) or 0)
        length = int(target_entry.get("chunk_length", 0) or 0)
        if offset < 0:
            offset = 0
        if length < 0:
            length = 0

        transcript_chunk = transcription[offset: offset +
                                         length] if length > 0 else ""
        if not transcript_chunk:
            # Fallback: return a bounded tail from offset when chunk length is unavailable/corrupt.
            transcript_chunk = transcription[offset: offset + 1200]

        return {
            "heading": target_entry,
            "content": transcript_chunk,
            "offset": offset,
            "length": len(transcript_chunk),
            "updated_at": snapshot.get("updated_at"),
        }

    if tool_name == "python_interpreter":
        return {
            "error": "python_interpreter is disabled in current migration stage",
        }

    return {"error": f"Unsupported tool: {tool_name}"}


def _sse_payload(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_session_chat(
    db: AsyncSession,
    session: Session,
    user_id: int,
    content: str,
    model: str | None = None,
    temperature: float | None = None,
    transcription_override: str | None = None,
    enable_tools: bool = True,
) -> AsyncIterator[str]:
    """Stream chat completion for a session and persist user/assistant messages.

        Notes:
        - Uses a lightweight neutral system instruction (no persona) to control
            uncertainty tagging and response behavior.
        - Only recent 10 rounds are sent as LLM context.
        - Context tools are available when enabled.
    """
    # Persist incoming user message first.
    await create_message(db, session.id, "user", content)

    llm_messages = await _get_recent_session_messages(db, session.id, rounds=10)

    # Keep this instruction intentionally minimal and persona-free.
    # The frontend highlights <maybe>...</maybe> spans and provides a follow-up action.
    system_instruction = (
        "You are a helpful AI assistant. Keep responses accurate, concise, and neutral. "
        "When a factual statement is uncertain, unverified, estimated, or likely stale, "
        "wrap only the uncertain span with <maybe> and </maybe>. "
        "Do not wrap entire answers unless everything is uncertain. "
        "Do not use <maybe> for obvious facts. "
        "Do not explain the tagging rule unless asked."
    )

    override = (transcription_override or "").strip()
    if override and override != (session.transcription or "").strip():
        session.transcription = override
        await db.flush()

    snapshot = await get_session_summary_snapshot(db, session)
    summary_text = str(snapshot.get("summary") or "").strip()
    summary_index = snapshot.get("index") or []
    transcription = (session.transcription or "").strip()
    latest_transcript_tail_chars = int(
        os.getenv("ASYNC_TRANSCRIPT_TAIL_CHARS_IN_MAIN_CONTEXT", "1800")
    )
    latest_transcript_tail_chars = max(
        300, min(latest_transcript_tail_chars, 6000))

    if summary_text:
        system_instruction += (
            "\n\nSession summary (high-level context):\n"
            "--- SUMMARY START ---\n"
            f"{summary_text}\n"
            "--- SUMMARY END ---\n"
            "Use this summary as primary high-level context. "
            "For exact quotations/details from the original transcript, "
            "call get_summary_chunk with heading_no or chunk_id."
        )
    elif transcription:
        system_instruction += (
            "\n\nA session transcription exists but no summary is available yet. "
            "If precise transcript evidence is required, use tools to inspect available chunks."
        )

    if summary_index:
        system_instruction += (
            "\n\nAvailable summary headings are accessible via list_summary_headings."
        )

    if transcription:
        latest_tail = transcription[-latest_transcript_tail_chars:]
        if len(transcription) > latest_transcript_tail_chars:
            latest_tail = f"...{latest_tail}"

        system_instruction += (
            "\n\nLatest transcript excerpt (for real-time/latest-detail questions):\n"
            "--- LATEST TRANSCRIPT EXCERPT START ---\n"
            f"{latest_tail}\n"
            "--- LATEST TRANSCRIPT EXCERPT END ---\n"
            "Treat this excerpt as the most recent raw transcript context. "
            "For precise older details, use list_summary_headings/get_summary_chunk."
        )

    llm_messages = [
        {
            "role": "system",
            "content": system_instruction,
        },
        *llm_messages,
    ]

    client, default_model, config = _build_openai_client_and_model()
    target_model = model or session.model_id or default_model

    tools = _get_server_tools() if enable_tools else []
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]

    max_iterations = int(os.getenv("ASYNC_LLM_TOOL_MAX_ITERATIONS", "4"))
    assistant_accumulated_text = ""
    persisted_tool_calls: dict[str, dict[str, Any]] = {}

    def _upsert_persisted_tool_call(call_data: dict[str, Any]) -> None:
        call_id = str(call_data.get("id") or "")
        if not call_id:
            return
        existing = persisted_tool_calls.get(call_id, {"id": call_id})
        for key, value in call_data.items():
            if value is not None:
                existing[key] = value
        persisted_tool_calls[call_id] = existing

    try:
        for _ in range(max_iterations):
            stream = await client.chat.completions.create(
                model=target_model,
                messages=llm_messages,  # type: ignore[arg-type]
                stream=True,
                temperature=temperature,
                tools=openai_tools if openai_tools else None,
                stream_options={"include_usage": True},
            )

            current_text = ""
            current_tool_calls: list[dict[str, Any] | None] = []

            async for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                delta = choice.delta if choice else None

                if delta and delta.content:
                    current_text += delta.content
                    out = {
                        "id": chunk.id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": target_model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": delta.content},
                                "finish_reason": None,
                            }
                        ],
                    }
                    yield _sse_payload(out)

                if delta and delta.tool_calls:
                    for tc in delta.tool_calls:
                        index = tc.index
                        while len(current_tool_calls) <= index:
                            current_tool_calls.append(None)
                        if current_tool_calls[index] is None:
                            current_tool_calls[index] = {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        existing = current_tool_calls[index]
                        if existing is None:
                            continue
                        if tc.id:
                            existing["id"] = tc.id
                        if tc.function and tc.function.name:
                            existing["function"]["name"] += tc.function.name
                        if tc.function and tc.function.arguments:
                            existing["function"]["arguments"] += tc.function.arguments

            valid_tool_calls = [c for c in current_tool_calls if c is not None]

            if not valid_tool_calls:
                assistant_accumulated_text += current_text
                break

            llm_messages.append(
                {
                    "role": "assistant",
                    "content": current_text or "",
                    "tool_calls": valid_tool_calls,
                }
            )

            for call in valid_tool_calls:
                fn_name = str(call["function"]["name"])
                raw_args = str(call["function"]["arguments"] or "{}")
                try:
                    parsed_args = json.loads(raw_args)
                except Exception:
                    parsed_args = {}

                tool_call_position = len(current_text)

                # Emit an execution-status chunk before running the tool, so client
                # can place tool cards exactly at the invocation boundary.
                yield _sse_payload(
                    {
                        "id": f"tool-start-{call.get('id', 'unknown')}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": target_model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_call_info": {
                                        "id": call.get("id"),
                                        "name": fn_name,
                                        "args": parsed_args,
                                        "position": tool_call_position,
                                        "status": "executing",
                                    }
                                },
                                "finish_reason": None,
                            }
                        ],
                    }
                )

                _upsert_persisted_tool_call(
                    {
                        "id": call.get("id"),
                        "name": fn_name,
                        "position": tool_call_position,
                        "args": parsed_args,
                        "status": "executing",
                    }
                )

                tool_result = await _execute_tool_call(
                    db=db,
                    session=session,
                    config=config,
                    tool_name=fn_name,
                    args=parsed_args,
                )

                llm_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    }
                )

                yield _sse_payload(
                    {
                        "id": f"tool-{call.get('id', 'unknown')}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": target_model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_call_info": {
                                        "id": call.get("id"),
                                        "name": fn_name,
                                        "args": parsed_args,
                                        "position": tool_call_position,
                                        "status": "error"
                                        if (
                                            isinstance(tool_result, dict)
                                            and "error" in tool_result
                                        )
                                        else "success",
                                        "result": tool_result,
                                    }
                                },
                                "finish_reason": None,
                            }
                        ],
                    }
                )

                _upsert_persisted_tool_call(
                    {
                        "id": call.get("id"),
                        "name": fn_name,
                        "position": tool_call_position,
                        "args": parsed_args,
                        "status": "error"
                        if (
                            isinstance(tool_result, dict)
                            and "error" in tool_result
                        )
                        else "success",
                        "result": tool_result,
                    }
                )

            # Continue to next LLM iteration with appended tool outputs.
            assistant_accumulated_text += current_text
        else:
            # Max iteration reached
            assistant_accumulated_text += "\n\n[Tool iteration limit reached.]"

        final_text = assistant_accumulated_text.strip()
        if not final_text:
            final_text = ""

        await create_message(
            db,
            session.id,
            "assistant",
            final_text,
            tool_calls=list(persisted_tool_calls.values()
                            ) if persisted_tool_calls else None,
        )

        yield "data: [DONE]\n\n"
    finally:
        await client.close()


def _summary_dir_for_session(session: Session, workspace_id: int) -> Path:
    return SUMMARY_DIR / str(session.user_id) / str(workspace_id) / f"session-{session.id}"


async def _get_or_create_summary_material(
    db: AsyncSession,
    session: Session,
    workspace_id: int,
    folder_id: int | None,
) -> Material:
    title = f"session-{session.id}-summary"
    existing = await db.execute(
        select(Material).where(
            Material.workspace_id == workspace_id,
            Material.user_id == session.user_id,
            Material.title == title,
        )
    )
    material = existing.scalars().first()
    if material:
        return material

    return await create_material(
        db,
        workspace_id=workspace_id,
        user_id=session.user_id,
        title=title,
        material_type="text",
        folder_id=folder_id,
        raw_content="",
        meta_data={"kind": "session_summary",
                   "session_id": session.id, "index": []},
        is_searchable=True,
    )


def _load_summary_files(summary_dir: Path) -> tuple[str, list[SummaryIndexEntry]]:
    summary_md_path = summary_dir / "summary.md"
    index_path = summary_dir / "summary_index.json"

    content = ""
    index: list[SummaryIndexEntry] = []

    if summary_md_path.exists():
        try:
            content = summary_md_path.read_text(encoding="utf-8")
        except Exception:
            content = ""

    if index_path.exists():
        try:
            raw = json.loads(index_path.read_text(encoding="utf-8"))
            for item in raw if isinstance(raw, list) else []:
                try:
                    index.append(
                        SummaryIndexEntry(
                            heading_no=int(item.get("heading_no", 0) or 0),
                            title=str(item.get("title") or "Untitled"),
                            chunk_id=str(item.get("chunk_id") or ""),
                            chunk_offset=int(item.get("chunk_offset", 0) or 0),
                            chunk_length=int(item.get("chunk_length", 0) or 0),
                            created_at=str(item.get("created_at") or ""),
                        )
                    )
                except Exception:
                    continue
        except Exception:
            index = []

    return content, index


def _write_summary_files(summary_dir: Path, content: str, index: list[SummaryIndexEntry]) -> None:
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_md_path = summary_dir / "summary.md"
    index_path = summary_dir / "summary_index.json"
    summary_md_path.write_text(content, encoding="utf-8")
    index_path.write_text(
        json.dumps([entry.__dict__ for entry in index],
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _fallback_summary(chunk_text: str, heading_no: int) -> tuple[str, list[str]]:
    trimmed = chunk_text.strip()
    if not trimmed:
        return f"{heading_no}. Empty chunk", []
    snippet = trimmed.replace("\n", " ")
    title = (snippet[:80] + "...") if len(snippet) > 80 else snippet
    sentences = [s.strip()
                 for s in snippet.replace("?", ".").split(".") if s.strip()]
    bullets = sentences[:3] if sentences else [snippet[:120]]
    return title, bullets


def _render_ai_index_tag(entry: SummaryIndexEntry) -> str:
    safe_title = (
        entry.title
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return (
        f'<ai_index heading_no="{entry.heading_no}" '
        f'title="{safe_title}" '
        f'chunk_id="{entry.chunk_id}" '
        f'chunk_offset="{entry.chunk_offset}" '
        f'chunk_length="{entry.chunk_length}" '
        f'created_at="{entry.created_at}" />'
    )


async def _summarize_chunk_with_llm(chunk_text: str, heading_no: int) -> tuple[str, list[str]]:
    client, target_model, _ = _build_openai_client_and_model()
    prompt = (
        "You are a concise meeting note taker. Given a transcript chunk, return JSON with keys 'title' and 'bullets'. "
        "Title max 80 chars, no numbering. Bullets: 3-6 short actionable points. Respond with JSON only."
    )

    try:
        resp = await client.chat.completions.create(
            model=target_model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": chunk_text[:4000]},
            ],
            temperature=0.3,
            max_tokens=500,
        )
        choice = resp.choices[0] if resp.choices else None
        content = choice.message.content if choice and choice.message else None
        if not content:
            raise ValueError("empty LLM content")
        parsed = json.loads(content)
        title = str(parsed.get("title") or "Summary").strip()
        bullets_raw = parsed.get("bullets") or []
        bullets = [str(b).strip() for b in bullets_raw if str(b).strip()]
        if not bullets:
            raise ValueError("no bullets")
        return title, bullets
    except Exception:
        return _fallback_summary(chunk_text, heading_no)
    finally:
        await client.close()


async def process_session_summary_job(
    db: AsyncSession,
    session: Session,
    *,
    chunk_text: str,
    chunk_offset: int = 0,
    chunk_length: int | None = None,
    total_length: int | None = None,
) -> dict[str, Any]:
    if not chunk_text.strip():
        # Return existing snapshot
        return await get_session_summary_snapshot(db, session)

    workspace_id = session.workspace_id
    if workspace_id is None:
        workspace = await get_or_create_user_root_workspace(db, session.user_id)
        workspace_id = workspace.id

    folder_id = session.folder_id
    summary_dir = _summary_dir_for_session(session, workspace_id)
    current_content, current_index = _load_summary_files(summary_dir)

    material = await _get_or_create_summary_material(db, session, workspace_id, folder_id)

    heading_no = len(current_index) + 1
    chunk_len = chunk_length if chunk_length is not None else len(chunk_text)
    chunk_id = f"{chunk_offset}-{chunk_len}"

    title, bullets = await _summarize_chunk_with_llm(chunk_text, heading_no)

    created_at = datetime.utcnow().isoformat() + "Z"
    new_entry = SummaryIndexEntry(
        heading_no=heading_no,
        title=title,
        chunk_id=chunk_id,
        chunk_offset=chunk_offset,
        chunk_length=chunk_len,
        created_at=created_at,
    )

    section_lines = [f"## {heading_no}. {title}", "",
                     "### Key Points"] + [f"- {b}" for b in bullets]
    section_lines += ["", _render_ai_index_tag(new_entry)]
    section_md = "\n".join(section_lines).strip() + "\n"

    new_content = current_content.rstrip()
    if new_content:
        new_content += "\n\n"
    new_content += section_md

    updated_index = [*current_index, new_entry]

    _write_summary_files(summary_dir, new_content, updated_index)

    relative_md_path = str((summary_dir / "summary.md").relative_to(BASE_DIR))
    material.raw_content = new_content
    material.file_path = relative_md_path
    material.meta_data = {
        "kind": "session_summary",
        "session_id": session.id,
        "index": [entry.__dict__ for entry in updated_index],
        "updated_at": created_at,
        "total_length": total_length,
    }
    await db.flush()

    return {
        "summary": new_content,
        "index": [entry.__dict__ for entry in updated_index],
        "updated_at": created_at,
    }


async def get_session_summary_snapshot(db: AsyncSession, session: Session) -> dict[str, Any]:
    workspace_id = session.workspace_id
    if workspace_id is None:
        workspace = await get_or_create_user_root_workspace(db, session.user_id)
        workspace_id = workspace.id

    summary_dir = _summary_dir_for_session(session, workspace_id)
    content, index = _load_summary_files(summary_dir)
    updated_at = ""
    if index:
        updated_at = max(
            (entry.created_at for entry in index if entry.created_at), default="")

    return {
        "summary": content,
        "index": [entry.__dict__ for entry in index],
        "updated_at": updated_at,
    }
