"""Session management for tracking user sessions."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional


class Session:
    """Represents a user session."""

    def __init__(
        self,
        session_id: str | None = None,
        user_id: str | None = None,
        timeout_minutes: int = 60,
    ):
        self.session_id = session_id or str(uuid.uuid4())
        self.user_id = user_id
        self.created_at = datetime.now(timezone.utc)
        self.last_accessed = self.created_at
        self.timeout_minutes = timeout_minutes
        self.metadata: dict = {}

    def is_expired(self) -> bool:
        """Check if session has expired."""
        timeout = timedelta(minutes=self.timeout_minutes)
        return datetime.now(timezone.utc) - self.last_accessed > timeout

    def touch(self):
        """Update last accessed time."""
        self.last_accessed = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        """Convert session to dictionary."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat(),
            "metadata": self.metadata,
        }


class SessionManager:
    """Manages user sessions in memory."""

    def __init__(self, timeout_minutes: int = 60, max_sessions_per_user: int = 10, db_manager=None):
        self._sessions: dict[str, Session] = {}
        self.timeout_minutes = timeout_minutes
        self.max_sessions_per_user = max_sessions_per_user
        self.db_manager = db_manager

    def create_session(self, user_id: str | None = None) -> Session:
        """Create a new session."""
        session = Session(user_id=user_id, timeout_minutes=self.timeout_minutes)
        self._sessions[session.session_id] = session
        
        # Default metadata
        session.metadata = {
            "ai_context": [],
            "transcription": ""
        }
        
        # Persist if db_manager is available
        if self.db_manager:
            self.db_manager.save_session_metadata(session.session_id, session.metadata)
            
        self._cleanup_expired()
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID."""
        session = self._sessions.get(session_id)
        if session and not session.is_expired():
            session.touch()
            return session
        elif session:
            # Remove expired session
            del self._sessions[session_id]
        
        # If not in memory, try to load from database if db_manager exists
        if self.db_manager:
            metadata = self.db_manager.get_session_metadata(session_id)
            if metadata:
                # Re-create session in memory
                # Note: user_id is not stored in session metadata currently, 
                # but we can improve this if needed.
                session = Session(session_id=session_id, timeout_minutes=self.timeout_minutes)
                session.metadata = metadata
                self._sessions[session_id] = session
                return session

        return None

    def update_session_metadata(self, session_id: str, metadata: dict):
        """Update session metadata and persist."""
        session = self.get_session(session_id)
        if session:
            session.metadata = metadata
            if self.db_manager:
                self.db_manager.save_session_metadata(session_id, metadata)

    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        found = False
        if session_id in self._sessions:
            del self._sessions[session_id]
            found = True
        
        if self.db_manager:
            # Check if it exists in DB to return True even if not in memory
            if self.db_manager.get_session_metadata(session_id):
                self.db_manager.delete_session_metadata(session_id)
                found = True
                
        return found

    def _cleanup_expired(self):
        """Remove expired sessions."""
        expired = [
            sid for sid, session in self._sessions.items() if session.is_expired()
        ]
        for sid in expired:
            del self._sessions[sid]

    def get_user_sessions(self, user_id: str) -> list[Session]:
        """Get all active sessions for a user."""
        self._cleanup_expired()
        return [s for s in self._sessions.values() if s.user_id == user_id]

    def count_active_sessions(self) -> int:
        """Count active sessions."""
        self._cleanup_expired()
        return len(self._sessions)
