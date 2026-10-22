from dataclasses import dataclass, field

RUBRIC_VERSION = "impact-rubric-1"
LEVELS = ("low", "medium", "high", "undetermined")
PRODUCT_PREFIXES = ("CL_PRODUCT_",)
FAMILIES = {
    "industry": ("MAINOKVED_NAME", "MAINOKVED_CODE"),
    "geography": ("REGION", "CITY"),
    "trade": ("FTS_FLAG", "FTS_COUNTRY_NAME"),
    "scale": ("REVENUE_COMPANY", "AMOUNT_WORKERS_FNS_GRADATION", "AMOUNT_WORKERS_SPARK_GRADATION"),
    "group": ("GROUP_ID",),
    "stage": ("ECO_MARK_LABEL", "COMPANY_AGE_YEARS_GRADATION"),
}


def family_of(feature: str) -> str:
    if feature.startswith(PRODUCT_PREFIXES) or feature == "FACTORING_MARK":
        return "product"
    for name, members in FAMILIES.items():
        if feature in members:
            return name
    return "profile"


@dataclass
class Rubric:
    level: str
    proposed: str
    factors: list[str] = field(default_factory=list)
    components: dict = field(default_factory=dict)
    caps: list[str] = field(default_factory=list)


def quantified(context: dict, features: set[str]) -> bool:
    entries = context.get("features", {})
    return any(entries.get(name, {}).get("unit") and entries.get(name, {}).get("period") for name in features)


def assess(
    proposed: str,
    context: dict,
    cited_features: set[str],
    has_event_evidence: bool,
    matches: list[dict],
    has_bank_evidence: bool,
    horizon_dated: bool,
) -> Rubric:
    proposed = proposed if proposed in LEVELS else "undetermined"
    factors = sorted({family_of(name) for name in cited_features})
    matched = {item["feature"] for item in matches} & cited_features
    components = {
        "rubric_version": RUBRIC_VERSION,
        "independent_factors": factors,
        "direct_event_matches": sorted(matched),
        "bank_evidence": has_bank_evidence,
        "dated_horizon": horizon_dated,
        "quantified_exposure": quantified(context, cited_features),
    }
    rubric = Rubric(level=proposed, proposed=proposed, factors=factors, components=components)
    if proposed == "undetermined":
        return rubric
    if not has_event_evidence or not factors:
        rubric.level = "undetermined"
        rubric.caps.append("no_exposure_evidence")
        return rubric
    if proposed == "low" and matched:
        rubric.level = "undetermined"
        rubric.caps.append("low_contradicts_direct_link")
        return rubric
    if proposed == "medium" and not matched:
        rubric.level = "undetermined"
        rubric.caps.append("medium_without_direct_link")
        return rubric
    if proposed == "high":
        if not matched:
            rubric.level = "undetermined"
            rubric.caps.append("high_without_direct_link")
            return rubric
        missing = []
        if len(factors) < 2:
            missing.append("single_factor")
        if not components["quantified_exposure"]:
            missing.append("exposure_not_quantified")
        if not horizon_dated:
            missing.append("trigger_not_dated")
        if missing:
            rubric.level = "medium"
            rubric.caps.extend(missing)
    return rubric
