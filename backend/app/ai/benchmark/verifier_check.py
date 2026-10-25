import csv
import re
from pathlib import Path

from app.ai.benchmark.runner import write
from app.ai.gate.prompts import GATE_PROMPT_VERSION
from app.ai.gate.verify import verify_checked


def read_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


BLOCK_START = re.compile(r"(?m)^(?=(Публикация:|Материал банка|Признак компании:|Входы:))")
KINDS = (
    ("Публикация:", "news"),
    ("Материал банка", "bank"),
    ("Признак компании:", "company"),
    ("Входы:", "news"),
)


def split_sources(row_id: str, text: str) -> dict[str, dict]:
    blocks = [item.strip() for item in BLOCK_START.split(text) if item and item.strip()]
    blocks = [item for item in blocks if item not in {key for key, _ in KINDS}]
    result = {}
    for number, block in enumerate(blocks, start=1):
        kind = next((name for prefix, name in KINDS if block.startswith(prefix)), "news")
        result[f"src-{row_id}-{number}"] = {"kind": kind, "text": block, "locator": {}}
    return result


def kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    total = len(pairs)
    if not total:
        return None
    observed = sum(1 for left, right in pairs if left == right) / total
    left_yes = sum(1 for left, _ in pairs if left) / total
    right_yes = sum(1 for _, right in pairs if right) / total
    expected = left_yes * right_yes + (1 - left_yes) * (1 - right_yes)
    return None if expected == 1 else round((observed - expected) / (1 - expected), 4)


def check_verifier(sheet: Path, labels: Path, output: Path) -> dict:
    rows = read_rows(sheet)
    human = {row["row_id"]: row for row in read_rows(labels)}
    claims = [
        {
            "claim_id": row["row_id"],
            "section": row["section"],
            "statement_type": row["statement_type"],
            "text": row["claim"],
            "evidence_refs": list(split_sources(row["row_id"], row["sources"])),
        }
        for row in rows
    ]
    sources = {}
    for row in rows:
        sources.update(split_sources(row["row_id"], row["sources"]))
    verdicts, usage = verify_checked(claims, sources)
    details = []
    for row in rows:
        given = verdicts[row["row_id"]]
        details.append(
            {
                "row_id": row["row_id"],
                "section": row["section"],
                "statement_type": row["statement_type"],
                "human": human[row["row_id"]]["verdict"],
                "verifier": given["verdict"],
                "reason": given["reason"],
                "human_comment": human[row["row_id"]]["comment"],
            }
        )
    pairs = [(item["human"] == "supported", item["verifier"] == "supported") for item in details]
    false_supported = [
        item for item in details if item["verifier"] == "supported" and item["human"] != "supported"
    ]
    false_unsupported = [
        item for item in details if item["verifier"] != "supported" and item["human"] == "supported"
    ]
    by_section: dict[str, dict] = {}
    for item in details:
        entry = by_section.setdefault(item["section"], {"rows": 0, "agree": 0})
        entry["rows"] += 1
        entry["agree"] += int((item["human"] == "supported") == (item["verifier"] == "supported"))
    report = {
        "verifier_prompt_version": GATE_PROMPT_VERSION,
        "sheet": sheet.name,
        "labels": labels.name,
        "rows": len(details),
        "agreement": round(sum(1 for left, right in pairs if left == right) / len(pairs), 4),
        "kappa_binary": kappa(pairs),
        "false_supported": len(false_supported),
        "false_unsupported": len(false_unsupported),
        "by_section": by_section,
        "cost_rub": round(sum(item["cost_rub"] for item in usage), 4),
        "false_supported_rows": false_supported,
        "false_unsupported_rows": false_unsupported,
        "details": details,
    }
    write(output, report)
    return report
