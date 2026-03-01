"""Authentication and authorization utilities."""

import os
import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import User, InviteToken


# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT settings
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.
    
    Args:
        data: Payload to encode in the token
        expires_delta: Token expiration time
        
    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """
    Decode and verify a JWT access token.
    
    Args:
        token: JWT token string
        
    Returns:
        Decoded payload or None if invalid
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    """Get user by username."""
    result = await db.execute(
        select(User).where(User.username == username, User.is_active == True)
    )
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    """Get user by ID."""
    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active == True)
    )
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    """Get user by email."""
    result = await db.execute(
        select(User).where(User.email == email, User.is_active == True)
    )
    return result.scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    username: str,
    password: str,
    email: Optional[str] = None
) -> User:
    """
    Create a new user.
    
    Args:
        db: Database session
        username: Username
        password: Plain text password
        email: Optional email address
        
    Returns:
        Created user object
    """
    hashed = hash_password(password)
    user = User(
        username=username,
        email=email,
        password_hash=hashed,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def authenticate_user(
    db: AsyncSession,
    username: str,
    password: str
) -> Optional[User]:
    """
    Authenticate a user by username and password.
    
    Args:
        db: Database session
        username: Username
        password: Plain text password
        
    Returns:
        User object if authenticated, None otherwise
    """
    user = await get_user_by_username(db, username)
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    
    # Update last login time
    user.last_login = datetime.utcnow()
    await db.flush()
    
    return user


async def verify_invite_token(db: AsyncSession, token: str) -> tuple[bool, Optional[str]]:
    """
    Verify an invitation token.
    
    Args:
        db: Database session
        token: Invitation token string
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    result = await db.execute(
        select(InviteToken).where(
            InviteToken.token == token,
            InviteToken.is_active == True
        )
    )
    invite = result.scalar_one_or_none()
    
    if not invite:
        return False, "Invalid invitation token"
    
    # Check if expired
    if invite.expires_at and invite.expires_at < datetime.utcnow():
        return False, "Invitation token has expired"
    
    # Check if max uses reached
    if invite.used_count >= invite.max_uses:
        return False, "Invitation token has reached maximum uses"
    
    return True, None


async def use_invite_token(db: AsyncSession, token: str) -> bool:
    """
    Mark an invitation token as used.
    
    Args:
        db: Database session
        token: Invitation token string
        
    Returns:
        True if successful, False otherwise
    """
    result = await db.execute(
        select(InviteToken).where(
            InviteToken.token == token,
            InviteToken.is_active == True
        )
    )
    invite = result.scalar_one_or_none()
    
    if not invite:
        return False
    
    invite.used_count += 1
    
    # Deactivate if max uses reached
    if invite.used_count >= invite.max_uses:
        invite.is_active = False
    
    await db.flush()
    return True


async def create_invite_token(
    db: AsyncSession,
    token: str,
    created_by: Optional[int] = None,
    max_uses: int = 1,
    expires_at: Optional[datetime] = None
) -> InviteToken:
    """
    Create a new invitation token.
    
    Args:
        db: Database session
        token: Token string
        created_by: User ID of creator (BIGINT)
        max_uses: Maximum number of uses
        expires_at: Expiration datetime
        
    Returns:
        Created InviteToken object
    """
    invite = InviteToken(
        token=token,
        created_by=created_by,
        max_uses=max_uses,
        expires_at=expires_at,
    )
    db.add(invite)
    await db.flush()
    await db.refresh(invite)
    return invite
