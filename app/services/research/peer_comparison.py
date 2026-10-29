"""Peer statistics within a sector. Pure functions."""

import statistics
from collections import defaultdict

PEER_KEYS = (
    "pe", "pb", "ev_ebitda", "roce_latest", "roe_latest", "operating_margin_latest", "revenue_cagr",
    "debt_to_equity",
)  # fmt: skip

MIN_PEERS = 3  # a "sector median" of fewer companies is not a meaningful reference


def sector_medians(
    values_by_symbol: dict[str, dict[str, float | None]], sector_by_symbol: dict[str, str | None]
) -> dict[str, dict[str, float]]:
    """sector -> metric -> median over companies in that sector that have the metric."""
    buckets: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for symbol, values in values_by_symbol.items():
        sector = sector_by_symbol.get(symbol)
        if not sector:
            continue
        for key in PEER_KEYS:
            v = values.get(key)
            if v is not None:
                buckets[sector][key].append(v)
    return {
        s: {k: statistics.median(v) for k, v in m.items() if len(v) >= MIN_PEERS}
        for s, m in buckets.items()
    }


def percentile_rank(value: float, population: list[float]) -> float | None:
    """Share of the population at or below `value` (0..1)."""
    if not population:
        return None
    return sum(p <= value for p in population) / len(population)


def compare_to_peers(
    symbol: str, values: dict[str, float | None], peers: dict[str, dict[str, float | None]]
) -> dict[str, dict]:
    others = {s: v for s, v in peers.items() if s != symbol}
    table = {}
    for key in PEER_KEYS:
        mine = values.get(key)
        population = [v[key] for v in others.values() if v.get(key) is not None]
        table[key] = {
            "value": mine,
            "peer_median": statistics.median(population) if population else None,
            "percentile": percentile_rank(mine, population) if mine is not None else None,
            "peer_count": len(population),
        }
    return {"peers": sorted(others), "metrics": table}
