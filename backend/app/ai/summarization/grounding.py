import re

NUMBER = re.compile(r"\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)?")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
MIN_QUOTE_CHARS = 15
QUOTE_MARKS = str.maketrans(
    {"«": "", "»": "", "“": "", "”": "", "„": "", '"': "", "‘": "", "’": "", "—": "-", "–": "-"}
)


def normalize_text(text: str) -> str:
    cleaned = text.translate(QUOTE_MARKS).replace("ё", "е").replace("Ё", "Е")
    return re.sub(r"\s+", " ", cleaned).strip().casefold()


def number_tokens(text: str) -> set[str]:
    tokens = set()
    for match in NUMBER.finditer(text):
        token = re.sub(r"[ \u00a0]", "", match.group(0)).replace(",", ".")
        tokens.add(token.rstrip("0").rstrip(".") if "." in token else token)
    return tokens


def unsupported_numbers(claim: str, source: str) -> set[str]:
    return number_tokens(claim) - number_tokens(source)


def quote_in_source(quote: str, source: str) -> bool:
    normalized_quote = normalize_text(quote).strip(" .")
    return len(normalized_quote) >= MIN_QUOTE_CHARS and normalized_quote in normalize_text(source)


def supported_sentences(text: str, source: str) -> str:
    sentences = [part for part in SENTENCE_END.split(text.strip()) if part]
    kept = [sentence for sentence in sentences if not unsupported_numbers(sentence, source)]
    return " ".join(kept)


INSTRUCTION_PATTERN = re.compile(
    r"игнорир|не учитывай|забудь|предыдущ\w+ инструкц|ignore (all|previous|the above)|system prompt|"
    r"ключ доступа|api[- ]?key|пароль|выдай|покажи (ключ|пароль|токен)|отправь .{0,40}(на|по) (e-?mail|почт)",
    re.IGNORECASE,
)


def strip_instructions(text: str) -> str:
    sentences = SENTENCE_END.split(text)
    return " ".join(sentence for sentence in sentences if not INSTRUCTION_PATTERN.search(sentence)).strip()
