import os
import re

from app.ai.evaluation import checks as c
from app.ai.evaluation.pipeline import Workspace, card_for, focus_of, summarized
from app.ai.providers import LLMError, get_llm_settings
from app.ai.providers.budgeting import shared_ledger
from app.ai.providers.gateway import shared_transport

TUNING_EVENT_IDS = {"event-1", "event-steel", "event-injection", "event-no-text"}
OFFLINE_ENV = {"AI_LLM_API_KEY": "sk-offline-check"}
HAS_CREDIT = re.compile(r"у компании (?:есть|имеется)[^.]{0,40}кредит", re.IGNORECASE)


class Session:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self._events: dict[str, tuple[dict, dict]] = {}
        self._focuses: dict[str, dict] = {}

    def event(self, name: str) -> tuple[dict, dict]:
        if name not in self._events:
            self._events[name] = summarized(self.workspace.raw_event(name))
        return self._events[name]

    def focus(self, name: str) -> dict:
        if name not in self._focuses:
            self._focuses[name] = focus_of(self.workspace.position(name))
        return self._focuses[name]

    def card(self, company_id: str, position: str, event_name: str, label: str, suppressed: int = 0) -> dict:
        event, summary = self.event(event_name)
        company = self.workspace.companies[company_id]
        focus = self.focus(position)
        envelope, searches = card_for(self.workspace, company, focus, event, suppressed)
        return {
            "label": label,
            "company_id": company_id,
            "position": position,
            "event": event_name,
            "focus": focus,
            "summary": summary,
            "envelope": envelope,
            "searches": searches,
            "checks": c.base_checks(envelope, event, company),
        }


def finish(scenario_id: str, title: str, criteria: str, cards: list[dict], extra: list[dict]) -> dict:
    checks = [item for card in cards for item in card["checks"]] + extra
    return {
        "id": scenario_id,
        "title": title,
        "criteria": criteria,
        "cards": cards,
        "extra_checks": extra,
        "verdict": c.verdict_of(checks),
    }


def new_news(session: Session) -> dict:
    card = session.card("U_38174", "chief_accountant", "inflation_weekly", "новая новость")
    event = session.workspace.raw_event("inflation_weekly")
    summary_facts = card["summary"]["facts"]
    extra = [
        c.check("event_not_used_in_tuning", event["id"] not in TUNING_EVENT_IDS, event["id"]),
        c.check("summary_has_checked_facts", len(summary_facts) >= 2, f"фактов: {len(summary_facts)}"),
        c.check(
            "summary_numbers_grounded",
            all(
                not c.unsupported_numbers(fact["text"], event["publications"][0]["text"])
                for fact in summary_facts
            ),
            "числа фактов есть в тексте новости",
        ),
    ]
    return finish(
        "S1",
        "Новая новость, не использовавшаяся при настройке промптов",
        "факты суммаризации подтверждены текстом, карточка имеет ссылки на существующие источники, числа есть в источниках",
        [card],
        extra,
    )


def same_industry(session: Session) -> dict:
    first = session.card("U_38174", "chief_accountant", "inflation_weekly", "с кредитным продуктом")
    second = session.card("U_9085", "chief_accountant", "inflation_weekly", "без кредитного продукта")
    texts_first = [claim["text"] for claim in c.claims_of(first["envelope"]["result"])]
    texts_second = [claim["text"] for claim in c.claims_of(second["envelope"]["result"])]
    extra = [
        c.check(
            "cards_differ_by_profile",
            texts_first != texts_second,
            "тексты карточек двух компаний не совпадают",
        ),
        c.check(
            "no_credit_product_claimed_without_profile",
            not any(HAS_CREDIT.search(text) for text in texts_second),
            "у компании без кредитного продукта нет утверждений о его наличии",
        ),
    ]
    return finish(
        "S2",
        "Две компании одной отрасли",
        "для одной новости и одной должности карточки опираются на профиль каждой компании и не смешивают их",
        [first, second],
        extra,
    )


