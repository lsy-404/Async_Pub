"""Workspace management utilities for new database structure."""

from typing import Any, Optional, List, Union
from datetime import datetime
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Workspace, Folder, Material, User


USER_ROOT_WORKSPACE_SENTINEL_ID = 0
USER_ROOT_WORKSPACE_NAME = "__USER_ROOT__"
USER_ROOT_WORKSPACE_EXTRA_DATA = {
    "system_kind": "user_root",
    "undeletable": True,
}

SESSION_FOLDER_IDS_KEY = "session_folder_ids"


def is_user_root_workspace(workspace: Workspace | None) -> bool:
    """Whether a workspace is the system user-root workspace."""
    if not workspace:
        return False
    extra_data = workspace.extra_data or {}
    return extra_data.get("system_kind") == "user_root"


def _coerce_int_id_set(values: Any) -> set[int]:
    if not isinstance(values, list):
        return set()
    result: set[int] = set()
    for value in values:
        if isinstance(value, int):
            result.add(value)
        elif isinstance(value, str) and value.isdigit():
            result.add(int(value))
    return result


def get_workspace_session_folder_ids(workspace: Workspace | None) -> set[int]:
    """Get session-scoped folder IDs stored in workspace metadata."""
    if not workspace:
        return set()
    extra_data = workspace.extra_data or {}
    return _coerce_int_id_set(extra_data.get(SESSION_FOLDER_IDS_KEY, []))


def is_session_scoped_folder(workspace: Workspace | None, folder_id: int) -> bool:
    """Whether a folder is explicitly session-scoped for a workspace."""
    return folder_id in get_workspace_session_folder_ids(workspace)


def add_session_scoped_folder_id(workspace: Workspace, folder_id: int) -> None:
    """Mark folder ID as session-scoped in workspace metadata."""
    extra_data = dict(workspace.extra_data or {})
    folder_ids = get_workspace_session_folder_ids(workspace)
    folder_ids.add(folder_id)
    extra_data[SESSION_FOLDER_IDS_KEY] = sorted(folder_ids)
    workspace.extra_data = extra_data


def remove_session_scoped_folder_id(workspace: Workspace, folder_id: int) -> None:
    """Remove folder ID from session-scoped metadata."""
    extra_data = dict(workspace.extra_data or {})
    folder_ids = get_workspace_session_folder_ids(workspace)
    folder_ids.discard(folder_id)
    extra_data[SESSION_FOLDER_IDS_KEY] = sorted(folder_ids)
    workspace.extra_data = extra_data


# === Workspace Management ===

async def get_workspace_by_id(
    db: AsyncSession,
    workspace_id: int,
    user_id: Optional[int] = None
) -> Optional[Workspace]:
    """
    Get workspace by ID, optionally filtered by user.

    Args:
        db: Database session
        workspace_id: Workspace ID
        user_id: Optional user ID to filter by

    Returns:
        Workspace object or None
    """
    query = select(Workspace).where(Workspace.id == workspace_id)

    if user_id:
        query = query.where(Workspace.user_id == user_id)

    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_user_workspaces(
    db: AsyncSession,
    user_id: int
) -> List[Workspace]:
    """
    Get all workspaces for a user.

    Args:
        db: Database session
        user_id: User ID

    Returns:
        List of Workspace objects
    """
    query = select(Workspace).where(
        Workspace.user_id == user_id
    ).order_by(Workspace.created_at)

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_user_root_workspace(
    db: AsyncSession,
    user_id: int,
) -> Optional[Workspace]:
    """Get system user-root workspace for a user, if it exists."""
    query = select(Workspace).where(
        Workspace.user_id == user_id,
        Workspace.name == USER_ROOT_WORKSPACE_NAME,
    ).order_by(Workspace.id.asc())
    result = await db.execute(query)
    return result.scalars().first()


async def get_or_create_user_root_workspace(
    db: AsyncSession,
    user_id: int,
) -> Workspace:
    """Get or create system user-root workspace for a user."""
    existing = await get_user_root_workspace(db, user_id)
    if existing:
        return existing

    workspace = Workspace(
        user_id=user_id,
        name=USER_ROOT_WORKSPACE_NAME,
        description="System user root",
        extra_data=USER_ROOT_WORKSPACE_EXTRA_DATA,
    )
    db.add(workspace)
    await db.flush()
    await db.refresh(workspace)
    return workspace


