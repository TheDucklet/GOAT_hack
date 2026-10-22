import math
from dataclasses import dataclass

FORMULAS = {
    "ratio": "result = numerator / denominator",
    "product": "result = factor_a * factor_b",
}


@dataclass(frozen=True)
class ConfirmedInput:
    name: str
    value: float
    lower: float
    upper: float
    unit: str
    period: str
    refs: tuple[str, ...]


def usable(item: ConfirmedInput) -> bool:
    numbers = (item.value, item.lower, item.upper)
    return (
        all(isinstance(number, int | float) and math.isfinite(number) for number in numbers)
        and item.lower <= item.value <= item.upper
        and bool(item.unit.strip())
        and bool(item.period.strip())
        and bool(item.refs)
    )


def apply(formula: str, left: ConfirmedInput, right: ConfirmedInput) -> tuple[float, float] | None:
    if formula == "product":
        corners = [
            left.lower * right.lower,
            left.upper * right.upper,
            left.lower * right.upper,
            left.upper * right.lower,
        ]
        return min(corners), max(corners)
    if formula == "ratio":
        if right.lower <= 0 or left.lower < 0:
            return None
        corners = [left.lower / right.upper, left.upper / right.lower]
        return min(corners), max(corners)
    return None


def build_scenario(
    formula: str, left: ConfirmedInput, right: ConfirmedInput, unit: str, period: str, assumptions: list[str]
) -> dict | None:
    if formula not in FORMULAS or not assumptions or not unit.strip() or not period.strip():
        return None
    if not (usable(left) and usable(right)) or left.name == right.name:
        return None
    bounds = apply(formula, left, right)
    if bounds is None or not all(math.isfinite(bound) for bound in bounds):
        return None
    return {
        "inputs": [
            {
                "name": item.name,
                "value": item.value,
                "unit": item.unit,
                "period": item.period,
                "input_refs": list(item.refs),
            }
            for item in (left, right)
        ],
        "formula": FORMULAS[formula],
        "unit": unit,
        "period": period,
        "assumptions": assumptions,
        "result_range": {"lower": bounds[0], "upper": bounds[1]},
    }
