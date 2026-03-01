"""
File system batch operations models and handlers.

Implements batch operations for Workspace/Folder/Session entities,
using workspace_manager.py and session_manager.py as the data layer.
"""

from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.workspace_manager import (
    USER_ROOT_WORKSPACE_SENTINEL_ID,
    create_workspace,
    update_workspace,
    delete_workspace,
    get_workspace_by_id,
    get_or_create_user_root_workspace,
    is_user_root_workspace,
    add_session_scoped_folder_id,
    remove_session_scoped_folder_id,
    is_session_scoped_folder,
    create_folder,
    update_folder,
    delete_folder,
    get_folder_by_id,
)
from app.session_manager import (
    create_session,
    update_session,
    delete_session,
    get_session_by_id,
)
from app.models import Session


class OperationType(str, Enum):
    """Types of file system operations."""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    MOVE = "move"


class EntityType(str, Enum):
    """Types of entities in the tree."""
    WORKSPACE = "workspace"
    FOLDER = "folder"
    SESSION = "session"


class FileSystemOperation(BaseModel):
    """A single file system operation."""
    operation: OperationType
    id: Optional[int] = Field(
        None, description="Entity ID (ignored for CREATE, required for others)")
    type: EntityType = Field(...,
                             description="Entity type: workspace, folder, or session")
    name: Optional[str] = Field(
        None, description="Display name (for CREATE/UPDATE)")
    parent_id: Optional[int] = Field(
        None, description="Parent ID: workspace_id for folders, workspace_id/folder_id for sessions")
    # Backward compatibility
    is_directory: Optional[bool] = Field(
        None, description="DEPRECATED: Use 'type' instead")


class BatchOperationRequest(BaseModel):
    """Request body for batch file system operations."""
    operations: List[FileSystemOperation] = Field(
        ...,
        description="List of operations to execute in order"
    )


class OperationResult(BaseModel):
    """Result of a single operation."""
    operation: OperationType
    id: Optional[int] = None
    type: Optional[str] = None
    success: bool
    error: Optional[str] = None
    created_id: Optional[int] = None


class BatchOperationResponse(BaseModel):
    """Response for batch file system operations."""
    success: bool
    results: List[OperationResult]
    total: int
    succeeded: int
    failed: int


