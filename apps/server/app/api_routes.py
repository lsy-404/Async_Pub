"""API routes for authentication, workspace management, sessions, and messages."""

from datetime import datetime, timedelta, timezone
import uuid
from pathlib import Path
from typing import Annotated, Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, get_current_user_optional
from app.models import User, InviteToken as InviteTokenModel, Workspace, Folder, Session, Material
from app.auth import (
    authenticate_user,
    create_user,
    create_access_token,
    verify_invite_token,
    use_invite_token,
    create_invite_token,
    get_user_by_username,
)
from app.workspace_manager import (
    USER_ROOT_WORKSPACE_SENTINEL_ID,
    get_workspace_by_id,
    get_user_workspaces,
    get_or_create_user_root_workspace,
    is_user_root_workspace,
    get_workspace_session_folder_ids,
    resolve_workspace_or_user_root,
    create_workspace,
    update_workspace,
    delete_workspace,
    get_folder_by_id,
    get_workspace_folders,
    create_folder,
    update_folder,
    delete_folder,
    get_material_by_id,
    get_workspace_materials,
    create_material,
    update_material,
    delete_material,
)
from app.session_manager import (
    get_session_by_id,
    get_user_sessions,
    create_session,
    update_session,
    delete_session,
    get_session_messages,
    create_message,
    delete_message,
    clear_session_messages,
)
from app.session_chat import (
    stream_session_chat,
    process_session_summary_job,
    get_session_summary_snapshot,
)

# Create router
router = APIRouter()


