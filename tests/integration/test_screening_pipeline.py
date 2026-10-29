from app.models import ResearchQueueItem, ScreeningResult
from app.repos.screening_repo import ScreeningRepo
from app.services.discovery.screening_service import run_screening
from tests.conftest import AS_OF


def statuses(session, run_id):
    return {c.symbol: r.status for r, c in ScreeningRepo(session).results_for_run(run_id)}


def test_full_screening_run_over_fixture_market(session, providers, cfg):
    run = run_screening(session, providers, cfg, AS_OF)
    assert run.status == "completed" and run.rules_version == cfg.version
    s = statuses(session, run.id)
    assert s["SMPLNIFTYETF"] == s["SMPLLAMBDA"] == "excluded_instrument"
    assert s["SMPLETA"] == "ineligible"  # stale financials
    assert s["SMPLTHETA"] == "ineligible"  # 2 years of history
    assert s["SMPLZETA"] == "governance_review"  # auditor resignation
    assert s["SMPLIOTA"] == "rejected"  # illiquid
    assert s["SMPLGAMMA"] == "rejected"  # interest coverage below critical floor
    assert {"SMPLALPHA", "SMPLDELTA", "SMPLBETA"} <= {k for k, v in s.items() if v == "candidate"}

    rows = ScreeningRepo(session).results_for_run(run.id, "candidate")
    ranks = [r.rank for r, _ in rows]
    assert ranks == list(range(1, len(rows) + 1))
    scores = [r.score for r, _ in rows]
    assert scores == sorted(scores, reverse=True)

    # explainability: every excluded company says why
    for r, c in ScreeningRepo(session).results_for_run(run.id):
        if r.status != "candidate":
            assert r.exclusion_reasons, c.symbol

    # provenance persisted, and candidates queued for research
    assert run.summary["enqueued_for_research"] == session.query(ResearchQueueItem).count() > 0
    kappa = next(r for r, c in ScreeningRepo(session).results_for_run(run.id) if c.symbol == "SMPLKAPPA")
    assert any(i["code"] == "conflicting_values" for i in kappa.data_quality["issues"])
    assert "Industrials" in run.summary["sector_medians"]


def test_rerun_is_stable_and_does_not_duplicate_queue(session, providers, cfg):
    first = run_screening(session, providers, cfg, AS_OF)
    queued = session.query(ResearchQueueItem).count()
    second = run_screening(session, providers, cfg, AS_OF)
    assert session.query(ResearchQueueItem).count() == queued  # still pending: not re-enqueued
    a = {r.company_id: r.score for r in session.query(ScreeningResult).filter_by(run_id=first.id)}
    b = {r.company_id: r.score for r in session.query(ScreeningResult).filter_by(run_id=second.id)}
    assert a == b  # deterministic


def test_provider_failure_marks_run_failed(session, providers, cfg, monkeypatch):
    import dataclasses

    import pytest

    class Broken:
        name = "broken"

        def load_universe(self):
            return providers.universe.load_universe()

        def get_profile(self, symbol):
            raise RuntimeError("boom")

    bad = dataclasses.replace(providers, fundamentals=Broken())
    with pytest.raises(RuntimeError):
        run_screening(session, bad, cfg, AS_OF)
    run = ScreeningRepo(session).list_runs(1)[0]
    assert run.status == "failed" and "boom" in run.error