async def _folder_has_sessions(db: AsyncSession, folder_id: int, user_id: int) -> bool:
    result = await db.execute(
        select(Session.id).where(
            Session.folder_id == folder_id,
            Session.user_id == user_id,
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _is_session_folder(db: AsyncSession, ws, folder_id: int, user_id: int) -> bool:
    if is_session_scoped_folder(ws, folder_id):
        return True
    # Legacy fallback: folder containing sessions is treated as session-scoped.
    return await _folder_has_sessions(db, folder_id, user_id)


async def execute_operation(
    db: AsyncSession,
    user_id: int,
    operation: FileSystemOperation
) -> OperationResult:
    """
    Execute a single file system operation.

    Args:
        db: Database session
        user_id: User ID
        operation: Operation to execute

    Returns:
        OperationResult indicating success or failure
    """
    entity_type = operation.type
    op_type = operation.operation

    try:
        if op_type == OperationType.CREATE:
            return await _handle_create(db, user_id, operation, entity_type)
        elif op_type == OperationType.UPDATE:
            return await _handle_update(db, user_id, operation, entity_type)
        elif op_type == OperationType.DELETE:
            return await _handle_delete(db, user_id, operation, entity_type)
        elif op_type == OperationType.MOVE:
            return await _handle_move(db, user_id, operation, entity_type)
        else:
            raise ValueError(f"Unknown operation type: {op_type}")

    except Exception as e:
        return OperationResult(
            operation=op_type,
            id=operation.id,
            type=entity_type.value if entity_type else None,
            success=False,
            error=str(e)
        )


async def _handle_create(
    db: AsyncSession,
    user_id: int,
    operation: FileSystemOperation,
    entity_type: EntityType
) -> OperationResult:
    """Handle CREATE operation."""
    if not operation.name:
        raise ValueError("Name is required for CREATE operation")

    created_id: int

    if entity_type == EntityType.WORKSPACE:
        workspace = await create_workspace(db, user_id, operation.name)
        created_id = workspace.id

    elif entity_type == EntityType.FOLDER:
        if not operation.parent_id:
            raise ValueError(
                "parent_id (workspace_id) is required for creating a folder")
        # Verify user owns the workspace (or resolve user-root sentinel)
        if operation.parent_id == USER_ROOT_WORKSPACE_SENTINEL_ID:
            ws = await get_or_create_user_root_workspace(db, user_id)
        else:
            ws = await get_workspace_by_id(db, operation.parent_id, user_id)
        if not ws:
            raise ValueError(f"Workspace not found: {operation.parent_id}")
        folder = await create_folder(db, ws.id, operation.name)

        # Mark as session-folder (created through filesystem/session API)
        add_session_scoped_folder_id(ws, folder.id)

        created_id = folder.id

    elif entity_type == EntityType.SESSION:
        # parent_id can be workspace_id or folder_id
        workspace_id = None
        folder_id = None
        if operation.parent_id:
            if operation.parent_id == USER_ROOT_WORKSPACE_SENTINEL_ID:
                ws = await get_or_create_user_root_workspace(db, user_id)
                workspace_id = ws.id
                folder_id = None
            else:
                # Check if parent is a folder first
                folder = await get_folder_by_id(db, operation.parent_id)
                if folder:
                    parent_ws = await get_workspace_by_id(db, folder.workspace_id, user_id)
                    if not parent_ws or not await _is_session_folder(db, parent_ws, folder.id, user_id):
                        raise ValueError("Parent folder is not session-scoped")
                    folder_id = folder.id
                    workspace_id = folder.workspace_id
                else:
                    # Check if parent is a workspace
                    ws = await get_workspace_by_id(db, operation.parent_id, user_id)
                    if ws:
                        workspace_id = ws.id
                    else:
                        raise ValueError(
                            f"Parent not found: {operation.parent_id}")

        session = await create_session(
            db, user_id, operation.name,
            workspace_id=workspace_id,
            folder_id=folder_id
        )
        created_id = session.id
    else:
        raise ValueError(f"Unknown entity type: {entity_type}")

    return OperationResult(
        operation=OperationType.CREATE,
        id=operation.id,
        type=entity_type.value,
        success=True,
        created_id=created_id
    )


async def _handle_update(
    db: AsyncSession,
    user_id: int,
    operation: FileSystemOperation,
    entity_type: EntityType
) -> OperationResult:
    """Handle UPDATE operation."""
    if operation.id is None:
        raise ValueError("id is required for UPDATE operation")

    if entity_type == EntityType.WORKSPACE:
        ws = await get_workspace_by_id(db, operation.id, user_id)
        if is_user_root_workspace(ws):
            raise ValueError("System root folder cannot be modified")
        result = await update_workspace(db, operation.id, user_id, name=operation.name)
        if not result:
            raise ValueError(f"Workspace not found: {operation.id}")

    elif entity_type == EntityType.FOLDER:
        folder = await get_folder_by_id(db, operation.id)
        if not folder:
            raise ValueError(f"Folder not found: {operation.id}")
        ws = await get_workspace_by_id(db, folder.workspace_id, user_id)
        if not ws:
            raise ValueError(f"Unauthorized: folder {operation.id}")

        if not await _is_session_folder(db, ws, folder.id, user_id):
            raise ValueError("Folder is not in session namespace")

        result = await update_folder(db, operation.id, folder.workspace_id, name=operation.name)
        if not result:
            raise ValueError(f"Folder not found: {operation.id}")

    elif entity_type == EntityType.SESSION:
        result = await update_session(db, operation.id, user_id, title=operation.name)
        if not result:
            raise ValueError(f"Session not found: {operation.id}")
    else:
        raise ValueError(f"Unknown entity type: {entity_type}")

    return OperationResult(
        operation=OperationType.UPDATE,
        id=operation.id,
        type=entity_type.value,
        success=True
    )


async def _handle_delete(
    db: AsyncSession,
    user_id: int,
    operation: FileSystemOperation,
    entity_type: EntityType
) -> OperationResult:
    """Handle DELETE operation."""
    if operation.id is None:
        raise ValueError("id is required for DELETE operation")

    if entity_type == EntityType.WORKSPACE:
        if operation.id == USER_ROOT_WORKSPACE_SENTINEL_ID:
            raise ValueError("System root folder cannot be deleted")
        ws = await get_workspace_by_id(db, operation.id, user_id)
        if is_user_root_workspace(ws):
            raise ValueError("System root folder cannot be deleted")
        success = await delete_workspace(db, operation.id, user_id)
        if not success:
            raise ValueError(f"Workspace not found: {operation.id}")

    elif entity_type == EntityType.FOLDER:
        folder = await get_folder_by_id(db, operation.id)
        if not folder:
            raise ValueError(f"Folder not found: {operation.id}")
        ws = await get_workspace_by_id(db, folder.workspace_id, user_id)
        if not ws:
            raise ValueError(f"Unauthorized: folder {operation.id}")

        if not await _is_session_folder(db, ws, folder.id, user_id):
            raise ValueError("Folder is not in session namespace")

        # Remove from session-folder set if present
        remove_session_scoped_folder_id(ws, folder.id)

        success = await delete_folder(db, operation.id, folder.workspace_id)
        if not success:
            raise ValueError(f"Folder not found: {operation.id}")

    elif entity_type == EntityType.SESSION:
        success = await delete_session(db, operation.id, user_id)
        if not success:
            raise ValueError(f"Session not found: {operation.id}")
    else:
        raise ValueError(f"Unknown entity type: {entity_type}")

    return OperationResult(
        operation=OperationType.DELETE,
        id=operation.id,
        type=entity_type.value,
        success=True
    )


async def _handle_move(
    db: AsyncSession,
    user_id: int,
    operation: FileSystemOperation,
    entity_type: EntityType
) -> OperationResult:
    """Handle MOVE operation (change parent)."""
    if operation.id is None:
        raise ValueError("id is required for MOVE operation")

    if entity_type == EntityType.FOLDER:
        folder = await get_folder_by_id(db, operation.id)
        if not folder:
            raise ValueError(f"Folder not found: {operation.id}")
        ws = await get_workspace_by_id(db, folder.workspace_id, user_id)
        if not ws:
            raise ValueError(f"Unauthorized: folder {operation.id}")

        if not await _is_session_folder(db, ws, folder.id, user_id):
            raise ValueError("Folder is not in session namespace")

        if operation.parent_id is not None:
            parent_folder = await get_folder_by_id(db, operation.parent_id)
            if parent_folder:
                parent_ws = await get_workspace_by_id(db, parent_folder.workspace_id, user_id)
                if not parent_ws or not await _is_session_folder(db, parent_ws, parent_folder.id, user_id):
                    raise ValueError(
                        "Target parent folder is not session-scoped")

        result = await update_folder(
            db, operation.id, folder.workspace_id,
            parent_id=operation.parent_id
        )
        if not result:
            raise ValueError(f"Folder not found: {operation.id}")

    elif entity_type == EntityType.SESSION:
        session_obj = await get_session_by_id(db, operation.id, user_id)
        if not session_obj:
            raise ValueError(f"Session not found: {operation.id}")
        folder_id = None
        workspace_id = session_obj.workspace_id
        if operation.parent_id:
            if operation.parent_id == USER_ROOT_WORKSPACE_SENTINEL_ID:
                ws = await get_or_create_user_root_workspace(db, user_id)
                workspace_id = ws.id
                folder_id = None
            else:
                folder = await get_folder_by_id(db, operation.parent_id)
                if folder:
                    parent_ws = await get_workspace_by_id(db, folder.workspace_id, user_id)
                    if not parent_ws or not await _is_session_folder(db, parent_ws, folder.id, user_id):
                        raise ValueError(
                            "Target parent folder is not session-scoped")
                    folder_id = folder.id
                    workspace_id = folder.workspace_id
                else:
                    ws = await get_workspace_by_id(db, operation.parent_id, user_id)
                    if ws:
                        workspace_id = ws.id
        result = await update_session(
            db, operation.id, user_id,
            workspace_id=workspace_id,
            folder_id=folder_id
        )
        if not result:
            raise ValueError(f"Session not found: {operation.id}")
    else:
        raise ValueError(f"MOVE not supported for type: {entity_type}")

    return OperationResult(
        operation=OperationType.MOVE,
        id=operation.id,
        type=entity_type.value,
        success=True
    )


async def process_batch_operations(
    db: AsyncSession,
    user_id: int,
    operations: List[FileSystemOperation]
) -> BatchOperationResponse:
    """
    Process a batch of file system operations.

    All operations are executed within a single transaction.

    Args:
        db: Database session
        user_id: User ID
        operations: List of operations to execute

    Returns:
        BatchOperationResponse with results
    """
    results = []

    for operation in operations:
        result = await execute_operation(db, user_id, operation)
        results.append(result)

    succeeded = sum(1 for r in results if r.success)
    failed = len(results) - succeeded

    return BatchOperationResponse(
        success=(failed == 0),
        results=results,
        total=len(results),
        succeeded=succeeded,
        failed=failed
    )
