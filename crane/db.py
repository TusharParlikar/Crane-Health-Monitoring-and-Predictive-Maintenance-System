"""Database tables: every reading with its scores, and alerts."""
import os
from datetime import datetime

from sqlalchemy import DateTime, Index, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

# Docker Compose sets PostgreSQL; local runs and tests fall back to SQLite.
engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///crane.db"))
Session = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Reading(Base):
    __tablename__ = "readings"
    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[str] = mapped_column(String(64))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    hoist_load: Mapped[float]
    motor_temp: Mapped[float]
    vibration: Mapped[float]
    duty_cycle: Mapped[float]
    anomaly: Mapped[bool]
    anomaly_score: Mapped[float]
    rul_days: Mapped[float]
    health: Mapped[float]
    __table_args__ = (Index("ix_readings_machine_id_id", "machine_id", "id"),)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # "anomaly" or "service_due"
    message: Mapped[str] = mapped_column(String(200))
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # NULL = still active


def as_dict(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}