async def resolve_workspace_or_user_root(
    db: AsyncSession,
    workspace_id: int,
    user_id: int,
) -> Optional[Workspace]:
    """Resolve workspace by ID, where sentinel ID maps to user-root workspace."""
    if workspace_id == USER_ROOT_WORKSPACE_SENTINEL_ID:
        return await get_or_create_user_root_workspace(db, user_id)
    return await get_workspace_by_id(db, workspace_id, user_id)


async def create_workspace(
    db: AsyncSession,
    user_id: int,
    name: str,
    description: Optional[str] = None,
    extra_data: Optional[dict] = None
) -> Workspace:
    """
    Create a new workspace.

    Args:
        db: Database session
        user_id: User ID
        name: Workspace name
        description: Optional description
        extra_data: Optional JSON metadata

    Returns:
        Created Workspace object
    """
    workspace = Workspace(
        user_id=user_id,
        name=name,
        description=description,
        extra_data=extra_data
    )
    db.add(workspace)
    await db.flush()
    await db.refresh(workspace)
    return workspace


# Sentinel to distinguish "not provided" from "set to None"
_UNSET: Any = object()


async def update_workspace(
    db: AsyncSession,
    workspace_id: int,
    user_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    extra_data: Union[Optional[dict], Any] = _UNSET
) -> Optional[Workspace]:
    """
    Update workspace metadata.

    Args:
        db: Database session
        workspace_id: Workspace ID
        user_id: User ID (for authorization)
        name: Optional new name
        description: Optional new description
        extra_data: Optional JSON metadata (pass None to clear)

    Returns:
        Updated Workspace object or None
    """
    workspace = await get_workspace_by_id(db, workspace_id, user_id)
    if not workspace:
        return None

    if name is not None:
        workspace.name = name
    if description is not None:
        workspace.description = description
    if extra_data is not _UNSET:
        workspace.extra_data = extra_data

    await db.flush()
    await db.refresh(workspace)
    return workspace


async def delete_workspace(
    db: AsyncSession,
    workspace_id: int,
    user_id: int
) -> bool:
    """
    Delete a workspace and all its contents (cascading).

    Args:
        db: Database session
        workspace_id: Workspace ID
        user_id: User ID (for authorization)

    Returns:
        True if deleted, False if not found
    """
    workspace = await get_workspace_by_id(db, workspace_id, user_id)
    if not workspace:
        return False

    await db.delete(workspace)
    await db.flush()
    return True


# === Folder Management ===

async def get_folder_by_id(
    db: AsyncSession,
    folder_id: int,
    workspace_id: Optional[int] = None
) -> Optional[Folder]:
    """
    Get folder by ID, optionally filtered by workspace.

    Args:
        db: Database session
        folder_id: Folder ID
        workspace_id: Optional workspace ID to filter by

    Returns:
        Folder object or None
    """
    query = select(Folder).where(Folder.id == folder_id)

    if workspace_id:
        query = query.where(Folder.workspace_id == workspace_id)

    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_workspace_folders(
    db: AsyncSession,
    workspace_id: int,
    parent_id: Optional[int] = None
) -> List[Folder]:
    """
    Get folders in a workspace, optionally filtered by parent.

    Args:
        db: Database session
        workspace_id: Workspace ID
        parent_id: Parent folder ID (None for root)

    Returns:
        List of Folder objects
    """
    query = select(Folder).where(
        Folder.workspace_id == workspace_id,
        Folder.parent_id == parent_id
    ).order_by(Folder.name)

    result = await db.execute(query)
    return list(result.scalars().all())


async def create_folder(
    db: AsyncSession,
    workspace_id: int,
    name: str,
    parent_id: Optional[int] = None
) -> Folder:
    """
    Create a new folder.

    Args:
        db: Database session
        workspace_id: Workspace ID
        name: Folder name
        parent_id: Optional parent folder ID

    Returns:
        Created Folder object
    """
    folder = Folder(
        workspace_id=workspace_id,
        parent_id=parent_id,
        name=name
    )
    db.add(folder)
    await db.flush()
    await db.refresh(folder)
    return folder


async def update_folder(
    db: AsyncSession,
    folder_id: int,
    workspace_id: int,
    name: Optional[str] = None,
    parent_id: Optional[int] = None
) -> Optional[Folder]:
    """
    Update folder metadata.

    Args:
        db: Database session
        folder_id: Folder ID
        workspace_id: Workspace ID (for authorization)
        name: Optional new name
        parent_id: Optional new parent ID

    Returns:
        Updated Folder object or None
    """
    folder = await get_folder_by_id(db, folder_id, workspace_id)
    if not folder:
        return None

    if name is not None:
        folder.name = name
    if parent_id is not None:
        folder.parent_id = parent_id

    await db.flush()
    await db.refresh(folder)
    return folder