async def _resolve_workspace_id(
    db: AsyncSession,
    current_user: User,
    workspace_id: int,
) -> int:
    """Resolve incoming workspace ID, allowing sentinel root ID to map to user root workspace."""
    ws = await resolve_workspace_or_user_root(db, workspace_id, current_user.id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws.id


async def _get_runtime_session_folder_ids(
    db: AsyncSession,
    current_user: User,
    workspace_id: int,
) -> set[int]:
    ws = await get_workspace_by_id(db, workspace_id, current_user.id)
    if not ws:
        return set()
    ids = set(get_workspace_session_folder_ids(ws))
    sessions = await get_user_sessions(db, current_user.id, workspace_id=workspace_id)
    ids.update(s.folder_id for s in sessions if s.folder_id is not None)
    return ids


def _material_upload_dir(user_id: int, workspace_id: int) -> Path:
    base = Path(__file__).resolve(
    ).parents[1] / "user-data" / "uploads" / str(user_id) / str(workspace_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


async def _save_uploaded_material_file(
    upload: UploadFile,
    user_id: int,
    workspace_id: int,
) -> tuple[str, int, Optional[str], str]:
    filename = upload.filename or "uploaded-file"
    suffix = Path(filename).suffix
    unique_name = f"{uuid.uuid4().hex}{suffix}"

    target_dir = _material_upload_dir(user_id, workspace_id)
    target_path = target_dir / unique_name

    content = await upload.read()
    target_path.write_bytes(content)

    relative_path = str(target_path.relative_to(
        Path(__file__).resolve().parents[1]))
    content_type = upload.content_type
    size_bytes = len(content)
    return relative_path, size_bytes, content_type, filename


# === Request/Response Models ===
class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6)
    email: Optional[str] = None
    invite_token: str


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: Optional[str]
    created_at: datetime
    last_login: Optional[datetime]


class CreateInviteRequest(BaseModel):
    token: str
    max_uses: int = 1
    expires_in_days: Optional[int] = None


class InviteTokenResponse(BaseModel):
    id: int
    token: str
    max_uses: int
    used_count: int
    expires_at: Optional[datetime]
    created_at: datetime
    is_active: bool


# --- Workspace ---
class WorkspaceResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    extra_data: Optional[dict] = None
    created_at: datetime


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    extra_data: Optional[dict] = None


class UpdateWorkspaceRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    extra_data: Optional[dict] = None


# --- Folder ---
class FolderResponse(BaseModel):
    id: int
    workspace_id: int
    parent_id: Optional[int] = None
    name: str


class CreateFolderRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    parent_id: Optional[int] = None


class UpdateFolderRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    parent_id: Optional[int] = None


# --- Session ---
class SessionCrudResponse(BaseModel):
    id: int
    user_id: int
    workspace_id: Optional[int] = None
    folder_id: Optional[int] = None
    title: str
    model_id: Optional[str] = None
    transcription: Optional[str] = None
    last_active_at: datetime
    created_at: datetime


class CreateSessionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    workspace_id: Optional[int] = None
    folder_id: Optional[int] = None
    model_id: Optional[str] = None


class UpdateSessionRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    workspace_id: Optional[int] = None
    folder_id: Optional[int] = None
    model_id: Optional[str] = None
    transcription: Optional[str] = None


# --- Material ---
class MaterialResponse(BaseModel):
    id: int
    workspace_id: int
    folder_id: Optional[int] = None
    title: str
    type: str
    file_path: Optional[str] = None
    meta_data: Optional[dict] = None
    created_at: datetime


class CreateMaterialRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    type: str = Field("file_ref", pattern="^(stt|text|file_ref)$")
    folder_id: Optional[int] = None
    raw_content: Optional[str] = None
    file_path: Optional[str] = None
    meta_data: Optional[dict] = None


class UpdateMaterialRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    folder_id: Optional[int] = None
    raw_content: Optional[str] = None
    meta_data: Optional[dict] = None


# --- UserData Tree ---
class UserDataNode(BaseModel):
    """Unified tree node for the userdata API."""
    model_config = {"json_schema_serialization_defaults_required": False}

    id: int
    name: str
    type: str  # "workspace" | "folder" | "session" | "file"
    children: Optional[List["UserDataNode"]] = None
    # workspace fields
    description: Optional[str] = None
    extra_data: Optional[dict] = None
    # session fields
    model_id: Optional[str] = None
    last_active_at: Optional[datetime] = None
    # material/file fields
    file_type: Optional[str] = None  # "stt" | "text" | "file_ref"
    file_path: Optional[str] = None
    meta_data: Optional[dict] = None
    # common
    created_at: Optional[datetime] = None

    def model_dump(self, **kwargs):
        """Override to exclude None values by default."""
        kwargs.setdefault("exclude_none", True)
        return super().model_dump(**kwargs)


# --- Message ---
class MessageResponse(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    tool_calls: Optional[List[dict]] = None
    created_at: datetime


class CreateMessageRequest(BaseModel):
    role: str = Field(..., pattern="^(system|user|assistant)$")
    content: str


class SessionChatCompletionRequest(BaseModel):
    content: str = Field(..., min_length=1)
    model: Optional[str] = None
    temperature: Optional[float] = Field(default=1.0, ge=0, le=2)
    transcription: Optional[str] = None
    stream: bool = True
    enable_tools: bool = True


class SessionSummaryHeading(BaseModel):
    heading_no: int
    title: str
    chunk_id: str
    chunk_offset: int
    chunk_length: int
    created_at: Optional[str] = None


class SessionSummaryResponse(BaseModel):
    summary: str
    index: List[SessionSummaryHeading]
    updated_at: Optional[str] = None


class SessionSummaryJobRequest(BaseModel):
    chunk: str = Field(..., min_length=1)
    chunk_offset: int = 0
    chunk_length: Optional[int] = None
    total_length: Optional[int] = None


# === Authentication Routes ===
@router.post("/auth/register", response_model=AuthResponse)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Register a new user with an invitation token.

    Requires:
    - Valid invitation token
    - Unique username
    - Password (min 6 characters)
    """
    # Verify invitation token
    is_valid, error_msg = await verify_invite_token(db, body.invite_token)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg or "Invalid invitation token"
        )

    # Check if username exists
    existing_user = await get_user_by_username(db, body.username)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken"
        )

    # Create user first – if this fails the invite must NOT be consumed
    try:
        user = await create_user(
            db=db,
            username=body.username,
            password=body.password,
            email=body.email
        )
    except Exception:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to create user"
        )

    # Consume invite token only after user creation succeeded
    await use_invite_token(db, body.invite_token)

    # Ensure system user-root exists for root-level file operations.
    await get_or_create_user_root_workspace(db, user.id)
    # Let get_db auto-commit; no explicit commit here to avoid double-commit

    # Generate access token
    access_token = create_access_token({"sub": str(user.id)})

    return AuthResponse(
        access_token=access_token,
        user_id=user.id,
        username=user.username
    )


@router.post("/auth/login", response_model=AuthResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Login with username and password.

    Returns JWT access token valid for 7 days.
    """
    user = await authenticate_user(db, body.username, body.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    await db.commit()

    # Generate access token
    access_token = create_access_token({"sub": str(user.id)})

    return AuthResponse(
        access_token=access_token,
        user_id=user.id,
        username=user.username
    )


@router.get("/auth/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user)
):
    """Get current authenticated user information."""
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        created_at=current_user.created_at,
        last_login=current_user.last_login
    )


class VerifyTokenRequest(BaseModel):
    """Request model for token verification."""
    token: str


@router.post("/auth/verify")
async def verify_token(
    body: VerifyTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Verify if a JWT token is valid.

    Returns 200 if token is valid, 401 if invalid.
    """
    from app.auth import decode_access_token, get_user_by_id

    # Decode token
    payload = decode_access_token(body.token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    # Get user ID from payload
    user_id_raw = payload.get("sub")
    if not user_id_raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )

    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )

    # Verify user exists and is active
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )

    return {
        "valid": True,
        "user_id": user.id,
        "username": user.username
    }


# === Invitation Management Routes ===
@router.post("/invites", response_model=InviteTokenResponse)
async def create_invite(
    body: CreateInviteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new invitation token.

    Only authenticated users can create invitations.
    """
    # Calculate expiration
    expires_at = None
    if body.expires_in_days:
        expires_at = datetime.utcnow() + timedelta(days=body.expires_in_days)

    invite = await create_invite_token(
        db=db,
        token=body.token,
        created_by=current_user.id,
        max_uses=body.max_uses,
        expires_at=expires_at
    )
    await db.commit()

    return InviteTokenResponse(
        id=invite.id,
        token=invite.token,
        max_uses=invite.max_uses,
        used_count=invite.used_count,
        expires_at=invite.expires_at,
        created_at=invite.created_at,
        is_active=invite.is_active
    )


@router.get("/invites", response_model=list[InviteTokenResponse])
async def list_invites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all invitation tokens created by current user."""
    from sqlalchemy import select

    result = await db.execute(
        select(InviteTokenModel)
        .where(InviteTokenModel.created_by == current_user.id)
        .order_by(InviteTokenModel.created_at.desc())
    )
    invites = result.scalars().all()

    return [
        InviteTokenResponse(
            id=inv.id,
            token=inv.token,
            max_uses=inv.max_uses,
            used_count=inv.used_count,
            expires_at=inv.expires_at,
            created_at=inv.created_at,
            is_active=inv.is_active
        )
        for inv in invites
    ]


# === File Management Routes ===
# DEPRECATED: These routes are being replaced with workspace/folder/material routes (Task 042)
# All file management routes have been removed. They will be reimplemented using:
# - workspace_manager.py for Workspace/Folder/Material operations
# - session_manager.py for Session/Message operations
# See task 042 for the refactoring plan.


# === UserData Tree Route ===

@router.get("/userdata", response_model=List[UserDataNode], response_model_exclude_none=True)
async def get_userdata(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Return the full data tree for the current user.

    Structure: root → workspaces → (folders | sessions | files)
    Each node carries a `type` field: "workspace", "folder", "session", or "file".
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    # Ensure system user-root workspace exists for every user.
    await get_or_create_user_root_workspace(db, current_user.id)

    # 1) Fetch all workspaces with eager-loaded relationships
    ws_result = await db.execute(
        select(Workspace)
        .where(Workspace.user_id == current_user.id)
        .options(
            selectinload(Workspace.folders),
            selectinload(Workspace.materials),
            selectinload(Workspace.sessions),
        )
        .order_by(Workspace.created_at)
    )
    workspaces = list(ws_result.scalars().unique().all())

    # 2) Build folder lookup  { folder_id -> Folder }
    #    and children map     { parent_id -> [Folder] }
    all_folders: dict[int, Folder] = {}
    folder_children: dict[Optional[int], list[Folder]] = {}
    for ws in workspaces:
        for f in ws.folders:
            all_folders[f.id] = f
            folder_children.setdefault(f.parent_id, []).append(f)

    # 3) Index sessions & materials by folder_id
    #    (folder_id=None means root level within the workspace)
    sessions_by_folder: dict[tuple[int, Optional[int]], list[Session]] = {}
    for ws in workspaces:
        for s in ws.sessions:
            key = (ws.id, s.folder_id)
            sessions_by_folder.setdefault(key, []).append(s)

    materials_by_folder: dict[tuple[int, Optional[int]], list[Material]] = {}
    for ws in workspaces:
        for m in ws.materials:
            key = (ws.id, m.folder_id)
            materials_by_folder.setdefault(key, []).append(m)

    # 4) Recursive builder for folder subtree
    def build_folder_node(folder: Folder, ws_id: int) -> UserDataNode:
        children: list[UserDataNode] = []
        # Sub-folders
        for child_f in sorted(
            folder_children.get(folder.id, []), key=lambda f: f.name
        ):
            children.append(build_folder_node(child_f, ws_id))
        # Sessions in this folder
        for s in sorted(
            sessions_by_folder.get((ws_id, folder.id), []),
            key=lambda s: s.last_active_at or s.created_at,
            reverse=True,
        ):
            children.append(UserDataNode(
                id=s.id, name=s.title, type="session",
                model_id=s.model_id,
                last_active_at=s.last_active_at,
                created_at=s.created_at,
            ))
        # Materials in this folder
        for m in sorted(
            materials_by_folder.get((ws_id, folder.id), []),
            key=lambda m: m.title,
        ):
            children.append(UserDataNode(
                id=m.id, name=m.title, type="file",
                file_type=m.type, file_path=m.file_path,
                meta_data=m.meta_data, created_at=m.created_at,
            ))
        return UserDataNode(
            id=folder.id, name=folder.name, type="folder",
            children=children if children else None,
        )

    # 5) Build workspace nodes
    tree: list[UserDataNode] = []
    for ws in workspaces:
        children: list[UserDataNode] = []
        # Root-level folders (parent_id is None AND belong to this workspace)
        root_folders = [
            f for f in folder_children.get(None, [])
            if f.workspace_id == ws.id
        ]
        for f in sorted(root_folders, key=lambda f: f.name):
            children.append(build_folder_node(f, ws.id))
        # Root-level sessions (folder_id=None)
        for s in sorted(
            sessions_by_folder.get((ws.id, None), []),
            key=lambda s: s.last_active_at or s.created_at,
            reverse=True,
        ):
            children.append(UserDataNode(
                id=s.id, name=s.title, type="session",
                model_id=s.model_id,
                last_active_at=s.last_active_at,
                created_at=s.created_at,
            ))
        # Root-level materials (folder_id=None)
        for m in sorted(
            materials_by_folder.get((ws.id, None), []),
            key=lambda m: m.title,
        ):
            children.append(UserDataNode(
                id=m.id, name=m.title, type="file",
                file_type=m.type, file_path=m.file_path,
                meta_data=m.meta_data, created_at=m.created_at,
            ))
        tree.append(UserDataNode(
            id=ws.id, name=ws.name, type="workspace",
            description=ws.description, extra_data=ws.extra_data,
            created_at=ws.created_at,
            children=children if children else None,
        ))

    return tree


# === Workspace Routes ===

@router.get("/workspaces", response_model=List[WorkspaceResponse])
async def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all workspaces for the current user."""
    workspaces = await get_user_workspaces(db, current_user.id)
    return [
        WorkspaceResponse(
            id=ws.id, name=ws.name,
            description=ws.description, extra_data=ws.extra_data,
            created_at=ws.created_at
        ) for ws in workspaces
    ]


@router.post("/workspaces", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace_route(
    body: CreateWorkspaceRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new workspace."""
    ws = await create_workspace(db, current_user.id, body.name, body.description, body.extra_data)
    await db.commit()
    return WorkspaceResponse(
        id=ws.id, name=ws.name,
        description=ws.description, extra_data=ws.extra_data,
        created_at=ws.created_at
    )


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace_route(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a workspace by ID."""
    ws = await get_workspace_by_id(db, workspace_id, current_user.id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return WorkspaceResponse(
        id=ws.id, name=ws.name,
        description=ws.description, extra_data=ws.extra_data,
        created_at=ws.created_at
    )


@router.put("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace_route(
    workspace_id: int,
    body: UpdateWorkspaceRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update workspace metadata."""
    target_ws = await get_workspace_by_id(db, workspace_id, current_user.id)
    if is_user_root_workspace(target_ws):
        raise HTTPException(
            status_code=403, detail="System root folder cannot be modified")

    ws = await update_workspace(
        db, workspace_id, current_user.id,
        name=body.name, description=body.description,
        extra_data=body.extra_data
    )
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    await db.commit()
    return WorkspaceResponse(
        id=ws.id, name=ws.name,
        description=ws.description, extra_data=ws.extra_data,
        created_at=ws.created_at
    )


@router.delete("/workspaces/{workspace_id}")
async def delete_workspace_route(
    workspace_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a workspace and all its contents."""
    if workspace_id == USER_ROOT_WORKSPACE_SENTINEL_ID:
        raise HTTPException(
            status_code=403, detail="System root folder cannot be deleted")

    target_ws = await get_workspace_by_id(db, workspace_id, current_user.id)
    if is_user_root_workspace(target_ws):
        raise HTTPException(
            status_code=403, detail="System root folder cannot be deleted")

    success = await delete_workspace(db, workspace_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Workspace not found")
    await db.commit()
    return {"success": True}


# === Folder Routes ===

@router.get("/workspaces/{workspace_id}/folders", response_model=List[FolderResponse])
async def list_folders(
    workspace_id: int,
    parent_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List folders in a workspace, optionally filtered by parent."""
    resolved_workspace_id = await _resolve_workspace_id(db, current_user, workspace_id)
    folders = await get_workspace_folders(db, resolved_workspace_id, parent_id)
    session_folder_ids = await _get_runtime_session_folder_ids(db, current_user, resolved_workspace_id)
    return [
        FolderResponse(
            id=f.id, workspace_id=f.workspace_id,
            parent_id=f.parent_id, name=f.name
        ) for f in folders if f.id not in session_folder_ids
    ]


@router.post("/workspaces/{workspace_id}/folders", response_model=FolderResponse, status_code=status.HTTP_201_CREATED)
async def create_folder_route(
    workspace_id: int,
    body: CreateFolderRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new folder in a workspace."""
    resolved_workspace_id = await _resolve_workspace_id(db, current_user, workspace_id)

    if body.parent_id is not None:
        parent = await get_folder_by_id(db, body.parent_id)
        if not parent or parent.workspace_id != resolved_workspace_id:
            raise HTTPException(
                status_code=404, detail="Parent folder not found")
        session_folder_ids = await _get_runtime_session_folder_ids(db, current_user, resolved_workspace_id)
        if parent.id in session_folder_ids:
            raise HTTPException(
                status_code=403, detail="Cannot create knowledge folder under session folder")

    folder = await create_folder(db, resolved_workspace_id, body.name, body.parent_id)
    await db.commit()
    return FolderResponse(
        id=folder.id, workspace_id=folder.workspace_id,
        parent_id=folder.parent_id, name=folder.name
    )


@router.put("/folders/{folder_id}", response_model=FolderResponse)
async def update_folder_route(
    folder_id: int,
    body: UpdateFolderRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update folder metadata."""
    folder = await get_folder_by_id(db, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    ws = await get_workspace_by_id(db, folder.workspace_id, current_user.id)
    if not ws:
        raise HTTPException(status_code=403, detail="Unauthorized")

    session_folder_ids = await _get_runtime_session_folder_ids(db, current_user, folder.workspace_id)
    if folder.id in session_folder_ids:
        raise HTTPException(
            status_code=403, detail="Session folder is managed by session file tree")

    if body.parent_id is not None:
        parent = await get_folder_by_id(db, body.parent_id)
        if not parent or parent.workspace_id != folder.workspace_id:
            raise HTTPException(
                status_code=404, detail="Parent folder not found")
        if parent.id in session_folder_ids:
            raise HTTPException(
                status_code=403, detail="Cannot move knowledge folder under session folder")

    result = await update_folder(db, folder_id, folder.workspace_id, body.name, body.parent_id)
    if not result:
        raise HTTPException(status_code=404, detail="Folder not found")
    await db.commit()
    return FolderResponse(
        id=result.id, workspace_id=result.workspace_id,
        parent_id=result.parent_id, name=result.name
    )


@router.delete("/folders/{folder_id}")
async def delete_folder_route(
    folder_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a folder and all its contents."""
    folder = await get_folder_by_id(db, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    ws = await get_workspace_by_id(db, folder.workspace_id, current_user.id)
    if not ws:
        raise HTTPException(status_code=403, detail="Unauthorized")

    session_folder_ids = await _get_runtime_session_folder_ids(db, current_user, folder.workspace_id)
    if folder.id in session_folder_ids:
        raise HTTPException(
            status_code=403, detail="Session folder is managed by session file tree")

    success = await delete_folder(db, folder_id, folder.workspace_id)
    if not success:
        raise HTTPException(status_code=404, detail="Folder not found")
    await db.commit()
    return {"success": True}


# === Material Routes ===

@router.post("/workspaces/{workspace_id}/materials", response_model=MaterialResponse, status_code=status.HTTP_201_CREATED)
async def create_material_route(
    workspace_id: int,
    body: CreateMaterialRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new material in a workspace."""
    resolved_workspace_id = await _resolve_workspace_id(db, current_user, workspace_id)

    material = await create_material(
        db, resolved_workspace_id, current_user.id, body.title, body.type,
        folder_id=body.folder_id, raw_content=body.raw_content,
        file_path=body.file_path, meta_data=body.meta_data
    )
    await db.commit()
    return MaterialResponse(
        id=material.id, workspace_id=material.workspace_id,
        folder_id=material.folder_id, title=material.title,
        type=material.type, file_path=material.file_path,
        meta_data=material.meta_data, created_at=material.created_at
    )


@router.post("/workspaces/{workspace_id}/materials/upload", response_model=MaterialResponse, status_code=status.HTTP_201_CREATED)
async def upload_material_route(
    workspace_id: int,
    file: UploadFile = File(...),
    folder_id: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upload a file and create a material entry under workspace/folder."""
    resolved_workspace_id = await _resolve_workspace_id(db, current_user, workspace_id)

    if folder_id is not None:
        folder = await get_folder_by_id(db, folder_id)
        if not folder or folder.workspace_id != resolved_workspace_id:
            raise HTTPException(status_code=404, detail="Folder not found")

    file_path, size_bytes, content_type, original_name = await _save_uploaded_material_file(
        file, current_user.id, resolved_workspace_id
    )

    material = await create_material(
        db,
        resolved_workspace_id,
        current_user.id,
        original_name,
        "file_ref",
        folder_id=folder_id,
        file_path=file_path,
        meta_data={
            "size_bytes": size_bytes,
            "content_type": content_type,
            "original_name": original_name,
        },
    )
    await db.commit()
    return MaterialResponse(
        id=material.id,
        workspace_id=material.workspace_id,
        folder_id=material.folder_id,
        title=material.title,
        type=material.type,
        file_path=material.file_path,
        meta_data=material.meta_data,
        created_at=material.created_at,
    )


@router.put("/materials/{material_id}", response_model=MaterialResponse)
async def update_material_route(
    material_id: int,
    body: UpdateMaterialRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update material metadata."""
    material = await get_material_by_id(db, material_id, current_user.id)
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")
    result = await update_material(
        db, material_id, current_user.id,
        title=body.title, folder_id=body.folder_id,
        raw_content=body.raw_content, meta_data=body.meta_data
    )
    if not result:
        raise HTTPException(status_code=404, detail="Material not found")
    await db.commit()
    return MaterialResponse(
        id=result.id, workspace_id=result.workspace_id,
        folder_id=result.folder_id, title=result.title,
        type=result.type, file_path=result.file_path,
        meta_data=result.meta_data, created_at=result.created_at
    )


@router.put("/materials/{material_id}/upload", response_model=MaterialResponse)
async def replace_material_file_route(
    material_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Replace file content for an existing material."""
    material = await get_material_by_id(db, material_id, current_user.id)
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")

    file_path, size_bytes, content_type, original_name = await _save_uploaded_material_file(
        file, current_user.id, material.workspace_id
    )

    updated = await update_material(
        db,
        material_id,
        current_user.id,
        title=original_name,
        meta_data={
            "size_bytes": size_bytes,
            "content_type": content_type,
            "original_name": original_name,
        },
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Material not found")

    updated.file_path = file_path
    updated.type = "file_ref"
    await db.commit()
    await db.refresh(updated)

    return MaterialResponse(
        id=updated.id,
        workspace_id=updated.workspace_id,
        folder_id=updated.folder_id,
        title=updated.title,
        type=updated.type,
        file_path=updated.file_path,
        meta_data=updated.meta_data,
        created_at=updated.created_at,
    )


@router.delete("/materials/{material_id}")
async def delete_material_route(
    material_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a material."""
    success = await delete_material(db, material_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Material not found")
    await db.commit()
    return {"success": True}


# === Session Routes ===

@router.get("/sessions", response_model=List[SessionCrudResponse])
async def list_sessions(
    workspace_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all sessions for the current user."""
    sessions = await get_user_sessions(db, current_user.id, workspace_id)
    return [
        SessionCrudResponse(
            id=s.id, user_id=s.user_id,
            workspace_id=s.workspace_id, folder_id=s.folder_id,
            title=s.title, model_id=s.model_id, transcription=s.transcription,
            last_active_at=s.last_active_at, created_at=s.created_at
        ) for s in sessions
    ]


@router.post("/sessions/create", response_model=SessionCrudResponse, status_code=status.HTTP_201_CREATED)
async def create_session_route(
    body: CreateSessionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new session."""
    resolved_workspace_id = body.workspace_id
    if resolved_workspace_id == USER_ROOT_WORKSPACE_SENTINEL_ID:
        root_ws = await get_or_create_user_root_workspace(db, current_user.id)
        resolved_workspace_id = root_ws.id

    session = await create_session(
        db, current_user.id, body.title,
        workspace_id=resolved_workspace_id,
        folder_id=body.folder_id,
        model_id=body.model_id
    )
    await db.commit()
    return SessionCrudResponse(
        id=session.id, user_id=session.user_id,
        workspace_id=session.workspace_id, folder_id=session.folder_id,
        title=session.title, model_id=session.model_id, transcription=session.transcription,
        last_active_at=session.last_active_at, created_at=session.created_at
    )


@router.get("/sessions/{session_id}", response_model=SessionCrudResponse)
async def get_session_route(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a session by ID."""
    session = await get_session_by_id(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionCrudResponse(
        id=session.id, user_id=session.user_id,
        workspace_id=session.workspace_id, folder_id=session.folder_id,
        title=session.title, model_id=session.model_id, transcription=session.transcription,
        last_active_at=session.last_active_at, created_at=session.created_at
    )


@router.put("/sessions/{session_id}", response_model=SessionCrudResponse)
async def update_session_route(
    session_id: int,
    body: UpdateSessionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update session metadata."""
    resolved_workspace_id = body.workspace_id
    if resolved_workspace_id == USER_ROOT_WORKSPACE_SENTINEL_ID:
        root_ws = await get_or_create_user_root_workspace(db, current_user.id)
        resolved_workspace_id = root_ws.id

    session = await update_session(
        db, session_id, current_user.id,
        title=body.title,
        workspace_id=resolved_workspace_id,
        folder_id=body.folder_id,
        model_id=body.model_id,
        transcription=body.transcription,
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.commit()
    return SessionCrudResponse(
        id=session.id, user_id=session.user_id,
        workspace_id=session.workspace_id, folder_id=session.folder_id,
        title=session.title, model_id=session.model_id, transcription=session.transcription,
        last_active_at=session.last_active_at, created_at=session.created_at
    )


@router.delete("/sessions/{session_id}")
async def delete_session_route(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a session and all its messages."""
    success = await delete_session(db, session_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.commit()
    return {"success": True}


# === Message Routes ===

@router.get("/sessions/{session_id}/messages", response_model=List[MessageResponse])
async def list_messages(
    session_id: int,
    limit: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all messages in a session."""
    # Verify session ownership
    session = await get_session_by_id(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = await get_session_messages(db, session_id, limit)
    return [
        MessageResponse(
            id=m.id, session_id=m.session_id,
            role=m.role, content=m.content,
            tool_calls=m.tool_calls,
            created_at=m.created_at
        ) for m in messages
    ]


@router.post("/sessions/{session_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def create_message_route(
    session_id: int,
    body: CreateMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new message in a session."""
    session = await get_session_by_id(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    message = await create_message(db, session_id, body.role, body.content)
    await db.commit()
    return MessageResponse(
        id=message.id, session_id=message.session_id,
        role=message.role, content=message.content,
        created_at=message.created_at
    )


@router.get("/sessions/{session_id}/summary", response_model=SessionSummaryResponse)
async def get_session_summary_route(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_session_by_id(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    snapshot = await get_session_summary_snapshot(db, session)
    return SessionSummaryResponse(
        summary=snapshot.get("summary", ""),
        index=[SessionSummaryHeading(**item)
               for item in snapshot.get("index", [])],
        updated_at=snapshot.get("updated_at"),
    )


@router.post("/sessions/{session_id}/summary/jobs", response_model=SessionSummaryResponse)
async def create_session_summary_job_route(
    session_id: int,
    body: SessionSummaryJobRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_session_by_id(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    result = await process_session_summary_job(
        db,
        session,
        chunk_text=body.chunk,
        chunk_offset=body.chunk_offset,
        chunk_length=body.chunk_length,
        total_length=body.total_length,
    )
    await db.commit()

    return SessionSummaryResponse(
        summary=result.get("summary", ""),
        index=[SessionSummaryHeading(**item)
               for item in result.get("index", [])],
        updated_at=result.get("updated_at"),
    )


@router.post("/sessions/{session_id}/chat/completions")
async def session_chat_completions_route(
    session_id: int,
    body: SessionChatCompletionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Session-bound chat completion stream with simple 10-round context.

    Migration constraints:
    - Uses neutral system instruction (no persona).
    - No pinpoint mode.
    - Context includes only last 10 rounds.
    - Context tools are supported when enabled.
    """
    if not body.stream:
        raise HTTPException(
            status_code=400,
            detail="Only stream=true is currently supported for session chat completions",
        )

    session = await get_session_by_id(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    stream = stream_session_chat(
        db=db,
        session=session,
        user_id=current_user.id,
        content=body.content,
        model=body.model,
        temperature=body.temperature,
        transcription_override=body.transcription,
        enable_tools=body.enable_tools,
    )

    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.delete("/sessions/{session_id}/messages")
async def clear_messages_route(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Clear all messages from a session."""
    session = await get_session_by_id(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    count = await clear_session_messages(db, session_id)
    await db.commit()
    return {"success": True, "deleted_count": count}


@router.delete("/messages/{message_id}")
async def delete_message_route(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a single message."""
    success = await delete_message(db, message_id)
    if not success:
        raise HTTPException(status_code=404, detail="Message not found")
    await db.commit()
    return {"success": True}
