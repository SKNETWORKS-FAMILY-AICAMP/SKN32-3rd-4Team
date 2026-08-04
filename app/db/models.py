"""SQLAlchemy ORM 모델 (커머스 코어 — 실습 잔재).

Product·Inventory·OrderItem은 아직 인증 모델과 같은 파일에 남은 레거시 커머스 스키마다.
커머스 CSV와 시더는 활성 경로에서 격리됐으며 보험 런타임의 DB 준비에는 쓰지 않는다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    # 역할(Phase 9). JWT에 넣지 않고 **매 요청 DB에서 읽는다** — 강등이 즉시 반영되도록.
    # 허용값은 app.auth.roles.ROLES. 알 수 없는 값은 USER로 폴백하지 않고 명시적 오류.
    role: Mapped[str] = mapped_column(String(20), default="USER", server_default="USER")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    orders: Mapped[list["Order"]] = relationship(back_populates="user")


class FaceCredential(Base):
    """얼굴 로그인 2차 인증 자격증명(Phase 13) — 사용자당 1개, opt-in.

    원본 사진은 저장하지 않고 정규화 임베딩(512 float32) 바이트만 저장한다.
    등록은 이미 로그인된 세션에서만 가능(미인증 상태에서 얼굴만으로 등록/로그인 경로 없음 —
    체인 잠김 방지). 얼굴 미등록 계정은 비밀번호 로그인만으로 토큰을 받는다(2차인증 미적용).
    """

    __tablename__ = "face_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    embedding: Mapped[bytes] = mapped_column(LargeBinary)  # np.float32[512].tobytes()
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # 예: P0001
    name: Mapped[str] = mapped_column(String(200), index=True)
    category: Mapped[str] = mapped_column(String(100))
    price: Mapped[int] = mapped_column(Integer)

    inventory: Mapped["Inventory"] = relationship(back_populates="product", uselist=False)


class Inventory(Base):
    __tablename__ = "inventory"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), unique=True)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    reorder_level: Mapped[int] = mapped_column(Integer, default=0)
    warehouse: Mapped[str] = mapped_column(String(100), default="")

    product: Mapped["Product"] = relationship(back_populates="inventory")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING / PAID
    total_amount: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    payment: Mapped["Payment"] = relationship(
        back_populates="order", uselist=False, cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    product_name: Mapped[str] = mapped_column(String(200))  # 주문시점 스냅샷
    unit_price: Mapped[int] = mapped_column(Integer)  # 주문시점 스냅샷
    quantity: Mapped[int] = mapped_column(Integer)

    order: Mapped["Order"] = relationship(back_populates="items")


class OrderIdempotency(Base):
    """주문 승인 멱등 레코드(Phase 6). (user_id, idempotency_key) 유일.

    같은 키·같은 요청지문(request_hash)이면 기존 order를 재생(중복 주문·재고차감 0);
    같은 키·다른 지문이면 ConflictErr(409). place와 **같은 트랜잭션**에서 기록한다.
    """

    __tablename__ = "order_idempotency"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key", name="uq_user_idem_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(80))
    request_hash: Mapped[str] = mapped_column(String(64))  # 요청 라인 정규 지문(SHA-256 hex)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True)
    amount: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="PAID")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    order: Mapped["Order"] = relationship(back_populates="payment")


class KnowledgeGap(Base):
    """지식보강 큐(Phase 9) — RAG가 근거를 못 찾아 abstention한 질문을 모은다.

    `run_events`는 "원문 저장 금지(요약만)" 관례지만 이 큐는 **질문 자체가 목적**이라 질문을
    저장한다. 대신 저장 전에 PII를 마스킹하고(app.obs.pii), 관리자 전용으로만 노출하며,
    보존기간이 지난 항목은 `manage.py purge-gaps`로 파기한다.
    """

    __tablename__ = "knowledge_gaps"

    id: Mapped[int] = mapped_column(primary_key=True)
    question: Mapped[str] = mapped_column(Text)  # 마스킹된 질문
    trace_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RunEvent(Base):
    """관측성 이벤트(trace 상관). 요청 처리 중 발생한 사건을 append-only로 기록한다.

    kind 예: "rag_query". detail은 JSON 문자열(민감정보·원문 저장 금지, 요약만).
    """

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(50), index=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
