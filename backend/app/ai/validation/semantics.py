import re

from app.ai.rag.temporal import temporal_status
from app.ai.summarization.conflicts import context_stems
from app.ai.summarization.grounding import normalize_text
from app.ai.validation.problems import CONTRADICTION, INSUFFICIENT, Problem

FLAGS_ASSERTING_STATE = ("CL_PRODUCT_LOA_MARK", "CL_PRODUCT_LEA_MARK", "CL_PRODUCT_DEP_MARK")
SENTENCE = re.compile(r"(?<=[.!?])\s+")
CONDITIONAL = re.compile(
    r"\bесли\b|при условии|при наличии|в случае|\bможет\b|\bмогут\b|\bмог бы\b|возможно|вероятно|"
    r"предполож|допуст|гипотет|\bлибо\b",
    re.IGNORECASE,
)
NEGATION = re.compile(
    r"\b(?:нет|отсутствует|отсутствуют|не имеет|не использует|не пользуется)\b", re.IGNORECASE
)
NO_DATA = re.compile(r"(?:данн|сведен|информац|подтвержд|неизвестн)", re.IGNORECASE)
HEDGE = re.compile(
    r"\b(?:вероятно|возможно|может|могут|предположительно|по-видимому|скорее всего|не исключено)\b",
    re.IGNORECASE,
)

DEBT = r"(?:кредит\w*|займ\w*|заём|заёмн\w+|долг\w*|задолженност\w*)"
PRODUCT_PRESUPPOSITIONS: tuple[tuple[str, str], ...] = (
    (r"(?:существующ|текущ|действующ)\w*\s+(?:\w+\s+){0,2}" + DEBT, "CL_PRODUCT_LOA_MARK"),
    (r"(?:обслуживани|погашени)\w+\s+(?:\w+\s+){0,2}" + DEBT, "CL_PRODUCT_LOA_MARK"),
    (r"(?:долгов|кредитн|процентн)\w+\s+(?:нагрузк|портфел|обязательств|расход)\w*", "CL_PRODUCT_LOA_MARK"),
    (r"(?:существующ|текущ|действующ)\w*\s+(?:\w+\s+){0,2}лизинг\w*", "CL_PRODUCT_LEA_MARK"),
    (r"(?:существующ|текущ|действующ)\w*\s+(?:\w+\s+){0,2}депозит\w*", "CL_PRODUCT_DEP_MARK"),
)
ABSENCE_CLAIMS: tuple[tuple[str, str], ...] = (
    (
        r"(?:нет|отсутствует|отсутствуют|не\s+имеет|не\s+использует)\s+(?:\w+\s+){0,3}" + DEBT,
        "CL_PRODUCT_LOA_MARK",
    ),
    (r"(?:нет|отсутствует|не\s+имеет|не\s+использует)\s+(?:\w+\s+){0,3}лизинг\w*", "CL_PRODUCT_LEA_MARK"),
    (r"(?:нет|отсутствует|не\s+имеет|не\s+использует)\s+(?:\w+\s+){0,3}депозит\w*", "CL_PRODUCT_DEP_MARK"),
)
COMPANY = r"(?:компани\w+|клиент\w*|предприяти\w+)"
INTENT = re.compile(
    COMPANY + r"\s+(?:\w+\s+){0,3}(?:планирует|собирается|намерен\w*|намеревается|решил\w*|готовится|"
    r"будет\s+(?:привлекать|брать|размещать|расширять|закупать|инвестировать))",
    re.IGNORECASE,
)
DIRECTION = re.compile(
    COMPANY
    + r"\s+(?:\w+\s+){0,3}(?:импортирует|экспортирует|ввозит|вывозит|занимается\s+(?:импортом|экспортом))|"
    r"(?:является|выступает)\s+(?:\w+\s+){0,2}(?:импортёр|экспортёр|импортер|экспортер|поставщик|покупател|"
    r"владел|собственник)\w*",
    re.IGNORECASE,
)
LOCATION = re.compile(
    r"(?:завод|производств\w+|площадк\w+|филиал\w*|офис\w*|склад\w*)\s+(?:компании\s+)?"
    r"(?:находится|расположен\w*|размещен\w*|размещён\w*)",
    re.IGNORECASE,
)
GROUP = re.compile(
    r"принадлежит|входит\s+в\s+(?:холдинг|структуру)|дочерн\w+|материнск\w+|головн\w+\s+компани\w+|"
    r"холдинг\w*|консолидирован\w+|\bвладеет\b|выручк\w+\s+групп\w+|оборот\w*\s+групп\w+",
    re.IGNORECASE,
)
PAYMENT_MEANING = re.compile(
    r"(?:платеж\w*|платёж\w*|переводы?|контрагент\w*)[^.]{0,80}(?:означа\w+|подтвержда\w+|свидетельству\w+|"
    r"указыва\w+)[^.]{0,60}(?:поставк\w+|кредит\w+|владени\w+|собственност\w+|торговл\w+)",
    re.IGNORECASE,
)
PAYMENT_TURNOVER = re.compile(
    r"\bоборот(?:а|у|ом|е|ы|ов)?\b[^.]{0,60}(?:платеж|платёж)\w*|"
    r"(?:платеж|платёж)\w*[^.]{0,60}\bоборот(?:а|у|ом|е|ы|ов)?\b",
    re.IGNORECASE,
)
REVENUE = re.compile(r"выручк\w+", re.IGNORECASE)
DIGITS = re.compile(r"\d")
PERIOD_CLAIM = re.compile(
    r"(?:выручк|оборот|платеж|платёж)\w*[^.]{0,80}(?<!\d)(20[0-3]\d)(?!\d)", re.IGNORECASE
)
AMOUNT = re.compile(
    r"\d[\d\s.,]*\s*(?:тыс\w*|млн|млрд|трлн)\.?(?!\s*(?:кв|тонн|шт|чел|п\.п|б\.п))", re.IGNORECASE
)
MONEY_CONTEXT = re.compile(
    r"(?:выручк|оборот|платеж|платёж|долг|задолж|прибыл|расход|сумм|капитал|стоимост|убыт|затрат)\w*",
    re.IGNORECASE,
)
CURRENCY = re.compile(r"руб|₽|\brub\b|usd|доллар|евро|юан|\beur\b", re.IGNORECASE)
PERIOD = re.compile(r"год|квартал|месяц|\bмес\b|полугод|недел|(?<!\d)20[0-3]\d(?!\d)", re.IGNORECASE)
BANK_POSITION = re.compile(
    r"(?:альфа-банк\w*|банк)\s+(?:\w+\s+){0,2}(?:ожидает|считает|прогнозирует|оценивает|рекомендует|видит|полагает)|"
    r"по\s+(?:мнению|оценке|прогнозу)\s+(?:альфа-)?банка|позици\w+\s+(?:альфа-)?банка",
    re.IGNORECASE,
)
INTERNAL_ID = re.compile(r"\bU_\d+\b")
CURRENT_STATUSES = {"current"}


