"""회원 서비스: 가입 / 인증."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.auth.security import hash_password, verify_password
from app.core.errors import AuthErr, ValidationErr
from app.db.models import User


def signup(db: Session, username: str, password: str) -> User:
    if db.query(User).filter(User.username == username).first():
        raise ValidationErr("이미 존재하는 사용자명입니다.")
    user = User(username=username, hashed_password=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, username: str, password: str) -> User:
    user = db.query(User).filter(User.username == username).first()
    if user is None or not verify_password(password, user.hashed_password):
        raise AuthErr("사용자명 또는 비밀번호가 올바르지 않습니다.")
    return user
