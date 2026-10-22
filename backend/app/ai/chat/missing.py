from app.ai.insights.build import LOAN_FLAG, LOAN_THEMES, Prepared
from app.ai.insights.context import flag_state
from app.data_semantics import confirmed_value

TRADE_THEMES = frozenset(
    {
        "импорт и экспорт",
        "торговые пошлины и тарифы",
        "металлургия",
        "сырьевые товары",
        "санкции и ограничения",
    }
)


def flag_is_set(prepared: Prepared, flag: str) -> bool:
    return flag_state(prepared.context, flag) == "true"


def feature_known(prepared: Prepared, feature: str) -> bool:
    return str(confirmed_value(prepared.context["features"].get(feature)) or "").strip() != ""


def missing_parameters(prepared: Prepared) -> list[str]:
    topics = prepared.payload.topics if isinstance(prepared.payload.topics, dict) else {}
    themes = set(topics.get("theme") or [])
    products = set(topics.get("product") or [])
    items: list[str] = []
    if LOAN_FLAG in products or LOAN_THEMES & themes:
        if flag_is_set(prepared, LOAN_FLAG):
            items += [
                "сумма действующей задолженности по кредитам",
                "тип ставки по кредитам (плавающая или фиксированная) и привязка к ключевой ставке",
                "график платежей и сроки погашения кредитов",
            ]
        else:
            items.append("задолженность компании в других банках: сумма, тип ставки и сроки")
        if flag_is_set(prepared, "CL_PRODUCT_LEA_MARK"):
            items.append("условия лизинговых договоров: остаток платежей и привязка к ставке")
        if flag_is_set(prepared, "CL_PRODUCT_DEP_MARK"):
            items.append("объём средств на депозитах и условия ставки по ним")
    if TRADE_THEMES & themes:
        items += [
            "доля закупок и продаж затронутых товаров в обороте компании",
            "условия действующих контрактов: фиксация цен и переходные периоды",
        ]
        if not feature_known(prepared, "FTS_COUNTRY_NAME"):
            items.append("страны и объёмы внешнеторговых операций, в данных об этом сведений нет")
    if not feature_known(prepared, "REVENUE_COMPANY"):
        items.append("годовая выручка компании")
    items.append("суммы и условия, необходимые для расчёта эффекта в рублях")
    return list(dict.fromkeys(items))
