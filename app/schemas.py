from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.models import Language, Priority, ReportStatus, ReportType


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class BootstrapAdminRequest(BaseModel):
    bootstrap_key: str
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=10, max_length=128)
    language: Language = Language.UZ


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class NamedEntityCreate(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9_-]+$", max_length=64)
    name_uz: str = Field(min_length=2, max_length=255)
    name_ru: str = Field(min_length=2, max_length=255)
    group_code: str | None = None


class NamedEntityRead(ORMModel):
    id: uuid.UUID
    code: str
    name_uz: str
    name_ru: str
    is_active: bool


class RoleCreate(NamedEntityCreate):
    permissions: list[str] = Field(default_factory=list)
    is_manager: bool = False


class EmployeeCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    phone: str | None = None
    language: Language = Language.UZ
    role_ids: list[uuid.UUID] = Field(default_factory=list)
    department_ids: list[uuid.UUID] = Field(default_factory=list)
    branch_ids: list[uuid.UUID] = Field(default_factory=list)
    direct_manager_id: uuid.UUID | None = None
    extra_recipient_ids: list[uuid.UUID] = Field(default_factory=list)
    amocrm_user_id: int | None = None
    visibility_scopes: list[str] = Field(default_factory=lambda: ["own"])
    can_receive_reports: bool = False
    can_view_confidential: bool = False


class EmployeeUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    language: Language | None = None
    role_ids: list[uuid.UUID] | None = None
    department_ids: list[uuid.UUID] | None = None
    branch_ids: list[uuid.UUID] | None = None
    direct_manager_id: uuid.UUID | None = None
    extra_recipient_ids: list[uuid.UUID] | None = None
    amocrm_user_id: int | None = None
    visibility_scopes: list[str] | None = None
    can_receive_reports: bool | None = None
    can_view_confidential: bool | None = None
    is_active: bool | None = None


class EmployeeRead(ORMModel):
    id: uuid.UUID
    full_name: str
    phone: str | None
    telegram_user_id: int | None
    telegram_username: str | None
    language: Language
    direct_manager_id: uuid.UUID | None
    amocrm_user_id: int | None
    visibility_scopes: list[str]
    can_receive_reports: bool
    can_view_confidential: bool
    is_active: bool
    roles: list[NamedEntityRead] = Field(default_factory=list)
    departments: list[NamedEntityRead] = Field(default_factory=list)
    branches: list[NamedEntityRead] = Field(default_factory=list)


class ActivationCodeResponse(BaseModel):
    code: str
    expires_at: datetime


class KPIValue(BaseModel):
    code: str
    label: str
    value: float
    unit: str = "count"
    target: float | None = None


class MoneyRisk(BaseModel):
    cash_discrepancy_uzs: float = 0
    direct_financial_loss_uzs: float = 0
    b2b_opportunity_at_risk_uzs: float = 0


class StructuredReport(BaseModel):
    completed: list[str] = Field(default_factory=list)
    measurable_results: list[str] = Field(default_factory=list)
    kpis: list[KPIValue] = Field(default_factory=list)
    unfinished: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    help_or_approval: list[str] = Field(default_factory=list)
    tomorrow_plan: list[str] = Field(default_factory=list)
    urgent_summary: str | None = None
    risk_categories: list[
        Literal[
            "major_financial_loss",
            "cash_discrepancy",
            "legal_or_copyright",
            "serious_customer_complaint",
            "employee_misconduct",
            "data_breach",
            "operational_failure",
            "inventory_shortage",
            "missed_important_deadline",
            "b2b_client_at_risk",
            "safety_incident",
            "fraud_suspicion",
        ]
    ] = Field(default_factory=list)
    money_risk: MoneyRisk = Field(default_factory=MoneyRisk)
    requires_action: bool = False
    suggested_priority: Priority = Priority.NORMAL
    confidential: bool = False
    mentioned_customer_names: list[str] = Field(default_factory=list)
    mentioned_phone_numbers: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, default=0.5)


class ReportCreate(BaseModel):
    report_type: ReportType
    report_date: date = Field(default_factory=date.today)


class ReportRead(ORMModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    report_type: ReportType
    report_date: date
    status: ReportStatus
    priority: Priority
    original_text: str
    structured_data: dict[str, Any]
    ai_confidence: float | None
    is_confidential: bool
    requires_action: bool
    submitted_at: datetime | None
    confirmed_at: datetime | None
    amocrm_lead_id: int | None
    amocrm_deal_id: int | None
    amocrm_task_id: int | None
    created_at: datetime
    updated_at: datetime


class ReportCorrection(BaseModel):
    correction: str = Field(min_length=1, max_length=10000)


class ManagerActionRequest(BaseModel):
    action: Literal["approve", "return", "comment", "reassign", "create_task", "escalate", "resolve"]
    reason: str | None = Field(default=None, max_length=5000)
    assignee_id: uuid.UUID | None = None
    due_at: datetime | None = None


class DealMatch(BaseModel):
    id: int
    name: str
    responsible_user_id: int | None = None
    price: float | None = None
    status_id: int | None = None


class AdminUserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=10, max_length=128)
    language: Language = Language.UZ
    permissions: list[str] = Field(default_factory=list)
    is_superadmin: bool = False


class AdminUserRead(ORMModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    language: Language
    permissions: list[str]
    is_active: bool
    is_superadmin: bool
    created_at: datetime


class ReportTemplateCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    report_type: ReportType
    department_id: uuid.UUID | None = None
    role_id: uuid.UUID | None = None
    questions_uz: list[str] = Field(default_factory=list)
    questions_ru: list[str] = Field(default_factory=list)
    extraction_instructions: str = ""


class ReportTemplateRead(ORMModel):
    id: uuid.UUID
    name: str
    report_type: ReportType
    department_id: uuid.UUID | None
    role_id: uuid.UUID | None
    questions_uz: list[str]
    questions_ru: list[str]
    extraction_instructions: str
    is_active: bool


class KPIDefinitionCreate(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9_-]+$", max_length=64)
    name_uz: str
    name_ru: str
    unit: str = "count"
    department_id: uuid.UUID | None = None
    role_id: uuid.UUID | None = None


class KPIDefinitionRead(ORMModel):
    id: uuid.UUID
    code: str
    name_uz: str
    name_ru: str
    unit: str
    department_id: uuid.UUID | None
    role_id: uuid.UUID | None
    is_active: bool


class EmployeeKPITargetCreate(BaseModel):
    kpi_definition_id: uuid.UUID
    period: Literal["daily", "weekly", "monthly"] = "daily"
    target_value: float
    effective_from: date = Field(default_factory=date.today)
    effective_to: date | None = None


class RiskThresholds(BaseModel):
    cash_discrepancy_uzs: float = 500_000
    direct_financial_loss_uzs: float = 3_000_000
    b2b_opportunity_at_risk_uzs: float = 20_000_000
    critical_acknowledgement_hours: float = 2
