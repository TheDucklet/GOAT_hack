import csv
import random
from pathlib import Path

from app.ai.benchmark.report import CRITICAL_SECTIONS, load_pairs
from app.ai.benchmark.runner import read, write

SEED = 20261025
SECTIONS = (
    "facts",
    "bank_view",
    "ai_interpretation",
    "mechanism",
    "personalized_summary",
    "impact_reason",
)
PER_SECTION_TOTAL = 5
PER_SECTION_NOT_GROUNDED = 2
SHEET_COLUMNS = (
    "row_id",
    "section",
    "statement_type",
    "claim",
    "sources",
    "verdict",
    "premises_supported",
    "conclusion_acceptable",
    "marking_correct",
    "comment",
)
SCENARIO_FIXTURES = (
    {
        "claim": "Если ставка по кредиту 14 % годовых и остаток долга 100 млн руб. за 12 месяцев, проценты составят около 14 млн руб. (диапазон 13–15 млн руб. при колебании среднего остатка).",
        "sources": "Входы: ключевая ставка 14,00 % годовых (публикация Банка России от 23.10.2026); остаток долга 100 млн руб. задан условием сценария, период 12 месяцев; формула: проценты = остаток × ставка × срок.",
        "expected": "корректный сценарий: входы названы, единицы и период указаны, формула проверяема, диапазон ограничен",
    },
    {
        "claim": "При снижении ставки до 12,5 % годовых годовая экономия на процентах по условному долгу 100 млн руб. составит около 1,5 млн руб.",
        "sources": "Входы: прогноз средней ключевой ставки на 2027 год 12,5–13,5 % годовых (публикация Банка России от 23.10.2026); текущая ставка 14,00 %; долг 100 млн руб. задан условием сценария; формула: экономия = долг × (14,00 % − 12,5 %).",
        "expected": "корректный сценарий",
    },
    {
        "claim": "Если пошлина вырастет, закупки металла подорожают, и компания потеряет 8 млн руб. выручки.",
        "sources": "Входы: сообщение о введении пошлины на прокат (синтетическая новость). Размер пошлины, объём закупок и выручка компании в источниках не указаны.",
        "expected": "некорректный сценарий: сумма выдумана, входов нет",
    },
    {
        "claim": "С вероятностью 70 % ставка снизится до 13 % к концу года, поэтому расходы на проценты сократятся на 5 млн руб.",
        "sources": "Входы: ключевая ставка 14,00 % годовых; следующее заседание 18.12.2026. Вероятность изменения ставки и размер долга компании в источниках не указаны.",
        "expected": "некорректный сценарий: вероятность и сумма не следуют из источников",
    },
    {
        "claim": "Если доля импорта составляет 30 % закупок, а курс вырастет на 10 %, себестоимость закупок вырастет примерно на 3 %.",
        "sources": "Входы: доля импорта 30 % закупок задана условием сценария, рост курса 10 % задан условием сценария, период не указан; формула: рост себестоимости = доля × рост курса.",
        "expected": "некорректный сценарий: период не указан, входы заданы условием без указания источника",
    },
    {
        "claim": "Если выручка за год составляет 500 млн руб. и маржа снижается на 2 п.п., годовая прибыль уменьшится на 10 млн руб. (диапазон 8–12 млн руб.).",
        "sources": "Входы: выручка 500 млн руб. за год задана условием сценария; снижение маржи на 2 п.п. задано условием сценария; формула: потери = выручка × изменение маржи.",
        "expected": "корректный сценарий: входы заданы явно как предпосылки, единицы и период указаны, формула проверяема",
    },
)


def source_block(item: dict, publications: dict[str, str]) -> str:
    kind, locator = item["kind"], item.get("locator") or {}
    if kind == "news":
        return "Публикация: " + publications.get(item["source_id"], item["excerpt"])
    if kind == "bank":
        title = locator.get("title") or "документ банка"
        return (
            f"Материал банка «{title}», дата {locator.get('document_date') or 'не указана'}, "
            f"страница {locator.get('page')}: {item['excerpt']}"
        )
    return "Признак компании: " + item["excerpt"]


def claim_pool(run_dir: Path, publications: dict[str, str]) -> list[dict]:
    pool = []
    for pair, record in sorted(load_pairs(run_dir).items()):
        if record["status"] != "ok":
            continue
        envelope = record["envelope"]
        evidence = {item["id"]: item for item in envelope["evidence"]}
        result = envelope["result"]
        claims = {
            section: [{**claim} for claim in (result.get(section) or [])]
            for section in ("facts", "bank_view", "ai_interpretation", "mechanism")
        }
        for section in ("personalized_summary", "impact_reason"):
            claims[section] = [result[section]] if result.get(section) else []
        judged = {item["claim_id"]: item for item in read(run_dir / "judge" / f"{pair}.json")["claims"]}
        for section, items in claims.items():
            for claim in items:
                verdict = judged.get(claim["claim_id"])
                if not verdict:
                    continue
                sources = "\n\n".join(
                    source_block(evidence[ref], publications)
                    for ref in claim["evidence_refs"]
                    if ref in evidence
                )
                pool.append(
                    {
                        "pair_id": pair,
                        "section": section,
                        "statement_type": claim["statement_type"],
                        "claim": claim["text"],
                        "sources": sources,
                        "judge_verdict": verdict["verdict"],
                    }
                )
    return pool


