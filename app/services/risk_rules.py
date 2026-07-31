from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Priority, SystemSetting
from app.schemas import RiskThresholds, StructuredReport

ALWAYS_CRITICAL = {
    "data_breach",
    "safety_incident",
    "fraud_suspicion",
    "operational_failure",
}

CONFIDENTIAL_CATEGORIES = {
    "cash_discrepancy",
    "major_financial_loss",
    "legal_or_copyright",
    "employee_misconduct",
    "data_breach",
    "fraud_suspicion",
}


async def load_risk_thresholds(session: AsyncSession) -> RiskThresholds:
    values = {}
    for key in RiskThresholds.model_fields:
        setting = await session.get(SystemSetting, f"risk.{key}")
        if setting is not None:
            values[key] = setting.value
    return RiskThresholds(**values)


def apply_deterministic_risk_rules(
    report: StructuredReport,
    thresholds: RiskThresholds | None = None,
) -> StructuredReport:
    thresholds = thresholds or RiskThresholds()
    categories = set(report.risk_categories)
    money = report.money_risk

    critical = bool(categories & ALWAYS_CRITICAL)
    critical |= money.cash_discrepancy_uzs >= thresholds.cash_discrepancy_uzs
    critical |= money.direct_financial_loss_uzs >= thresholds.direct_financial_loss_uzs
    critical |= money.b2b_opportunity_at_risk_uzs >= thresholds.b2b_opportunity_at_risk_uzs

    high = bool(categories) or report.requires_action
    if critical:
        report.suggested_priority = Priority.CRITICAL
        report.requires_action = True
    elif high and report.suggested_priority in {Priority.NORMAL, Priority.MEDIUM}:
        report.suggested_priority = Priority.HIGH

    if categories & CONFIDENTIAL_CATEGORIES:
        report.confidential = True

    return report
