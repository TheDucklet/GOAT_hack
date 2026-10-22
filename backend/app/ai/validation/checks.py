import re

from app.ai.summarization.grounding import INSTRUCTION_PATTERN, normalize_text, unsupported_numbers
from app.ai.summarization.vocabulary import PRODUCT_FLAGS, TRUE_VALUES
from app.ai.validation.problems import CONTRADICTION, INSUFFICIENT, SUPPORTED, Problem
from app.ai.validation.semantics import CONDITIONAL, semantic_problems, sentences

PRODUCT_WORDS: dict[str, tuple[str, ...]] = {
    "CL_PRODUCT_LOA_MARK": ("кредитн\\w+ продукт", "кредит\\w*"),
    "CL_PRODUCT_LEA_MARK": ("лизинг\\w*",),
    "CL_PRODUCT_DEP_MARK": ("депозит\\w*",),
    "FACTORING_MARK": ("факторинг\\w*",),
    "CL_PRODUCT_GAR_MARK": ("гарант\\w+",),
    "CL_PRODUCT_ZPP_MARK": ("зарплатн\\w+ проект\\w*",),
    "CL_PRODUCT_RKO_MARK": ("расч[её]тно-кассов\\w+ обслуживани\\w+", "РКО"),
}
HAS_PATTERN = "(?:у компании (?:есть|имеется)|компания (?:использует|имеет|пользуется))"
LACKS_PATTERN = (
    "(?:у компании (?:нет|отсутствует)|компания не (?:использует|имеет|пользуется)|у компании отсутствуют)"
)
GAP = "(?:\\W+\\w+){0,3}?\\W+"
SECTION_BANK = "bank_view"
SECTION_INTERPRETATION = "ai_interpretation"


def contains(excerpt: str, text: str) -> bool:
    normalized = normalize_text(excerpt).strip(" .")
    return bool(normalized) and normalized in normalize_text(text)


def check_news(item: dict, catalog) -> list[Problem]:
    known = catalog.news.get(item["id"])
    if known is None:
        return [Problem("unknown_news_source", "новостной источник не относится к событию")]
    problems = []
    for key in ("source_id", "version"):
        if item.get(key) != known[key]:
            problems.append(Problem("news_source_mismatch", f"поле {key} не совпадает с публикацией"))
    if item.get("locator", {}).get("url") != known["url"]:
        problems.append(Problem("news_url_mismatch", "ссылка не совпадает со ссылкой публикации"))
    if not contains(item["excerpt"], known["text"]) and item["excerpt"] != known["excerpt"]:
        problems.append(Problem("excerpt_not_in_publication", "цитаты нет в тексте публикации"))
    return problems


def check_company(item: dict, catalog) -> list[Problem]:
    problems = []
    if item["source_id"] != catalog.company_id:
        problems.append(Problem("foreign_company_source", "источник относится к другой компании"))
    if item["version"] != catalog.profile_version:
        problems.append(Problem("stale_profile_version", "версия профиля не совпадает с текущей"))
    feature = str(item.get("locator", {}).get("feature_path", "")).removeprefix("features.")
    if feature not in catalog.known_features:
        problems.append(
            Problem("missing_profile_parameter", f"в профиле нет значения признака {feature or 'без имени'}")
        )
    elif item["excerpt"] != catalog.company_excerpts.get(feature):
        problems.append(
            Problem("company_excerpt_mismatch", "текст не соответствует значению признака в профиле")
        )
    return problems


def check_bank(item: dict, catalog) -> list[Problem]:
    page = item.get("locator", {}).get("page")
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        return [Problem("invalid_page", "номер страницы должен быть целым числом от 1")]
    same_document = [
        hit
        for hit in catalog.bank_hits
        if hit["document_id"] == item["source_id"] and hit["version"] == item["version"]
    ]
    if not same_document:
        return [
            Problem("bank_document_not_retrieved", "документ или его версия не получены инструментом поиска")
        ]
    on_page = [hit for hit in same_document if hit["page"] == page]
    if not on_page:
        return [Problem("wrong_page", f"на странице {page} нет найденных фрагментов этого документа")]
    if not any(contains(item["excerpt"], hit["text"]) for hit in on_page):
        return [Problem("excerpt_not_on_page", "цитаты нет на указанной странице документа")]
    return []


