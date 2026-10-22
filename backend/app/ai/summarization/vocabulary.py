import argparse
import csv
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

from app.ai.rag.search import stem
from app.ai.summarization.grounding import normalize_text
from app.data_semantics import confirmed_value

VOCABULARY_PATH = Path(__file__).with_name("vocabulary.json")
CSV_DELIMITER = ";"
MAX_MATCHES = 10
MAX_CANDIDATES = 25
MAX_COUNTRY_VALUES = 300

THEMES: tuple[str, ...] = (
    "ключевая ставка",
    "инфляция",
    "курс рубля",
    "кредитование",
    "облигации",
    "золото",
    "потребление",
    "рынок труда",
    "бюджет и налоги",
    "ВВП",
    "промышленность",
    "нефть и газ",
    "металлургия",
    "сырьевые товары",
    "банковский сектор",
    "розничная торговля",
    "строительство и недвижимость",
    "импорт и экспорт",
    "санкции и ограничения",
    "цены на топливо",
    "торговые пошлины и тарифы",
    "логистика и транспорт",
    "валютное регулирование",
    "лизинг",
    "факторинг",
    "депозиты и ликвидность",
)

TRUE_VALUES = {"1", "1.0", "true", "True"}
FALSE_VALUES = {"0", "0.0", "false", "False"}

PRODUCT_FLAGS: tuple[str, ...] = (
    "CL_PRODUCT_RKO_MARK",
    "CL_PRODUCT_GAR_MARK",
    "CL_PRODUCT_LOA_MARK",
    "CL_PRODUCT_LEA_MARK",
    "CL_PRODUCT_DEP_MARK",
    "CL_PRODUCT_ZPP_MARK",
    "FACTORING_MARK",
)

PRODUCT_DESCRIPTIONS: dict[str, str] = {
    "CL_PRODUCT_RKO_MARK": "расчётно-кассовое обслуживание",
    "CL_PRODUCT_GAR_MARK": "банковские гарантии",
    "CL_PRODUCT_LOA_MARK": "кредиты",
    "CL_PRODUCT_LEA_MARK": "лизинг",
    "CL_PRODUCT_DEP_MARK": "депозиты",
    "CL_PRODUCT_ZPP_MARK": "зарплатный проект",
    "FACTORING_MARK": "факторинг",
}


def canonical(values: list[str], allowed: tuple[str, ...]) -> list[str]:
    by_key = {normalize_text(item): item for item in allowed}
    kept: list[str] = []
    for value in values:
        match = by_key.get(normalize_text(value))
        if match and match not in kept:
            kept.append(match)
    return kept


def canonical_themes(values: list[str]) -> list[str]:
    return canonical(values, THEMES)


THEME_PRODUCTS: dict[str, tuple[str, ...]] = {
    "ключевая ставка": (
        "CL_PRODUCT_LOA_MARK",
        "CL_PRODUCT_LEA_MARK",
        "CL_PRODUCT_DEP_MARK",
        "FACTORING_MARK",
    ),
    "кредитование": ("CL_PRODUCT_LOA_MARK",),
    "лизинг": ("CL_PRODUCT_LEA_MARK",),
    "факторинг": ("FACTORING_MARK",),
    "депозиты и ликвидность": ("CL_PRODUCT_DEP_MARK",),
    "банковский сектор": ("CL_PRODUCT_RKO_MARK",),
    "валютное регулирование": ("CL_PRODUCT_RKO_MARK",),
}


def products_for_themes(themes: list[str]) -> list[str]:
    return list(dict.fromkeys(flag for theme in themes for flag in THEME_PRODUCTS.get(theme, ())))


@lru_cache
def load_vocabulary() -> dict:
    return json.loads(VOCABULARY_PATH.read_text(encoding="utf-8"))


def _matches(keywords: list[str], values: list[dict], limit: int = MAX_MATCHES) -> list[str]:
    stems = [stem(keyword.lower().strip()) for keyword in keywords if keyword.strip()]
    found = [item for item in values if any(prefix and prefix in item["value"].lower() for prefix in stems)]
    found.sort(key=lambda item: (-item["count"], item["value"]))
    return [item["value"] for item in found[:limit]]


def match_industries(keywords: list[str], limit: int = MAX_CANDIDATES) -> list[str]:
    return _matches(keywords, load_vocabulary()["industries"], limit)


def match_regions(names: list[str]) -> list[str]:
    vocabulary = load_vocabulary()
    return _matches(names, vocabulary["regions"] + vocabulary["cities"])


def match_countries(names: list[str]) -> list[str]:
    return _matches(names, load_vocabulary()["countries"])


def _ranked(counter: Counter, limit: int | None = None) -> list[dict]:
    items = [{"value": value, "count": count} for value, count in counter.most_common(limit) if value]
    return sorted(items, key=lambda item: (-item["count"], item["value"]))


def build_vocabulary(csv_path: Path, output: Path = VOCABULARY_PATH) -> dict:
    columns = {
        "industries": "MAINOKVED_NAME",
        "regions": "REGION",
        "cities": "CITY",
        "countries": "FTS_COUNTRY_NAME",
    }
    counters = {name: Counter() for name in columns}
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=CSV_DELIMITER):
            for name, column in columns.items():
                counters[name][(row.get(column) or "").strip()] += 1
    vocabulary = {
        "source": csv_path.name,
        "industries": _ranked(counters["industries"]),
        "regions": _ranked(counters["regions"]),
        "cities": _ranked(counters["cities"], 100),
        "countries": _ranked(counters["countries"], MAX_COUNTRY_VALUES),
    }
    output.write_text(json.dumps(vocabulary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    load_vocabulary.cache_clear()
    return vocabulary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ai.summarization.vocabulary")
    parser.add_argument("--csv", required=True)
    args = parser.parse_args(argv)
    vocabulary = build_vocabulary(Path(args.csv))
    print({key: len(value) for key, value in vocabulary.items() if isinstance(value, list)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def flag_state(features: dict, flag: str) -> str:
    value = confirmed_value(features.get(flag))
    text = None if value is None else str(value)
    if text in TRUE_VALUES:
        return "true"
    if text in FALSE_VALUES:
        return "false"
    return "unknown"
