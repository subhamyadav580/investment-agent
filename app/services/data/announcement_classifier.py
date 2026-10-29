"""Maps exchange announcement subjects/text to the event categories used by governance rules, alerts, and
event-driven discovery. Pure and conservative: when unsure, it returns "other" rather than a severe category."""

import re

# Categories:
#   serious governance: auditor_resignation, auditor_qualification, sebi_order, insolvency
#   governance warning: regulatory_action, credit_rating_downgrade
#   discovery events:   results, order_win, acquisition, capacity_expansion, credit_rating_upgrade, debt_issue
#   context:            board_meeting, management_change, pledge_change, other


def _has(text: str, *words: str) -> bool:
    return any(w in text for w in words)


_SEBI_ORDER = re.compile(
    r"(order|penalty|penalties)\b[^.]{0,60}\b(passed|issued|imposed|levied) by (the )?(sebi|securities and exchange board)"
    r"|(sebi|securities and exchange board of india)( has)? (passed|issued|imposed|levied)"
)
_NON_STATUTORY_AUDITOR = re.compile(r"(internal|secretarial|cost|tax) auditor")


def _is_statutory_auditor_resignation(text: str) -> bool:
    if "auditor" not in text or not _has(text, "resign"):
        return False
    if "statutory auditor" in text:
        return True
    return not _NON_STATUTORY_AUDITOR.search(text)


def classify_announcement(subject: str | None, text: str | None) -> str:
    s = (subject or "").lower()
    t = (text or "").lower()
    both = f"{s} {t}"

    if _has(s, "corporate insolvency", "insolvency and bankruptcy", "liquidation"):
        return "insolvency"
    if _is_statutory_auditor_resignation(both):
        return "auditor_resignation"
    if _has(both, "qualified opinion", "modified opinion", "adverse opinion", "disclaimer of opinion") and not _has(
        both, "unmodified opinion", "unqualified opinion"
    ):
        return "auditor_qualification"
    # Nearly every filing cites "SEBI (LODR) Regulations", so "sebi" alone means nothing: require SEBI as the
    # body that passed an order or levied a penalty.
    if _SEBI_ORDER.search(t):
        return "sebi_order"
    if _has(s, "action(s) taken or orders passed", "action(s) initiated or orders passed") or _has(
        t, "insolvency resolution process", "petition under section 7", "petition under section 9"
    ):
        return "regulatory_action"
    if "credit rating" in s or "credit rating" in t:
        if _has(t, "downgrad", "rating watch with negative", "negative implications"):
            return "credit_rating_downgrade"
        if "upgrad" in t:
            return "credit_rating_upgrade"
        return "other"
    if _has(both, "pledge", "encumbrance"):
        return "pledge_change"
    if _has(s, "financial result") or (s.startswith("outcome of board meeting") and "financial result" in t):
        return "results"
    if _has(s, "bagging/receiving of orders", "awarding of order", "receipt of order"):
        return "order_win"
    if _has(s, "acquisition", "amalgamation", "merger", "takeover"):
        return "acquisition"
    if _has(s, "capacity addition", "commencement of commercial production", "commencement of operations"):
        return "capacity_expansion"
    if _has(s, "allotment of securities", "issue of securities", "fund raising") and re.search(
        r"debenture|\bncds?\b|bond", t
    ):
        return "debt_issue"
    if _has(s, "change in management", "resignation of director", "cessation", "change in director", "appointment"):
        return "management_change"
    return "other"
