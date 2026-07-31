from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Table,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class Language(str, enum.Enum):
    UZ = "uz"
    RU = "ru"


class ReportType(str, enum.Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    INCIDENT = "incident"
    APPROVAL = "approval"
    FREEFORM = "freeform"


class ReportStatus(str, enum.Enum):
    DRAFT = "draft"
    PROCESSING = "processing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    RETURNED = "returned"
    ACTION_REQUIRED = "action_required"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"
    FAILED = "failed"


class Priority(str, enum.Enum):
    NORMAL = "normal"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MessageKind(str, enum.Enum):
    TEXT = "text"
    VOICE = "voice"
    PHOTO = "photo"
    DOCUMENT = "document"
    CORRECTION = "correction"


class ManagerActionType(str, enum.Enum):
    APPROVE = "approve"
    RETURN = "return"
    COMMENT = "comment"
    REASSIGN = "reassign"
    CREATE_TASK = "create_task"
    ESCALATE = "escalate"
    RESOLVE = "resolve"


class ScheduleKind(str, enum.Enum):
    DAILY_PROMPT = "daily_prompt"
    WEEKLY_PROMPT = "weekly_prompt"
    DAILY_SUMMARY = "daily_summary"
    WEEKLY_SUMMARY = "weekly_summary"
    MONTHLY_SUMMARY = "monthly_summary"


class IntegrationStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD = "dead"


employee_roles = Table(
    "employee_roles",
    Base.metadata,
    Column("employee_id", Uuid, ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Uuid, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

employee_departments = Table(
    "employee_departments",
    Base.metadata,
    Column("employee_id", Uuid, ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True),
    Column("department_id", Uuid, ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True),
)

employee_branches = Table(
    "employee_branches",
    Base.metadata,
    Column("employee_id", Uuid, ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True),
    Column("branch_id", Uuid, ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True),
)

employee_extra_recipients = Table(
    "employee_extra_recipients",
    Base.metadata,
    Column("employee_id", Uuid, ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True),
    Column("recipient_id", Uuid, ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True),
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AdminUser(Base, TimestampMixin):
    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    language: Mapped[Language] = mapped_column(Enum(Language), default=Language.UZ)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False)


class Department(Base, TimestampMixin):
    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name_uz: Mapped[str] = mapped_column(String(255))
    name_ru: Mapped[str] = mapped_column(String(255))
    group_code: Mapped[str] = mapped_column(String(64), default="office", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    employees: Mapped[list[Employee]] = relationship(secondary=employee_departments, back_populates="departments")


class Branch(Base, TimestampMixin):
    __tablename__ = "branches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name_uz: Mapped[str] = mapped_column(String(255))
    name_ru: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    employees: Mapped[list[Employee]] = relationship(secondary=employee_branches, back_populates="branches")


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name_uz: Mapped[str] = mapped_column(String(255))
    name_ru: Mapped[str] = mapped_column(String(255))
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_manager: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    employees: Mapped[list[Employee]] = relationship(secondary=employee_roles, back_populates="roles")


class Employee(Base, TimestampMixin):
    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_user_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True, nullable=True)
    telegram_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language: Mapped[Language] = mapped_column(Enum(Language), default=Language.UZ)
    direct_manager_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    amocrm_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    visibility_scopes: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["own"])
    can_receive_reports: Mapped[bool] = mapped_column(Boolean, default=False)
    can_view_confidential: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    direct_manager: Mapped[Employee | None] = relationship(remote_side="Employee.id", foreign_keys=[direct_manager_id], backref="direct_reports")
    roles: Mapped[list[Role]] = relationship(secondary=employee_roles, back_populates="employees", lazy="selectin")
    departments: Mapped[list[Department]] = relationship(secondary=employee_departments, back_populates="employees", lazy="selectin")
    branches: Mapped[list[Branch]] = relationship(secondary=employee_branches, back_populates="employees", lazy="selectin")
    extra_recipients: Mapped[list[Employee]] = relationship(
        secondary=employee_extra_recipients,
        primaryjoin=id == employee_extra_recipients.c.employee_id,
        secondaryjoin=id == employee_extra_recipients.c.recipient_id,
        lazy="selectin",
    )
    reports: Mapped[list[Report]] = relationship(back_populates="employee", foreign_keys="Report.employee_id")


class ActivationCode(Base, TimestampMixin):
    __tablename__ = "activation_codes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(255), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)

    employee: Mapped[Employee] = relationship()


class ReportTemplate(Base, TimestampMixin):
    __tablename__ = "report_templates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    report_type: Mapped[ReportType] = mapped_column(Enum(ReportType), index=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("departments.id", ondelete="CASCADE"), nullable=True)
    role_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("roles.id", ondelete="CASCADE"), nullable=True)
    questions_uz: Mapped[list[str]] = mapped_column(JSON, default=list)
    questions_ru: Mapped[list[str]] = mapped_column(JSON, default=list)
    extraction_instructions: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class KPIDefinition(Base, TimestampMixin):
    __tablename__ = "kpi_definitions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name_uz: Mapped[str] = mapped_column(String(255))
    name_ru: Mapped[str] = mapped_column(String(255))
    unit: Mapped[str] = mapped_column(String(64), default="count")
    department_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("departments.id", ondelete="CASCADE"), nullable=True)
    role_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("roles.id", ondelete="CASCADE"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class EmployeeKPITarget(Base, TimestampMixin):
    __tablename__ = "employee_kpi_targets"
    __table_args__ = (UniqueConstraint("employee_id", "kpi_definition_id", "period", name="uq_employee_kpi_period"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    kpi_definition_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("kpi_definitions.id", ondelete="CASCADE"))
    period: Mapped[str] = mapped_column(String(16), default="daily")
    target_value: Mapped[float] = mapped_column()
    effective_from: Mapped[date] = mapped_column(Date, default=date.today)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)


class ReportSchedule(Base, TimestampMixin):
    __tablename__ = "report_schedules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[ScheduleKind] = mapped_column(Enum(ScheduleKind), index=True)
    group_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("departments.id", ondelete="CASCADE"), nullable=True)
    role_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("roles.id", ondelete="CASCADE"), nullable=True)
    local_time: Mapped[time] = mapped_column(Time)
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Monday=0
    grace_minutes: Mapped[int] = mapped_column(Integer, default=60)
    first_reminder_minutes: Mapped[int] = mapped_column(Integer, default=20)
    final_reminder_minutes: Mapped[int] = mapped_column(Integer, default=45)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Report(Base, TimestampMixin):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    report_type: Mapped[ReportType] = mapped_column(Enum(ReportType), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[ReportStatus] = mapped_column(Enum(ReportStatus), default=ReportStatus.DRAFT, index=True)
    priority: Mapped[Priority] = mapped_column(Enum(Priority), default=Priority.NORMAL, index=True)
    language: Mapped[str] = mapped_column(String(16), default="uz")
    original_text: Mapped[str] = mapped_column(Text, default="")
    structured_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ai_confidence: Mapped[float | None] = mapped_column(nullable=True)
    ai_questions: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_confidential: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    requires_action: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledgement_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_responsible_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True)
    amocrm_lead_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    amocrm_deal_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    amocrm_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)

    employee: Mapped[Employee] = relationship(back_populates="reports", foreign_keys=[employee_id], lazy="selectin")
    current_responsible: Mapped[Employee | None] = relationship(foreign_keys=[current_responsible_id], lazy="selectin")
    messages: Mapped[list[ReportMessage]] = relationship(back_populates="report", cascade="all, delete-orphan", lazy="selectin")
    recipients: Mapped[list[ReportRecipient]] = relationship(back_populates="report", cascade="all, delete-orphan", lazy="selectin")
    actions: Mapped[list[ManagerAction]] = relationship(back_populates="report", cascade="all, delete-orphan", lazy="selectin")