def sentences(text: str) -> list[str]:
    return [item.strip() for item in SENTENCE.split(text) if item.strip()]


def state_word(state: str) -> str:
    return "отсутствует" if state == "false" else "не подтверждено"


def product_problems(sentence: str, catalog) -> list[Problem]:
    problems = []
    conditional = bool(CONDITIONAL.search(sentence))
    for pattern, flag in PRODUCT_PRESUPPOSITIONS:
        if not re.search(pattern, sentence, re.IGNORECASE):
            continue
        state = catalog.flag_states.get(flag, "unknown")
        if state == "true" or conditional or (state == "false" and NEGATION.search(sentence)):
            continue
        verdict = CONTRADICTION if state == "false" else INSUFFICIENT
        problems.append(
            Problem(
                "presupposed_product",
                f"утверждение предполагает существующий продукт или долг ({flag}), в профиле это {state_word(state)}",
                verdict,
            )
        )
        break
    for pattern, flag in ABSENCE_CLAIMS:
        match = re.search(pattern, sentence, re.IGNORECASE)
        if not match or NO_DATA.search(match.group(0)) or conditional:
            continue
        if catalog.flag_states.get(flag, "unknown") == "unknown":
            problems.append(
                Problem("absence_unconfirmed", f"отсутствие продукта ({flag}) в профиле не подтверждено")
            )
            break
    return problems


def evidence_status(item: dict, catalog) -> str | None:
    if item["kind"] != "bank":
        return None
    for hit in catalog.bank_hits:
        if (
            hit["document_id"] == item["source_id"]
            and hit["version"] == item["version"]
            and hit["page"] == item.get("locator", {}).get("page")
        ):
            if hit.get("temporal_status"):
                return hit["temporal_status"]
            if catalog.event_day is None:
                return "undated"
            return temporal_status(hit.get("document_date"), hit["text"], catalog.event_day)[0]
    return None


