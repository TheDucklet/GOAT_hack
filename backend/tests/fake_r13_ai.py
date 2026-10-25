"""Explicit synthetic acceptance producer, never enabled in production."""

from app.integrations.ai import AIError
from tests.fake_feed_ai import build_insight as base_insight
from tests.fake_feed_ai import derive_user_focus as derive_user_focus


def build_insight(company_context, user_focus, event, tools):
    if event["id"] == "r13-deferred":
        raise AIError("budget_exhausted", "Synthetic acceptance budget failure")
    envelope = base_insight(company_context, user_focus, event, tools)
    result = envelope["result"]
    funded = company_context["company_id"] == "demo_company_a"
    summary = (
        "Учебный кредит с плавающей ставкой требует пересмотра плана платежей."
        if funded
        else "Недостаточно данных для оценки процентного влияния на компанию."
    )
    mechanism = (
        "В учебном профиле подтверждён плавающий кредит; учебное изменение ставки влияет на будущие платежи при пересмотре."
        if funded
        else "Наличие РКО не подтверждает кредитную экспозицию; нужно уточнить договоры и сроки пересмотра."
    )
    for section in ("personalized_summary", "impact_reason", "relevance_reason"):
        result[section]["text"] = summary
    result["mechanism"][0]["text"] = mechanism
    result["facts"][0]["text"] = (
        "В учебном событии ставка для пересматриваемого договора повышается на один процентный пункт."
    )
    result["time_horizon"]["label"] = "До ближайшего пересмотра учебного договора"
    result["impact_level"] = "medium" if funded else "undetermined"
    result["unknowns"] = (
        ["Уточнить дату следующего пересмотра"] if funded else ["Неизвестны кредитные договоры и остатки"]
    )
    company_evidence = envelope["evidence"][1]
    field = "confirmed_debt_terms" if funded else "CL_PRODUCT_RKO_MARK"
    company_evidence["locator"] = {"feature_path": "features." + field}
    company_evidence["excerpt"] = str(company_context["features"][field]["value"])
    return envelope