async def delete_folder(
    db: AsyncSession,
    folder_id: int,
    workspace_id: int
) -> bool:
    """
    Delete a folder and all its contents (cascading).

    Args:
        db: Database session
        folder_id: Folder ID
        workspace_id: Workspace ID (for authorization)

    Returns:
        True if deleted, False if not found
    """
    folder = await get_folder_by_id(db, folder_id, workspace_id)
    if not folder:
        return False

    await db.delete(folder)
    await db.flush()
    return True


# === Material Management ===

async def get_material_by_id(
    db: AsyncSession,
    material_id: int,
    user_id: Optional[int] = None
) -> Optional[Material]:
    """
    Get material by ID, optionally filtered by user.

    Args:
        db: Database session
        material_id: Material ID
        user_id: Optional user ID to filter by

    Returns:
        Material object or None
    """
    query = select(Material).where(Material.id == material_id)

    if user_id:
        query = query.where(Material.user_id == user_id)

    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_workspace_materials(
    db: AsyncSession,
    workspace_id: int,
    folder_id: Optional[int] = None
) -> List[Material]:
    """
    Get materials in a workspace, optionally filtered by folder.

    Args:
        db: Database session
        workspace_id: Workspace ID
        folder_id: Optional folder ID (None for root)

    Returns:
        List of Material objects
    """
    query = select(Material).where(
        Material.workspace_id == workspace_id,
        Material.folder_id == folder_id
    ).order_by(Material.title)

    result = await db.execute(query)
    return list(result.scalars().all())


async def create_material(
    db: AsyncSession,
    workspace_id: int,
    user_id: int,
    title: str,
    material_type: str,
    folder_id: Optional[int] = None,
    raw_content: Optional[str] = None,
    file_path: Optional[str] = None,
    meta_data: Optional[dict] = None,
    is_searchable: bool = True
) -> Material:
    """
    Create a new material.

    Args:
        db: Database session
        workspace_id: Workspace ID
        user_id: User ID
        title: Material title
        material_type: Type ('stt', 'text', 'file_ref')
        folder_id: Optional folder ID
        raw_content: Optional content text
        file_path: Optional file path/URL
        meta_data: Optional metadata JSON
        is_searchable: Whether searchable

    Returns:
        Created Material object
    """
    material = Material(
        workspace_id=workspace_id,
        folder_id=folder_id,
        user_id=user_id,
        title=title,
        type=material_type,
        raw_content=raw_content,
        file_path=file_path,
        meta_data=meta_data,
        is_searchable=is_searchable
    )
    db.add(material)
    await db.flush()
    await db.refresh(material)
    return material


async def update_material(
    db: AsyncSession,
    material_id: int,
    user_id: int,
    title: Optional[str] = None,
    folder_id: Optional[int] = None,
    raw_content: Optional[str] = None,
    meta_data: Optional[dict] = None,
    is_searchable: Optional[bool] = None
) -> Optional[Material]:
    """
    Update material metadata.

    Args:
        db: Database session
        material_id: Material ID
        user_id: User ID (for authorization)
        title: Optional new title
        folder_id: Optional new folder ID
        raw_content: Optional new content
        meta_data: Optional new metadata
        is_searchable: Optional new searchable flag

    Returns:
        Updated Material object or None
    """
    material = await get_material_by_id(db, material_id, user_id)
    if not material:
        return None

    if title is not None:
        material.title = title
    if folder_id is not None:
        material.folder_id = folder_id
    if raw_content is not None:
        material.raw_content = raw_content
    if meta_data is not None:
        material.meta_data = meta_data
    if is_searchable is not None:
        material.is_searchable = is_searchable

    await db.flush()
    await db.refresh(material)
    return material


async def delete_material(
    db: AsyncSession,
    material_id: int,
    user_id: int
) -> bool:
    """
    Delete a material.

    Args:
        db: Database session
        material_id: Material ID
        user_id: User ID (for authorization)

    Returns:
        True if deleted, False if not found
    """
    material = await get_material_by_id(db, material_id, user_id)
    if not material:
        return False

    await db.delete(material)
    await db.flush()
    return True
