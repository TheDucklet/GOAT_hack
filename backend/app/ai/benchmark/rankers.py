from datetime import datetime

from app.ai.benchmark.metrics import IMPACT_ORDER
from app.services.ranking import rank_event


def baseline_scores(context: dict, focus: dict, events: list[dict], now: datetime) -> dict[str, float]:
    return {item["id"]: rank_event(context, focus, item, now)[0] for item in events}


def order(scores: dict[str, float], events: list[dict]) -> list[str]:
    dates = {item["id"]: item["published_at"] for item in events}
    return sorted(scores, key=lambda key: (-scores[key], _inverse(dates[key]), key))


def _inverse(published_at: str) -> tuple:
    return tuple(-ord(char) for char in published_at)


def insight_scores(cards: dict[str, dict], baseline: dict[str, float]) -> dict[str, float]:
    scores = {}
    for event_id, envelope in cards.items():
        result = envelope["result"]
        level = IMPACT_ORDER[result["impact_level"]]
        steps = len(result["mechanism"])
        scores[event_id] = level * 1000 + steps * 10 + baseline.get(event_id, 0.0)
    return scores
