"""SQLAlchemy database models."""

from datetime import datetime
from typing import Optional
from sqlalchemy import (
    String,
    Integer,
    BigInteger,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    Index,
    Enum as SQLEnum,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


def utcnow() -> datetime:
    """Get current UTC time (timezone-naive for MySQL compatibility)."""
    return datetime.utcnow()


class User(Base):
    """User account model."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )
    username: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
    last_login: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False)

    # Relationships
    workspaces: Mapped[list["Workspace"]] = relationship(
        "Workspace", back_populates="owner", cascade="all, delete-orphan"
    )
    materials: Mapped[list["Material"]] = relationship(
        "Material", back_populates="owner", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["Session"]] = relationship(
        "Session", back_populates="user", cascade="all, delete-orphan"
    )
    invite_tokens: Mapped[list["InviteToken"]] = relationship(
        "InviteToken", back_populates="creator"
    )

    # Indexes
    __table_args__ = (
        Index("idx_username", "username"),
        Index("idx_email", "email"),
    )


class InviteToken(Base):
    """Invitation token model."""

    __tablename__ = "invite_tokens"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )
    token: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False)

    # Relationships
    creator: Mapped[Optional["User"]] = relationship(
        "User", back_populates="invite_tokens"
    )

    # Indexes
    __table_args__ = (
        Index("idx_token", "token"),
        Index("idx_expires", "expires_at"),
    )


class Workspace(Base):
    """Workspace model - user-isolated top-level container."""

    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extra_data: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )

    # Relationships
    owner: Mapped["User"] = relationship("User", back_populates="workspaces")
    folders: Mapped[list["Folder"]] = relationship(
        "Folder", back_populates="workspace", cascade="all, delete-orphan"
    )
    materials: Mapped[list["Material"]] = relationship(
        "Material", back_populates="workspace", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["Session"]] = relationship(
        "Session", back_populates="workspace"
    )

    # Indexes
    __table_args__ = (
        Index("idx_user", "user_id"),
    )


class Folder(Base):
    """Folder model - supports unlimited hierarchy."""

    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )
    workspace_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False
    )
    parent_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("folders.id", ondelete="CASCADE"),
        nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Relationships
    workspace: Mapped["Workspace"] = relationship(
        "Workspace", back_populates="folders")
    parent: Mapped[Optional["Folder"]] = relationship(
        "Folder", remote_side=[id], back_populates="children"
    )
    children: Mapped[list["Folder"]] = relationship(
        "Folder", back_populates="parent", cascade="all, delete-orphan"
    )
    materials: Mapped[list["Material"]] = relationship(
        "Material", back_populates="folder"
    )
    sessions: Mapped[list["Session"]] = relationship(
        "Session", back_populates="folder"
    )

    # Indexes
    __table_args__ = (
        Index("idx_workspace_parent", "workspace_id", "parent_id"),
    )


class Material(Base):
    """Material/Document model - stores STT transcriptions, documents, or file references."""

    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )
    workspace_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False
    )
    folder_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("folders.id", ondelete="CASCADE"),
        nullable=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(
        SQLEnum("stt", "text", "file_ref", name="material_type"),
        nullable=False
    )
    raw_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True)
    meta_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_searchable: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship(
        "Workspace", back_populates="materials")
    folder: Mapped[Optional["Folder"]] = relationship(
        "Folder", back_populates="materials")
    owner: Mapped["User"] = relationship("User", back_populates="materials")

    # Indexes
    __table_args__ = (
        Index("idx_lookup", "workspace_id", "folder_id", "user_id"),
    )


class Session(Base):
    """Session model - supports optional workspace and folder binding."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    workspace_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True
    )
    folder_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("folders.id", ondelete="SET NULL"),
        nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    model_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    transcription: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="sessions")
    workspace: Mapped[Optional["Workspace"]] = relationship(
        "Workspace", back_populates="sessions")
    folder: Mapped[Optional["Folder"]] = relationship(
        "Folder", back_populates="sessions")
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="session", cascade="all, delete-orphan"
    )

    # Indexes
    __table_args__ = (
        Index("idx_user_workspace", "user_id", "workspace_id"),
        Index("idx_folder", "folder_id"),
    )


class Message(Base):
    """Message model - row-based message storage."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )
    session_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False
    )
    role: Mapped[str] = mapped_column(
        SQLEnum("system", "user", "assistant", name="message_role"),
        nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )

    # Relationships
    session: Mapped["Session"] = relationship(
        "Session", back_populates="messages")

    # Indexes
    __table_args__ = (
        Index("idx_session", "session_id"),
    )
