"""File management utilities.

DEPRECATED: This module is being replaced by workspace_manager.py and session_manager.py
as part of the database structure refactoring (Task 042).
This file is temporarily disabled to allow server startup.
"""

import os
import aiofiles
import mimetypes
from pathlib import Path
from typing import Optional, BinaryIO, Any
from datetime import datetime, timezone
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
# from app.models import File, User  # DEPRECATED: File model no longer exists
from app.models import User

# Type alias to allow existing function signatures to work
# This is a placeholder and these functions should not be used
File = Any  # DEPRECATED: Placeholder type


# Base directory for file storage
FILE_STORAGE_BASE = Path(os.getenv("FILE_STORAGE_PATH", "./user_files"))


def get_user_file_path(user_id: str, file_id: str) -> Path:
    """Get the full path for a user's file."""
    return FILE_STORAGE_BASE / user_id / file_id


async def ensure_user_directory(user_id: str):
    """Ensure user's file storage directory exists."""
    user_dir = FILE_STORAGE_BASE / user_id
    user_dir.mkdir(parents=True, exist_ok=True)


async def get_file_by_id(
    db: AsyncSession,
    file_id: str,
    user_id: Optional[str] = None
) -> Optional[File]:
    """
    Get file by ID, optionally filtered by user.
    
    Args:
        db: Database session
        file_id: File UUID
        user_id: Optional user ID to filter by
        
    Returns:
        File object or None
    """
    query = select(File).where(
        File.id == file_id,
        File.deleted_at.is_(None)
    )
    
    if user_id:
        query = query.where(File.user_id == user_id)
    
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_user_files(
    db: AsyncSession,
    user_id: str,
    parent_id: Optional[str] = None,
    include_deleted: bool = False
) -> list[File]:
    """
    Get all files for a user, optionally filtered by parent directory.
    
    Args:
        db: Database session
        user_id: User ID
        parent_id: Parent directory ID (None for root)
        include_deleted: Whether to include soft-deleted files
        
    Returns:
        List of File objects
    """
    query = select(File).where(
        File.user_id == user_id,
        File.parent_id == parent_id
    )
    
    if not include_deleted:
        query = query.where(File.deleted_at.is_(None))
    
    query = query.order_by(File.is_directory.desc(), File.display_name)
    
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_file_tree(
    db: AsyncSession,
    user_id: str,
    include_deleted: bool = False
) -> list[File]:
    """
    Get complete file tree for a user with eager loading.
    
    Args:
        db: Database session
        user_id: User ID
        include_deleted: Whether to include soft-deleted files
        
    Returns:
        List of root-level File objects with children loaded
    """
    query = select(File).where(
        File.user_id == user_id,
        File.parent_id.is_(None)
    ).options(
        selectinload(File.children)
    )
    
    if not include_deleted:
        query = query.where(File.deleted_at.is_(None))
    
    query = query.order_by(File.is_directory.desc(), File.display_name)
    
    result = await db.execute(query)
    return list(result.scalars().all())


async def create_file(
    db: AsyncSession,
    user_id: str,
    display_name: str,
    is_directory: bool = False,
    parent_id: Optional[str] = None,
    mime_type: Optional[str] = None
) -> File:
    """
    Create a new file or directory entry.
    
    Args:
        db: Database session
        user_id: Owner user ID
        display_name: Display name
        is_directory: Whether this is a directory
        parent_id: Parent directory ID
        mime_type: MIME type
        
    Returns:
        Created File object
    """
    # Verify parent exists if specified
    if parent_id:
        parent = await get_file_by_id(db, parent_id, user_id)
        if not parent or not parent.is_directory:
            raise ValueError("Invalid parent directory")
    
    file = File(
        user_id=user_id,
        original_name=display_name,
        display_name=display_name,
        is_directory=is_directory,
        parent_id=parent_id,
        mime_type=mime_type,
    )
    
    db.add(file)
    await db.flush()
    await db.refresh(file)
    
    # Create physical directory for user if needed
    if not is_directory:
        await ensure_user_directory(user_id)
    
    return file


