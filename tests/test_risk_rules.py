from app.core.models import Priority
from app.schemas import MoneyRisk, StructuredReport
from app.services.risk_rules import apply_deterministic_risk_rules


def test_cash_discrepancy_threshold_is_critical():
    report = StructuredReport(
        risk_categories=["cash_discrepancy"],
        money_risk=MoneyRisk(cash_discrepancy_uzs=500_000),
    )
    result = apply_deterministic_risk_rules(report)
    assert result.suggested_priority == Priority.CRITICAL
    assert result.requires_action is True
    assert result.confidential is True


def test_b2b_below_threshold_is_high_not_critical():
    report = StructuredReport(
        risk_categories=["b2b_client_at_risk"],
        money_risk=MoneyRisk(b2b_opportunity_at_risk_uzs=19_999_999),
    )
    result = apply_deterministic_risk_rules(report)
    assert result.suggested_priority == Priority.HIGH


def test_data_breach_is_always_critical():
    report = StructuredReport(risk_categories=["data_breach"])
    result = apply_deterministic_risk_rules(report)
    assert result.suggested_priority == Priority.CRITICAL
    assert result.confidential is True