def bank_problems(text: str, section: str, cited: list[dict], catalog) -> list[Problem]:
    bank_items = [item for item in cited if item["kind"] == "bank"]
    statuses = {evidence_status(item, catalog) for item in bank_items} - {None}
    problems = []
    if section == "bank_view" or BANK_POSITION.search(text):
        if statuses - CURRENT_STATUSES:
            problems.append(
                Problem(
                    "stale_bank_position",
                    "материал банка не подтверждён как актуальный на дату события: "
                    + ", ".join(sorted(statuses - CURRENT_STATUSES)),
                )
            )
        elif not bank_items and section != "bank_view" and BANK_POSITION.search(text):
            problems.append(
                Problem(
                    "bank_position_without_bank_source", "позиция банка названа без банковского источника"
                )
            )
    return problems


def hedge_problems(text: str, section: str, cited: list[dict]) -> list[Problem]:
    if section not in {"facts", "bank_view"} or HEDGE.search(text):
        return []
    claim_stems = context_stems(text)
    if not claim_stems:
        return []
    for item in cited:
        for source_sentence in sentences(item["excerpt"]):
            if not HEDGE.search(source_sentence):
                continue
            shared = claim_stems & context_stems(source_sentence)
            if len(shared) >= 3 and len(shared) / len(claim_stems) >= 0.5:
                return [
                    Problem(
                        "hypothesis_presented_as_fact",
                        "источник говорит о возможности, а утверждение подано как факт",
                    )
                ]
    return []


def semantic_problems(text: str, section: str, cited: list[dict], catalog, support: str) -> list[Problem]:
    problems: list[Problem] = []
    normalized_support = normalize_text(support)
    for sentence in sentences(text):
        conditional = bool(CONDITIONAL.search(sentence))
        problems.extend(product_problems(sentence, catalog))
        if INTENT.search(sentence) and not conditional:
            problems.append(
                Problem("invented_company_intent", "планы и намерения компании в данных не названы")
            )
        if DIRECTION.search(sentence) and not conditional:
            problems.append(
                Problem(
                    "trade_direction_unconfirmed",
                    "направление торговли и роль компании в данных не подтверждены",
                )
            )
        if LOCATION.search(sentence):
            problems.append(
                Problem(
                    "location_unconfirmed", "в данных только место регистрации, не расположение производства"
                )
            )
        if GROUP.search(sentence) and not conditional:
            problems.append(
                Problem(
                    "group_ownership_unconfirmed",
                    "код группы не подтверждает владение, консолидацию или оборот группы",
                )
            )
        if PAYMENT_MEANING.search(sentence) and not conditional:
            problems.append(
                Problem("payment_meaning_unconfirmed", "платёж не доказывает поставку, кредит или владение")
            )
        if PAYMENT_TURNOVER.search(sentence) and not conditional:
            problems.append(
                Problem(
                    "payments_as_turnover",
                    "платежи в данных не равны обороту компании, период и валюта не заданы",
                )
            )
        if (
            REVENUE.search(sentence)
            and DIGITS.search(sentence)
            and not catalog.revenue_confirmed
            and not NO_DATA.search(sentence)
        ):
            problems.append(
                Problem("revenue_unconfirmed", "выручка не подтверждена: единица и отчётный период не заданы")
            )
        match = PERIOD_CLAIM.search(sentence)
        if match and match.group(1) not in normalized_support:
            problems.append(Problem("period_unconfirmed", f"год {match.group(1)} в источниках не назван"))
        amount = AMOUNT.search(sentence)
        if (
            amount
            and MONEY_CONTEXT.search(sentence)
            and normalize_text(amount.group(0)) not in normalized_support
            and not (CURRENCY.search(sentence) and PERIOD.search(sentence))
        ):
            problems.append(Problem("amount_without_unit_period", "сумма названа без валюты или периода"))
    if INTERNAL_ID.search(text):
        problems.append(
            Problem("internal_identifier_in_text", "в тексте названы внутренние идентификаторы компаний")
        )
    problems.extend(bank_problems(text, section, cited, catalog))
    problems.extend(hedge_problems(text, section, cited))
    unique = {}
    for problem in problems:
        unique.setdefault((problem.code, problem.detail), problem)
    return list(unique.values())
