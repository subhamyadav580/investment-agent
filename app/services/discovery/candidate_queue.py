"""Hands ranked screening candidates to the deep-research queue (Postgres-backed; no Redis needed for v1)."""

from sqlalchemy.orm import Session

from app.repos.screening_repo import ResearchQueueRepo


def enqueue_candidates(
    session: Session, run_id: int, ranked: list[tuple[int, float, float]], top_n: int, min_score: float
) -> list[int]:
    """`ranked` = [(company_id, score, priority)] best first. The score gates eligibility; the priority
    (score plus any discovery boost) orders the queue. Skips companies already pending/running."""
    repo = ResearchQueueRepo(session)
    enqueued = []
    for company_id, score, priority in ranked:
        if len(enqueued) >= top_n:
            break
        if score < min_score or repo.has_open_item(company_id):
            continue
        repo.add(company_id, run_id, priority=priority)
        enqueued.append(company_id)
    return enqueued


def enqueue_one(session: Session, company_id: int, priority: float = 100.0) -> bool:
    repo = ResearchQueueRepo(session)
    if repo.has_open_item(company_id):
        return False
    repo.add(company_id, None, priority)
    return True