class ReportMessage(Base, TimestampMixin):
    __tablename__ = "report_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    kind: Mapped[MessageKind] = mapped_column(Enum(MessageKind))
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")
    file_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    report: Mapped[Report] = relationship(back_populates="messages")


class ReportRecipient(Base, TimestampMixin):
    __tablename__ = "report_recipients"
    __table_args__ = (UniqueConstraint("report_id", "employee_id", name="uq_report_recipient"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    routing_reason: Mapped[str] = mapped_column(String(255), default="direct_manager")
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    report: Mapped[Report] = relationship(back_populates="recipients")
    employee: Mapped[Employee] = relationship(lazy="selectin")


class ManagerAction(Base, TimestampMixin):
    __tablename__ = "manager_actions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    actor_employee_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    action_type: Mapped[ManagerActionType] = mapped_column(Enum(ManagerActionType), index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    report: Mapped[Report] = relationship(back_populates="actions")
    actor: Mapped[Employee] = relationship(lazy="selectin")


class PromptDelivery(Base, TimestampMixin):
    __tablename__ = "prompt_deliveries"
    __table_args__ = (UniqueConstraint("employee_id", "schedule_id", "delivery_date", name="uq_prompt_delivery"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    schedule_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("report_schedules.id", ondelete="CASCADE"), index=True)
    delivery_date: Mapped[date] = mapped_column(Date, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    final_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    overdue_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_report_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("reports.id", ondelete="SET NULL"), nullable=True)


class ComplianceIncident(Base, TimestampMixin):
    __tablename__ = "compliance_incidents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    incident_date: Mapped[date] = mapped_column(Date, index=True)
    missed_count_30d: Mapped[int] = mapped_column(Integer)
    level: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="open")
    reason_required: Mapped[bool] = mapped_column(Boolean, default=False)
    employee_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class IntegrationOutbox(Base, TimestampMixin):
    __tablename__ = "integration_outbox"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_outbox_idempotency"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    integration: Mapped[str] = mapped_column(String(32), default="amocrm")
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[IntegrationStatus] = mapped_column(Enum(IntegrationStatus), default=IntegrationStatus.PENDING, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class SystemSetting(Base, TimestampMixin):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_type: Mapped[str] = mapped_column(String(32), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
