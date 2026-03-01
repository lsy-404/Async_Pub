"""Session and message management utilities for new database structure."""

from typing import Optional, List
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Session, Message, User, Workspace


# === Session Management ===

async def get_session_by_id(
    db: AsyncSession,
    session_id: int,
    user_id: Optional[int] = None
) -> Optional[Session]:
    """
    Get session by ID, optionally filtered by user.

    Args:
        db: Database session
        session_id: Session ID
        user_id: Optional user ID to filter by

    Returns:
        Session object or None
    """
    query = select(Session).where(Session.id == session_id)

    if user_id:
        query = query.where(Session.user_id == user_id)

    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_user_sessions(
    db: AsyncSession,
    user_id: int,
    workspace_id: Optional[int] = None
) -> List[Session]:
    """
    Get all sessions for a user, optionally filtered by workspace.

    Args:
        db: Database session
        user_id: User ID
        workspace_id: Optional workspace ID to filter by

    Returns:
        List of Session objects
    """
    query = select(Session).where(Session.user_id == user_id)

    if workspace_id is not None:
        query = query.where(Session.workspace_id == workspace_id)

    query = query.order_by(Session.last_active_at.desc())

    result = await db.execute(query)
    return list(result.scalars().all())


async def create_session(
    db: AsyncSession,
    user_id: int,
    title: str,
    workspace_id: Optional[int] = None,
    folder_id: Optional[int] = None,
    model_id: Optional[str] = None,
    transcription: Optional[str] = None,
) -> Session:
    """
    Create a new session.

    Args:
        db: Database session
        user_id: User ID
        title: Session title
        workspace_id: Optional workspace ID to bind to
        folder_id: Optional folder ID to bind to
        model_id: Optional AI model ID

    Returns:
        Created Session object
    """
    session = Session(
        user_id=user_id,
        workspace_id=workspace_id,
        folder_id=folder_id,
        title=title,
        model_id=model_id,
        transcription=transcription,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


async def update_session(
    db: AsyncSession,
    session_id: int,
    user_id: int,
    title: Optional[str] = None,
    workspace_id: Optional[int] = None,
    folder_id: Optional[int] = None,
    model_id: Optional[str] = None,
    transcription: Optional[str] = None,
) -> Optional[Session]:
    """
    Update session metadata.

    Args:
        db: Database session
        session_id: Session ID
        user_id: User ID (for authorization)
        title: Optional new title
        workspace_id: Optional new workspace ID
        folder_id: Optional new folder ID
        model_id: Optional new model ID

    Returns:
        Updated Session object or None
    """
    session = await get_session_by_id(db, session_id, user_id)
    if not session:
        return None

    if title is not None:
        session.title = title
    if workspace_id is not None:
        session.workspace_id = workspace_id
    if folder_id is not None:
        session.folder_id = folder_id
    if model_id is not None:
        session.model_id = model_id
    if transcription is not None:
        session.transcription = transcription

    # Update last_active_at
    session.last_active_at = datetime.utcnow()

    await db.flush()
    await db.refresh(session)
    return session


async def delete_session(
    db: AsyncSession,
    session_id: int,
    user_id: int
) -> bool:
    """
    Delete a session and all its messages (cascading).

    Args:
        db: Database session
        session_id: Session ID
        user_id: User ID (for authorization)

    Returns:
        True if deleted, False if not found
    """
    session = await get_session_by_id(db, session_id, user_id)
    if not session:
        return False

    await db.delete(session)
    await db.flush()
    return True


# === Message Management ===

async def get_message_by_id(
    db: AsyncSession,
    message_id: int
) -> Optional[Message]:
    """
    Get message by ID.

    Args:
        db: Database session
        message_id: Message ID

    Returns:
        Message object or None
    """
    result = await db.execute(
        select(Message).where(Message.id == message_id)
    )
    return result.scalar_one_or_none()


async def get_session_messages(
    db: AsyncSession,
    session_id: int,
    limit: Optional[int] = None
) -> List[Message]:
    """
    Get all messages for a session.

    Args:
        db: Database session
        session_id: Session ID
        limit: Optional maximum number of messages to return

    Returns:
        List of Message objects ordered by creation time
    """
    query = select(Message).where(
        Message.session_id == session_id
    ).order_by(Message.created_at)

    if limit:
        query = query.limit(limit)

    result = await db.execute(query)
    return list(result.scalars().all())


async def create_message(
    db: AsyncSession,
    session_id: int,
    role: str,
    content: str,
    tool_calls: Optional[list[dict]] = None,
) -> Message:
    """
    Create a new message.

    Args:
        db: Database session
        session_id: Session ID
        role: Message role ('system', 'user', 'assistant')
        content: Message content

    Returns:
        Created Message object
    """
    message = Message(
        session_id=session_id,
        role=role,
        content=content,
        tool_calls=tool_calls,
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)

    # Update session's last_active_at
    session = await get_session_by_id(db, session_id)
    if session:
        session.last_active_at = datetime.utcnow()
        await db.flush()

    return message


async def delete_message(
    db: AsyncSession,
    message_id: int
) -> bool:
    """
    Delete a message.

    Args:
        db: Database session
        message_id: Message ID

    Returns:
        True if deleted, False if not found
    """
    message = await get_message_by_id(db, message_id)
    if not message:
        return False

    await db.delete(message)
    await db.flush()
    return True


async def clear_session_messages(
    db: AsyncSession,
    session_id: int
) -> int:
    """
    Clear all messages from a session.

    Args:
        db: Database session
        session_id: Session ID

    Returns:
        Number of messages deleted
    """
    messages = await get_session_messages(db, session_id)
    count = len(messages)

    for message in messages:
        await db.delete(message)

    await db.flush()
    return count