def check_evidence(item: dict, catalog) -> list[Problem]:
    checks = {"news": check_news, "company": check_company, "bank": check_bank}
    check = checks.get(item.get("kind"))
    if check is None:
        return [Problem("unknown_kind", "неизвестный вид источника")]
    if not str(item.get("excerpt", "")).strip():
        return [Problem("empty_excerpt", "у источника нет подтверждающего фрагмента")]
    return check(item, catalog)


def profile_problems(text: str, catalog) -> list[Problem]:
    problems = []
    for sentence in sentences(text):
        if CONDITIONAL.search(sentence):
            continue
        for flag in PRODUCT_FLAGS:
            state = catalog.flag_states.get(flag) or (
                "true" if catalog.features.get(flag, "") in TRUE_VALUES else "unknown"
            )
            for word in PRODUCT_WORDS.get(flag, ()):
                if state != "true" and re.search(HAS_PATTERN + GAP + word, sentence, re.IGNORECASE):
                    verdict = CONTRADICTION if state == "false" else INSUFFICIENT
                    detail = (
                        f"в профиле нет продукта {flag}, а в утверждении он есть"
                        if state == "false"
                        else f"наличие продукта {flag} в профиле не подтверждено, а в утверждении он есть"
                    )
                    problems.append(Problem("profile_contradiction", detail, verdict))
                    break
                if state == "true" and re.search(LACKS_PATTERN + GAP + word, sentence, re.IGNORECASE):
                    problems.append(
                        Problem(
                            "profile_contradiction",
                            f"в профиле есть продукт {flag}, а в утверждении его нет",
                            CONTRADICTION,
                        )
                    )
                    break
    return list({(item.code, item.detail): item for item in problems}.values())


def check_claim(
    claim: dict, section: str, evidence_by_id: dict[str, dict], catalog, extra_support: str = ""
) -> tuple[str, list[Problem], list[str], dict[str, str]]:
    problems: list[Problem] = []
    statuses: dict[str, str] = {}
    valid_refs: list[str] = []
    refs = list(dict.fromkeys(claim["evidence_refs"]))
    if not refs:
        problems.append(Problem("no_evidence", "у утверждения нет ссылок на источники"))
    for ref in refs:
        item = evidence_by_id.get(ref)
        if item is None:
            problems.append(Problem("unknown_evidence", f"источник {ref} не найден и не превращён в ссылку"))
            statuses[ref] = "unknown"
            continue
        found = check_evidence(item, catalog)
        statuses[ref] = "valid" if not found else "invalid"
        if found:
            problems.extend(found)
        else:
            valid_refs.append(ref)
    kinds = {ref: evidence_by_id[ref]["kind"] for ref in valid_refs}
    if refs and not valid_refs:
        problems.append(Problem("no_valid_evidence", "ни один источник утверждения не прошёл проверку"))
    elif section == SECTION_BANK and (not valid_refs or any(kind != "bank" for kind in kinds.values())):
        problems.append(
            Problem(
                "bank_view_requires_bank_evidence",
                "позиция банка должна опираться только на банковские источники",
            )
        )
    elif section == SECTION_INTERPRETATION and not (
        "company" in kinds.values() and any(kind in {"news", "bank"} for kind in kinds.values())
    ):
        problems.append(
            Problem(
                "missing_premise", "объяснение должно ссылаться на признак компании и на событие или банк"
            )
        )
    support = " ".join(
        [*[evidence_by_id[ref]["excerpt"] for ref in valid_refs], *catalog.event_texts, extra_support]
    )
    missing = unsupported_numbers(claim["text"], support)
    if missing:
        problems.append(
            Problem("number_without_source", "числа без источника: " + ", ".join(sorted(missing)))
        )
    if INSTRUCTION_PATTERN.search(claim["text"]):
        problems.append(Problem("instruction_in_text", "текст утверждения похож на инструкцию, а не на факт"))
    problems.extend(profile_problems(claim["text"], catalog))
    cited = [evidence_by_id[ref] for ref in valid_refs]
    problems.extend(semantic_problems(claim["text"], section, cited, catalog, support))
    if any(problem.verdict == CONTRADICTION for problem in problems):
        verdict = CONTRADICTION
    elif problems:
        verdict = INSUFFICIENT
    else:
        verdict = SUPPORTED
    return verdict, problems, valid_refs, statuses
