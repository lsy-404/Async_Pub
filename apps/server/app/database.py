"""Database connection and session management."""

from typing import AsyncGenerator
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import DeclarativeBase


# Global variables for database engine and session maker
# These will be initialized by init_db() with the config
engine = None
AsyncSessionLocal = None


# Base class for models
class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


def init_database_config(database_url: str):
    """
    Initialize database engine and session maker with the provided URL.
    Must be called before using any database functions.

    Args:
        database_url: SQLAlchemy database connection URL
    """
    global engine, AsyncSessionLocal

    # Create async engine
    engine = create_async_engine(
        database_url,
        echo=False,  # Set to True for SQL query logging
        pool_pre_ping=True,  # Verify connections before using
        pool_recycle=3600,  # Recycle connections after 1 hour
    )

    # Create async session factory
    AsyncSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for getting database sessions.

    Usage:
        @app.get("/")
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """Initialize database tables."""
    if engine is None:
        raise RuntimeError(
            "Database engine not initialized. Call init_database_config() first.")

    def _ensure_schema_updates(sync_conn):
        inspector = inspect(sync_conn)
        table_names = set(inspector.get_table_names())
        if "messages" in table_names:
            msg_columns = {col["name"]
                           for col in inspector.get_columns("messages")}
            if "tool_calls" not in msg_columns:
                sync_conn.execute(
                    text("ALTER TABLE messages ADD COLUMN tool_calls JSON NULL"))

        if "sessions" in table_names:
            session_columns = {col["name"]
                               for col in inspector.get_columns("sessions")}
            if "transcription" not in session_columns:
                sync_conn.execute(
                    text("ALTER TABLE sessions ADD COLUMN transcription TEXT NULL"))

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_schema_updates)


async def close_db():
    """Close database connections."""
    if engine is not None:
        await engine.dispose()
