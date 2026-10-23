import csv
from itertools import combinations
from pathlib import Path

from app.ai.benchmark.data import BenchmarkContext, pair_id
from app.ai.summarization.vocabulary import PRODUCT_DESCRIPTIONS, flag_state
from app.data_semantics import confirmed_value

LABELS = (0, 1, 2)
SIGNIFICANT = 2
SHEET_COLUMNS = (
    "pair_id",
    "company",
    "role",
    "event_title",
    "event_date",
    "event_text",
    "label",
    "comment",
)
LABEL_MEANING = {
    0: "не относится к компании и должности",
    1: "относится как фон, действий или решений не требует",
    2: "значимо: должностное лицо должно увидеть это в ленте и учесть в ближайшие 12 месяцев",
}


STATE_WORDS = {"true": "да", "false": "нет", "unknown": "неизвестно"}


def company_line(context: dict) -> str:
    features = context["features"]

    def value(name: str) -> str:
        entry = features.get(name)
        return str(confirmed_value(entry)) if confirmed_value(entry) is not None else "неизвестно"

    products = ", ".join(
        f"{description} – {STATE_WORDS[flag_state(features, flag)]}"
        for flag, description in PRODUCT_DESCRIPTIONS.items()
    )
    trade = f"запись ФТС: {STATE_WORDS[flag_state(features, 'FTS_FLAG')]}"
    if confirmed_value(features.get("FTS_COUNTRY_NAME")):
        trade += f", страна в записи: {value('FTS_COUNTRY_NAME')}"
    revenue = (
        "выручка: единица и период не подтверждены"
        if "REVENUE_COMPANY" in features
        else "выручка: нет данных"
    )
    return "; ".join(
        [
            f"деятельность: {value('MAINOKVED_NAME')} (ОКВЭД {value('MAINOKVED_CODE')})",
            f"регион: {value('REGION')}",
            f"численность: {value('AMOUNT_WORKERS_FNS_GRADATION')}",
            f"возраст компании: {value('COMPANY_AGE_YEARS_GRADATION')}",
            f"продукты банка: {products}",
            trade,
            revenue,
        ]
    )


def sheet_rows(contexts: list[BenchmarkContext], events: list[dict], positions: dict) -> list[dict]:
    rows = []
    for context in contexts:
        for event in events:
            rows.append(
                {
                    "pair_id": pair_id(context.context_id, event["id"]),
                    "company": company_line(context.context),
                    "role": positions[context.role]["position_text"],
                    "event_title": event["title"],
                    "event_date": event["published_at"],
                    "event_text": event["text"],
                    "label": "",
                    "comment": "",
                }
            )
    return rows


def write_sheet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def read_labels(path: Path) -> dict[str, int]:
    labels: dict[str, int] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            raw = (row.get("label") or "").strip()
            if not raw:
                continue
            value = int(raw)
            if value not in LABELS:
                raise ValueError(f"недопустимая метка {value} в паре {row['pair_id']}")
            labels[row["pair_id"]] = value
    return labels


def adjudicate(label_sets: dict[str, dict[str, int]], pair_ids: list[str]) -> dict[str, dict]:
    result = {}
    for pair in pair_ids:
        given = {name: labels[pair] for name, labels in label_sets.items() if pair in labels}
        values = set(given.values())
        status = (
            "unlabeled"
            if not given
            else "agreed"
            if len(values) == 1 and len(given) == len(label_sets)
            else "disputed"
        )
        result[pair] = {
            "labels": given,
            "status": status,
            "final": next(iter(values)) if status == "agreed" else None,
            "any_significant": SIGNIFICANT in values,
        }
    return result


def cohen_kappa(first: dict[str, int], second: dict[str, int]) -> float | None:
    shared = sorted(set(first) & set(second))
    if not shared:
        return None
    total = len(shared)
    observed = sum(1 for key in shared if first[key] == second[key]) / total
    expected = sum(
        (sum(1 for key in shared if first[key] == label) / total)
        * (sum(1 for key in shared if second[key] == label) / total)
        for label in LABELS
    )
    if expected == 1:
        return None
    return round((observed - expected) / (1 - expected), 4)


def agreement_report(label_sets: dict[str, dict[str, int]]) -> dict:
    kappas = {
        f"{left}|{right}": cohen_kappa(label_sets[left], label_sets[right])
        for left, right in combinations(sorted(label_sets), 2)
    }
    return {
        "labelers": sorted(label_sets),
        "labeled_pairs": {k: len(v) for k, v in label_sets.items()},
        "kappa": kappas,
    }
