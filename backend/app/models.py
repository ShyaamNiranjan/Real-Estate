from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import CITEXT, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TZ = TIMESTAMP(timezone=True)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(TZ)
    google_sub: Mapped[str | None] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text, server_default="")
    avatar_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=text("now()"))
    last_login_at: Mapped[datetime | None] = mapped_column(TZ)
    deleted_at: Mapped[datetime | None] = mapped_column(TZ)


class UserCredential(Base):
    """Write-only for the API: app_rw can insert and update but never read password_hash."""

    __tablename__ = "user_credentials"
    __mapper_args__ = {"eager_defaults": False}

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    password_hash: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=text("now()"))


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    username: Mapped[str | None] = mapped_column(CITEXT, unique=True)
    display_name: Mapped[str] = mapped_column(Text, server_default="")
    kind: Mapped[str] = mapped_column(Text, server_default="solo")
    country_code: Mapped[str | None] = mapped_column(String(2))
    compliance_profile: Mapped[str | None] = mapped_column(Text)
    currency_default: Mapped[str] = mapped_column(String(3), server_default="USD")
    area_unit: Mapped[str] = mapped_column(Text, server_default="sqft")
    timezone: Mapped[str] = mapped_column(Text, server_default="UTC")
    plan_key: Mapped[str | None] = mapped_column(Text)
    subscription_state: Mapped[str] = mapped_column(Text, server_default="none")
    site_published_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=text("now()"))
    deleted_at: Mapped[datetime | None] = mapped_column(TZ)


class Membership(Base):
    __tablename__ = "memberships"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    role_id: Mapped[UUID | None]
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    invited_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    joined_at: Mapped[datetime] = mapped_column(TZ, server_default=text("now()"))
    removed_at: Mapped[datetime | None] = mapped_column(TZ)
