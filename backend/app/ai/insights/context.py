import uuid
from dataclasses import dataclass

from app.ai.summarization.vocabulary import PRODUCT_DESCRIPTIONS, TRUE_VALUES
from app.ai.summarization.vocabulary import flag_state as feature_flag_state
from app.data_semantics import confirmed_value

EVIDENCE_NAMESPACE = uuid.UUID("5a1f0c8e-6c2b-4f6e-9a57-2d5f6a7b9c10")
MAX_FEATURE_CHARS = 120

FEATURE_LABELS: dict[str, str] = {
    "MAINOKVED_NAME": "Основной вид деятельности",
    "MAINOKVED_CODE": "Код ОКВЭД",
    "REGION": "Регион регистрации",
    "CITY": "Город регистрации",
    "REVENUE_COMPANY": "Годовая выручка",
    "AMOUNT_WORKERS_FNS_GRADATION": "Численность работников по данным ФНС",
    "COMPANY_AGE_YEARS_GRADATION": "Возраст компании, лет",
    "ECO_MARK_LABEL": "Стадия развития бизнеса",
    "FTS_COUNTRY_NAME": "Страна в записи ФТС; направление торговли неизвестно",
    "NEGATIVEMARK": "Признак ключевого собственника; доля и структура владения неизвестны",
    "OKFS_NAME": "Форма собственности",
    "CL_TYPE": "Тип клиента банка",
}
FLAG_FEATURES: tuple[str, ...] = tuple(PRODUCT_DESCRIPTIONS)
FEATURE_ORDER: tuple[str, ...] = (*FEATURE_LABELS, *FLAG_FEATURES, "GROUP_ID", "FTS_FLAG")
HIDDEN_FEATURES = frozenset({"CL_TYPE"})
MISSING = {"", "nan", "None", "null", "NULL"}


@dataclass(frozen=True)
class CompanyFact:
    evidence_id: str
    feature: str
    value: str
    label: str
    excerpt: str


def evidence_id(*parts: str) -> str:
    return str(uuid.uuid5(EVIDENCE_NAMESPACE, ":".join(parts)))


def readable_money(raw: str) -> str | None:
    try:
        amount = int(round(float(raw)))
    except ValueError:
        return None
    grouped = f"{amount:,}".replace(",", " ")
    if amount >= 1_000_000_000:
        approx = f"{amount / 1_000_000_000:.1f}".replace(".", ",")
        return f"{grouped} руб. (около {approx} млрд руб.)"
    if amount >= 1_000_000:
        approx = f"{amount / 1_000_000:.1f}".replace(".", ",")
        return f"{grouped} руб. (около {approx} млн руб.)"
    return f"{grouped} руб."


def readable_value(feature: str, raw: str) -> str:
    if feature in FLAG_FEATURES:
        meaning = PRODUCT_DESCRIPTIONS.get(feature, feature)
        if raw in TRUE_VALUES:
            return f"да, у компании есть продукт банка «{meaning}»"
        return f"нет, продукта банка «{meaning}» у компании нет"
    if feature == "FTS_FLAG":
        return (
            "есть запись о компании в базе ФТС; импорт/экспорт не установлен"
            if raw in TRUE_VALUES
            else "запись о компании в базе ФТС не отмечена"
        )
    if feature == "REVENUE_COMPANY":
        return readable_money(raw) or raw
    return raw


def flag_state(context: dict, flag: str) -> str:
    return feature_flag_state(context["features"], flag)


def company_facts(context: dict) -> list[CompanyFact]:
    features = context["features"]
    facts = []
    for feature in FEATURE_ORDER:
        if feature in HIDDEN_FEATURES:
            continue
        entry = features.get(feature)
        value = confirmed_value(entry)
        raw = None if value is None else str(value)
        if raw is None or raw in MISSING or (feature == "FTS_COUNTRY_NAME" and not raw.strip()):
            continue
        label = FEATURE_LABELS.get(feature) or ("Банковский продукт" if feature in FLAG_FEATURES else feature)
        if feature == "GROUP_ID":
            label = "Группа компаний"
        if feature == "FTS_FLAG":
            label = "Наличие записи ФТС"
        excerpt = f"{label}: {readable_value(feature, raw)}"[: MAX_FEATURE_CHARS * 2]
        if feature == "REVENUE_COMPANY" and "quality" in entry:
            excerpt = f"{label}: {raw}; единица: {entry.get('unit') or 'неизвестна'}; период: {entry.get('period') or 'неизвестен'}"
        facts.append(
            CompanyFact(
                evidence_id(context["company_id"], context["profile_version"], feature),
                feature,
                raw,
                label,
                excerpt,
            )
        )
    return facts


def matched_features(context: dict, topics: dict | None) -> list[dict]:
    topics = topics or {}
    features = context["features"]
    matches = []

    def value_of(feature: str) -> str | None:
        entry = features.get(feature)
        value = confirmed_value(entry)
        return None if value is None else str(value)

    def folded(items) -> set[str]:
        return {str(item).strip().casefold() for item in items or []}

    industries, geo = folded(topics.get("industry")), folded(topics.get("geo"))
    for feature in ("MAINOKVED_NAME", "MAINOKVED_CODE"):
        if (value := value_of(feature)) and value.strip().casefold() in industries:
            matches.append({"factor": "industry", "feature": feature, "value": value})
            break
    for feature in ("REGION", "CITY", "FTS_COUNTRY_NAME"):
        if (value := value_of(feature)) and value.strip().casefold() in geo:
            matches.append({"factor": "geo", "feature": feature, "value": value})
    for flag in topics.get("product") or []:
        if value_of(flag) in TRUE_VALUES:
            matches.append({"factor": "product", "feature": flag, "value": "1"})
    return matches
