from datetime import UTC, date, datetime, timedelta

from app.schemas.screening import Metric
from app.services.alerts.deduplication import deduplication_key, in_quiet_period
from app.services.alerts.notifier import MultiNotifier, format_alert
from app.services.alerts.rules import AlertContext, evaluate_alert_rules
from app.services.discovery.rules_config import AlertsCfg
from tests.fixtures.builders import announcement

AS_OF = date(2026, 10, 24)


def ctx(values=None, prev=None, **kw) -> AlertContext:
    values = values or {}
    metrics = {k: Metric(key=k, value=v, unit="ratio", period="FY2026") for k, v in values.items()}
    return AlertContext(symbol="TEST", exchange="NSE", as_of=AS_OF, since=AS_OF - timedelta(days=7), values=values,
                        prev_values=prev or {}, metrics=metrics, announcements=kw.pop("announcements", []),
                        cfg=kw.pop("cfg", AlertsCfg()), **kw)  # fmt: skip


def rule_ids(cands):
    return sorted(c.rule_id for c in cands)


def test_quiet_company_triggers_nothing():
    assert evaluate_alert_rules(ctx({"operating_margin_latest": 0.2, "operating_margin_prev": 0.21,
                                     "cfo_to_pat_3y": 0.9, "debt_to_equity": 0.3, "interest_coverage": 9})) == []  # fmt: skip


def test_threshold_rules():
    cands = evaluate_alert_rules(ctx({"operating_margin_latest": 0.12, "operating_margin_prev": 0.18,
                                      "profit_growth_latest": -0.35, "cfo_to_pat_3y": 0.3, "debt_to_equity": 1.6,
                                      "interest_coverage": 1.2}))  # fmt: skip
    assert rule_ids(cands) == ["cashflow_warning", "debt_warning", "debt_warning", "earnings_deterioration",
                               "earnings_deterioration"]  # fmt: skip
    icr = next(c for c in cands if c.trigger.startswith("Interest"))
    assert icr.severity == "critical"


def test_per_company_overrides():
    cfg = AlertsCfg().with_overrides({"max_debt_to_equity": 2.0, "unknown_key": 1})
    assert evaluate_alert_rules(ctx({"debt_to_equity": 1.6}, cfg=cfg)) == []


def test_debt_rules_skip_lenders():
    assert evaluate_alert_rules(ctx({"debt_to_equity": 9.0}, sector_group="financial")) == []


def test_governance_only_new_events():
    new = announcement("auditor_resignation", AS_OF - timedelta(days=2))
    old = announcement("sebi_order", AS_OF - timedelta(days=60))
    cands = evaluate_alert_rules(ctx(announcements=[new, old]))
    assert [c.severity for c in cands] == ["critical"] and "auditor_resignation" in cands[0].trigger


def test_valuation_watch_only_on_entering_range():
    vr = {"metric": "pe", "low": 15, "high": 20, "assumptions": "mid-cycle earnings"}
    assert rule_ids(evaluate_alert_rules(ctx({"pe": 18}, {"pe": 25}, valuation_range=vr))) == ["valuation_watch"]
    assert evaluate_alert_rules(ctx({"pe": 18}, {"pe": 19}, valuation_range=vr)) == []


def test_results_reminder_window():
    soon = announcement("board_meeting", AS_OF - timedelta(days=1), event_date=AS_OF + timedelta(days=3))
    later = announcement("board_meeting", AS_OF - timedelta(days=1), event_date=AS_OF + timedelta(days=30))
    assert rule_ids(evaluate_alert_rules(ctx(announcements=[soon, later]))) == ["results_reminder"]


def test_thesis_review_met_and_unverifiable():
    conds = [{"metric": "roce_latest", "op": "<", "value": 0.15}, {"metric": "gross_npa_pct", "op": ">", "value": 4}]
    cands = evaluate_alert_rules(ctx({"roce_latest": 0.11}, invalidation_conditions=conds))
    sev = {c.trigger.split(":")[0]: c.severity for c in cands}
    assert sev == {"Thesis invalidation condition met": "critical", "Thesis condition cannot be checked": "info"}


def test_dedup_key_and_quiet_period():
    assert deduplication_key(1, "r", "x") == deduplication_key(1, "r", "x") != deduplication_key(2, "r", "x")
    now = datetime(2026, 10, 24, tzinfo=UTC)
    assert in_quiet_period(now - timedelta(hours=10), now, 72)
    assert not in_quiet_period(now - timedelta(hours=80), now, 72)
    assert in_quiet_period((now - timedelta(hours=1)).replace(tzinfo=None), now, 72)  # naive from SQLite
    assert not in_quiet_period(None, now, 72)


def test_multi_notifier_reports_partial_failure():
    class Boom:
        def send(self, payload):
            raise ConnectionError("down")

    sent = []

    class Ok:
        def send(self, payload):
            sent.append(payload)

    try:
        MultiNotifier({"ok": Ok(), "telegram": Boom()}).send({"x": 1})
    except RuntimeError as e:
        assert "telegram" in str(e)
    else:
        raise AssertionError("expected failure")
    assert sent == [{"x": 1}]  # healthy channel still delivered


def test_format_alert_mentions_not_a_trade_instruction():
    c = evaluate_alert_rules(ctx({"cfo_to_pat_3y": 0.2}))[0]
    subject, body = format_alert({**c.model_dump(mode="json"), "triggered_at": "now"})
    assert "TEST" in subject and "not a trade instruction" in body