def new_position(session: Session) -> dict:
    first = session.card("U_38174", "chief_accountant", "inflation_weekly", "главный бухгалтер")
    second = session.card("U_38174", "marketing_director", "inflation_weekly", "директор по маркетингу")
    extra = [
        c.themes_canonical(first["focus"], session.workspace.position("chief_accountant")["interests"]),
        c.themes_canonical(second["focus"], session.workspace.position("marketing_director")["interests"]),
        c.check(
            "focus_differs_by_position",
            set(first["focus"]["topics"]) != set(second["focus"]["topics"]),
            f"{first['focus']['topics']} и {second['focus']['topics']}",
        ),
        c.check(
            "new_position_has_priorities",
            bool(second["focus"]["topics"]) and bool(second["focus"]["priorities"]),
            f"темы: {second['focus']['topics']}",
        ),
    ]
    return finish(
        "S3",
        "Новая должность",
        "должность, которой не было в настройке, даёт непустой фокус из общего словаря тем, отличающийся от прежнего",
        [first, second],
        extra,
    )


def without_bank_view(session: Session) -> dict:
    card = session.card("U_38174", "chief_accountant", "metro_station", "новость вне материалов банка")
    result = card["envelope"]["result"]
    extra = [
        c.check("bank_view_is_null", result["bank_view"] is None, f"bank_view: {result['bank_view']}"),
        c.check(
            "absence_is_explained_in_unknowns",
            any(c.BANK_UNKNOWN_WORDS.search(text) for text in result["unknowns"]),
            f"unknowns: {result['unknowns']}",
        ),
    ]
    card["checks"] = [item for item in card["checks"] if item["name"] != "card_has_facts_and_analysis"]
    card["checks"].append(
        c.check("facts_kept", bool(result["facts"]), f"фактов события: {len(result['facts'])}")
    )
    return finish(
        "S4",
        "Отсутствие bank_view",
        "если материалов банка нет, позиция банка пуста, это объяснено в unknowns, мнение модели не выдаётся за позицию банка",
        [card],
        extra,
    )


def incomplete_profile(session: Session) -> dict:
    card = session.card("U_INCOMPLETE", "chief_accountant", "inflation_weekly", "профиль из двух признаков")
    result = card["envelope"]["result"]
    present = {"MAINOKVED_NAME", "REGION"}
    used = {
        item["locator"]["feature_path"].removeprefix("features.")
        for item in card["envelope"]["evidence"]
        if item["kind"] == "company"
    }
    extra = [
        c.check("only_present_features_cited", used <= present, f"использованные признаки: {sorted(used)}"),
        c.check(
            "missing_data_is_named",
            any(c.MISSING_DATA_WORDS.search(text) for text in result["unknowns"]),
            f"unknowns: {result['unknowns']}",
        ),
    ]
    card["checks"] = [item for item in card["checks"] if item["name"] != "card_has_facts_and_analysis"]
    card["checks"].append(
        c.check("facts_kept", bool(result["facts"]), f"фактов события: {len(result['facts'])}")
    )
    return finish(
        "S5",
        "Неполный профиль",
        "карточка не опирается на отсутствующие признаки, не придумывает выручку и продукты, называет нехватку данных",
        [card],
        extra,
    )


def source_conflict(session: Session) -> dict:
    card = session.card(
        "U_38174", "chief_accountant", "housing_conflict", "две публикации с разными объёмами"
    )
    result = card["envelope"]["result"]
    event = session.workspace.raw_event("housing_conflict")
    first_id, second_id = (item["id"] for item in event["evidence"])
    facts = result["facts"]
    by_source = {
        first_id: [fact["text"] for fact in facts if first_id in fact["evidence_refs"]],
        second_id: [fact["text"] for fact in facts if second_id in fact["evidence_refs"]],
    }
    mixed = [
        fact["claim_id"]
        for fact in facts
        if first_id in fact["evidence_refs"] and second_id in fact["evidence_refs"]
    ]
    texts = [claim["text"] for claim in c.claims_of(result)] + result["unknowns"]
    extra = [
        c.check(
            "both_sources_kept_separately",
            bool(by_source[first_id]) and bool(by_source[second_id]) and not mixed,
            f"факты по источникам: {by_source}, смешанные: {mixed}",
        ),
        c.check(
            "conflict_is_disclosed",
            any(c.CONFLICT_WORDS.search(text) for text in texts),
            "карточка прямо называет расхождение источников",
        ),
    ]
    return finish(
        "S6",
        "Конфликт источников",
        "расходящиеся числа остаются привязанными к своим публикациям и расхождение названо явно",
        [card],
        extra,
    )


