import re

from app.ai.summarization.grounding import SENTENCE_END

MIN_QUESTION_CHARS = 4
MAX_QUESTION_CHARS = 1500

BYPASS_PATTERN = re.compile(
    r"игнорир\w*|забудь|не учитывай|отключи\w* (огранич|защит|прав)|"
    r"права доступа|без (проверки )?прав|обойд\w+ (огранич|прав)|"
    r"откро\w+ (мне )?(данные |профиль )?компани\w+|"
    r"(покажи|выведи|дай)\w* .{0,40}(другой|чужой|друг\w+) компани|"
    r"данные (другой|чужой) компани|"
    r"ignore (all|previous|your)|system prompt|"
    r"(покажи|выдай|выведи)\w* .{0,20}(ключ|пароль|токен)|"
    r"(оплат\w+|переве\w+|отправ\w+|удал\w+|измен\w+) .{0,40}(плат[её]ж|счёт|счет|деньги|данные|роль|права)",
    re.IGNORECASE,
)
OTHER_COMPANY_ID = re.compile(r"\bU_\d+\b|\bgroup_\d+\w*\b")


def mentions_other_company(text: str, company_id: str) -> bool:
    return any(found != company_id for found in OTHER_COMPANY_ID.findall(text))


def split_question(text: str, company_id: str) -> tuple[str, list[str]]:
    sentences = [part.strip() for part in SENTENCE_END.split(" ".join(text.split())) if part.strip()]
    clean, removed = [], []
    for sentence in sentences:
        if BYPASS_PATTERN.search(sentence) or mentions_other_company(sentence, company_id):
            removed.append(sentence)
        else:
            clean.append(sentence)
    question = " ".join(clean)[:MAX_QUESTION_CHARS]
    return (question if len(question) >= MIN_QUESTION_CHARS else ""), removed