async def update_file(
    db: AsyncSession,
    file_id: str,
    user_id: str,
    display_name: Optional[str] = None,
    parent_id: Optional[str] = None
) -> Optional[File]:
    """
    Update file metadata (rename, move).
    
    Args:
        db: Database session
        file_id: File ID
        user_id: Owner user ID
        display_name: New display name
        parent_id: New parent directory ID
        
    Returns:
        Updated File object or None
    """
    file = await get_file_by_id(db, file_id, user_id)
    if not file:
        return None
    
    if display_name is not None:
        file.display_name = display_name
    
    if parent_id is not None:
        # Verify new parent exists
        if parent_id:
            parent = await get_file_by_id(db, parent_id, user_id)
            if not parent or not parent.is_directory:
                raise ValueError("Invalid parent directory")
        file.parent_id = parent_id
    
    file.updated_at = datetime.utcnow()
    await db.flush()
    await db.refresh(file)
    
    return file


async def delete_file_recursive(
    db: AsyncSession,
    file_id: str,
    user_id: str,
    soft_delete: bool = True
) -> bool:
    """
    Delete a file or directory recursively.
    
    For directories, this will recursively delete all children first.
    
    Args:
        db: Database session
        file_id: File ID
        user_id: Owner user ID
        soft_delete: Whether to soft delete (mark as deleted) or hard delete
        
    Returns:
        True if deleted, False if not found
    """
    file = await get_file_by_id(db, file_id, user_id)
    if not file:
        return False
    
    # If it's a directory, recursively delete all children first
    if file.is_directory:
        children = await get_user_files(db, user_id, parent_id=file_id, include_deleted=False)
        for child in children:
            await delete_file_recursive(db, child.id, user_id, soft_delete)
    
    if soft_delete:
        # Soft delete: mark as deleted
        file.deleted_at = datetime.utcnow()
        await db.flush()
    else:
        # Hard delete: remove from database and filesystem
        if not file.is_directory:
            file_path = get_user_file_path(user_id, file_id)
            if file_path.exists():
                file_path.unlink()
        
        await db.delete(file)
        await db.flush()
    
    return True


async def delete_file(
    db: AsyncSession,
    file_id: str,
    user_id: str,
    soft_delete: bool = True
) -> bool:
    """
    Delete a file or directory (wrapper for recursive delete).
    
    Args:
        db: Database session
        file_id: File ID
        user_id: Owner user ID
        soft_delete: Whether to soft delete (mark as deleted) or hard delete
        
    Returns:
        True if deleted, False if not found
    """
    return await delete_file_recursive(db, file_id, user_id, soft_delete)


async def write_file_content(
    user_id: str,
    file_id: str,
    content: bytes
) -> tuple[int, str]:
    """
    Write content to a file.
    
    Args:
        user_id: User ID
        file_id: File ID
        content: File content bytes
        
    Returns:
        Tuple of (file_size, file_path)
    """
    await ensure_user_directory(user_id)
    file_path = get_user_file_path(user_id, file_id)
    
    async with aiofiles.open(file_path, 'wb') as f:
        await f.write(content)
    
    file_size = len(content)
    return file_size, str(file_path.relative_to(FILE_STORAGE_BASE))


async def read_file_content(user_id: str, file_id: str) -> Optional[bytes]:
    """
    Read file content.
    
    Args:
        user_id: User ID
        file_id: File ID
        
    Returns:
        File content bytes or None if not found
    """
    file_path = get_user_file_path(user_id, file_id)
    
    if not file_path.exists():
        return None
    
    async with aiofiles.open(file_path, 'rb') as f:
        return await f.read()


async def upload_file(
    db: AsyncSession,
    user_id: str,
    file_content: bytes,
    display_name: str,
    parent_id: Optional[str] = None
) -> File:
    """
    Upload a file with content.
    
    Args:
        db: Database session
        user_id: Owner user ID
        file_content: File content bytes
        display_name: Display name
        parent_id: Parent directory ID
        
    Returns:
        Created File object
    """
    # Guess MIME type from filename
    mime_type, _ = mimetypes.guess_type(display_name)
    
    # Create file entry
    file = await create_file(
        db=db,
        user_id=user_id,
        display_name=display_name,
        is_directory=False,
        parent_id=parent_id,
        mime_type=mime_type
    )
    
    # Write file content
    file_size, file_path = await write_file_content(
        user_id=user_id,
        file_id=file.id,
        content=file_content
    )
    
    # Update file metadata
    file.file_size = file_size
    file.file_path = file_path
    await db.flush()
    await db.refresh(file)
    
    return file


def guess_mime_type(filename: str) -> Optional[str]:
    """Guess MIME type from filename."""
    mime_type, _ = mimetypes.guess_type(filename)
    return mime_type