def unique_key(item: dict) -> tuple[str, str, str]:
    return item["section"], item["claim"], item["sources"]


def draw(pool: list[dict], taken: set, rng: random.Random) -> list[dict]:
    chosen = []
    for section in SECTIONS:
        picked = []
        for grounded, limit in ((False, PER_SECTION_NOT_GROUNDED), (True, PER_SECTION_TOTAL)):
            candidates = [
                item
                for item in pool
                if item["section"] == section
                and (item["judge_verdict"] == "supported") is grounded
                and (item["section"], item["claim"]) not in taken
            ]
            unique = list({(item["claim"], item["sources"]): item for item in candidates}.values())
            rng.shuffle(unique)
            for item in unique[: limit - len(picked)] if grounded else unique[:limit]:
                taken.add((item["section"], item["claim"]))
                picked.append(item)
        chosen.extend(picked)
    return chosen


def sheet_row(row_id: str, item: dict) -> dict:
    return {
        "row_id": row_id,
        "section": item["section"],
        "statement_type": item["statement_type"],
        "claim": item["claim"],
        "sources": item["sources"],
        "verdict": "",
        "premises_supported": "",
        "conclusion_acceptable": "",
        "marking_correct": "",
        "comment": "",
    }


def write_sheet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def build_sheets(run_dir: Path, output: Path, seed: int = SEED) -> dict:
    publications = {
        publication["id"]: publication["text"]
        for event in read(run_dir / "events.json")
        for publication in event["publications"]
    }
    pool = claim_pool(run_dir, publications)
    critical = [
        item
        for item in pool
        if item["section"] in CRITICAL_SECTIONS and item["judge_verdict"] in {"unsupported", "contradicted"}
    ]
    taken = {(item["section"], item["claim"]) for item in critical}
    rng = random.Random(seed)
    extra = draw(pool, taken, rng)
    control = draw(pool, taken, rng)
    unique_critical = list({unique_key(item): item for item in critical}.values())
    calibration_rows, mapping = [], {}
    for number, item in enumerate(unique_critical, start=1):
        row_id = f"K{number:02d}"
        calibration_rows.append(sheet_row(row_id, item))
        mapping[row_id] = {
            "kind": "critical",
            "pair_ids": sorted({x["pair_id"] for x in critical if unique_key(x) == unique_key(item)}),
        }
    for number, item in enumerate(extra, start=1):
        row_id = f"E{number:02d}"
        calibration_rows.append(sheet_row(row_id, item))
        mapping[row_id] = {"kind": "extra", "pair_ids": [item["pair_id"]], "judge": item["judge_verdict"]}
    for number, item in enumerate(SCENARIO_FIXTURES, start=1):
        row_id = f"S{number:02d}"
        calibration_rows.append(
            sheet_row(
                row_id,
                {
                    "section": "scenario",
                    "statement_type": "scenario",
                    "claim": item["claim"],
                    "sources": item["sources"],
                },
            )
        )
        mapping[row_id] = {"kind": "scenario_fixture", "expected": item["expected"]}
    control_rows = []
    for number, item in enumerate(control, start=1):
        row_id = f"C{number:02d}"
        control_rows.append(sheet_row(row_id, item))
        mapping[row_id] = {"kind": "control", "pair_ids": [item["pair_id"]], "judge": item["judge_verdict"]}
    write_sheet(output / "calibration-sheet.csv", calibration_rows)
    write_sheet(output / "control-sheet.csv", control_rows)
    selection = {
        "run": run_dir.name,
        "seed": seed,
        "method": (
            "критические вхождения (facts и bank_view с вердиктом unsupported или contradicted) сведены к уникальным формулировкам; "
            "добавочная выборка по seed: для каждого из шести разделов 5 утверждений, сначала до двух неподтверждённых судьёй run-1, "
            "остальные подтверждённые, без повторов формулировок; контрольная выборка того же устройства, не пересекающаяся с калибровочной; "
            "шесть сценариев написаны вручную как fixtures"
        ),
        "critical_occurrences": len(critical),
        "critical_unique": len(unique_critical),
        "calibration_rows": len(calibration_rows),
        "control_rows": len(control_rows),
        "rows": mapping,
    }
    write(output / "selection.json", selection)
    return selection
