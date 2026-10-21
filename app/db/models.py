from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    DateTime,
    ForeignKey,
    JSON,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False, default="Engineer")
    role = Column(String(50), nullable=False, default="engineer")  # "engineer", "admin"
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    tasks = relationship("TaskRecord", back_populates="user", cascade="all, delete-orphan")


class TaskRecord(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    objective = Column(Text, nullable=False)
    repository_url = Column(String(500), nullable=False)
    status = Column(String(50), nullable=False, default="received", index=True)
    repository_metadata = Column(JSON, nullable=True)
    evidence_stats = Column(JSON, nullable=True)
    orchestration_decision = Column(JSON, nullable=True)  # Jev System One decision
    memory_sync_status = Column(JSON, nullable=True)       # Obsidian sync status & path
    retry_count = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="tasks")
    report = relationship("ReportRecord", back_populates="task", uselist=False, cascade="all, delete-orphan")
    events = relationship("TaskEventRecord", back_populates="task", cascade="all, delete-orphan", order_by="TaskEventRecord.id")


class ReportRecord(Base):
    __tablename__ = "reports"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_id = Column(String(36), ForeignKey("tasks.id"), unique=True, nullable=False, index=True)
    summary = Column(Text, nullable=False)
    findings = Column(JSON, nullable=False, default=list)
    root_cause_hypotheses = Column(JSON, nullable=False, default=list)
    recommended_next_steps = Column(JSON, nullable=False, default=list)
    limitations = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    task = relationship("TaskRecord", back_populates="report")


class TaskEventRecord(Base):
    __tablename__ = "task_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(36), ForeignKey("tasks.id"), nullable=False, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    task = relationship("TaskRecord", back_populates="events")