def additional_search(session: Session) -> dict:
    card = session.card(
        "U_243", "chief_accountant", "ruble_yuan", "первые два запроса не вернули материалов", suppressed=2
    )
    trace = card["envelope"]["trace"]
    retries = [step for step in trace["steps"] if step.get("purpose") == "retry"]
    result = card["envelope"]["result"]
    extra = [
        c.check(
            "extra_search_executed",
            trace.get("extra_searches", 0) >= 1 and bool(retries),
            f"дополнительных поисков: {trace.get('extra_searches')}",
        ),
        c.check(
            "extra_searches_within_limit",
            trace.get("extra_searches", 0) <= 2,
            f"остановка: {trace.get('stop_reason')}",
        ),
        c.check(
            "extra_search_found_evidence",
            trace.get("stop_reason") == "supported" and bool(result["bank_view"]),
            f"остановка: {trace.get('stop_reason')}, позиция банка: {len(result['bank_view'] or [])} утв.",
        ),
        c.check(
            "searches_are_recorded_for_replay",
            len(card["searches"]) >= 3 and all("chunk_ids" in call for call in card["searches"]),
            f"запросов к материалам банка: {len(card['searches'])}",
        ),
    ]
    return finish(
        "S7",
        "Дополнительный поиск",
        "если первых материалов банка нет, агент меняет запрос, не больше двух раз, находит подтверждение и записывает все запросы",
        [card],
        extra,
    )


def llm_failure(session: Session) -> dict:
    event, _ = session.event("inflation_weekly")
    focus = session.focus("chief_accountant")
    company = session.workspace.companies["U_38174"]
    outcomes = []
    saved = {
        key: os.environ.get(key)
        for key in (
            "AI_LLM_API_KEY",
            "AI_LLM_BASE_URL",
            "AI_LLM_RETRY_BACKOFF_SECONDS",
            "AI_LLM_DAILY_LIMIT_RUB",
        )
    }
    cases = [
        (
            "provider_unavailable",
            {**OFFLINE_ENV, "AI_LLM_BASE_URL": "http://127.0.0.1:9/v1", "AI_LLM_RETRY_BACKOFF_SECONDS": "0"},
            "provider_unavailable",
        ),
        ("budget_exhausted", {**OFFLINE_ENV, "AI_LLM_DAILY_LIMIT_RUB": "0.000001"}, "budget_exhausted"),
    ]
    try:
        for name, env, expected in cases:
            for key in saved:
                os.environ.pop(key, None)
            os.environ.update(env)
            get_llm_settings.cache_clear()
            shared_ledger.cache_clear()
            shared_transport.cache_clear()
            outcome = {"case": name, "expected_code": expected, "returned_card": False, "code": None}
            try:
                envelope, searches = card_for(session.workspace, company, focus, event)
                outcome.update(returned_card=True, searches=len(searches))
            except LLMError as error:
                outcome.update(code=error.code, message=error.message, retryable=error.retryable)
            outcomes.append(outcome)
    finally:
        for key, value in saved.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value
        get_llm_settings.cache_clear()
        shared_ledger.cache_clear()
        shared_transport.cache_clear()
    extra = []
    for outcome in outcomes:
        extra.append(
            c.check(
                f"{outcome['case']}_gives_explicit_error",
                outcome["code"] == outcome["expected_code"] and bool(outcome.get("message")),
                f"код: {outcome['code']}, сообщение: {outcome.get('message')}",
            )
        )
        extra.append(
            c.check(
                f"{outcome['case']}_returns_no_partial_card",
                not outcome["returned_card"],
                "результат не подставлен",
            )
        )
    return {
        "id": "S8",
        "title": "Отказ LLM",
        "criteria": "при недоступности модели и исчерпанном бюджете возвращается явная ошибка без подставленного результата",
        "cards": [],
        "outcomes": outcomes,
        "extra_checks": extra,
        "verdict": c.verdict_of(extra),
    }


SCENARIOS = {
    "S1": new_news,
    "S2": same_industry,
    "S3": new_position,
    "S4": without_bank_view,
    "S5": incomplete_profile,
    "S6": source_conflict,
    "S7": additional_search,
    "S8": llm_failure,
}
