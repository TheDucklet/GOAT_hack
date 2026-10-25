"""Keep source eligibility conditions visible even when a short summary omits them."""

import re

from app.ai.summarization.grounding import SENTENCE_END, strip_instructions

ELIGIBILITY = re.compile(
    r"услови(?:е|ем|ями)\b|условия (?:применения|получения|участия)|при условии|обязательн\w* требован|"
    r"для (?:получения|применения|участия)|право .{0,60}при\b",
    re.IGNORECASE,
)


def condition_sentences(text: str) -> list[str]:
    return list(
        dict.fromkeys(
            " ".join(sentence.split())
            for sentence in SENTENCE_END.split(strip_instructions(text))
            if ELIGIBILITY.search(sentence)
        )
    )


def condition_context(event, aliases: dict[str, str]) -> list[dict]:
    """Exact quotes bound to known news aliases, not company eligibility claims."""
    by_ref = {ref: alias for alias, ref in aliases.items()}
    by_publication = {
        item.source_id: item.id
        for item in event.evidence
        if item.kind == "news" and item.id in by_ref
    }
    return [
        {"evidence_id": by_ref[by_publication[publication.id]], "text": text}
        for publication in event.publications
        if publication.id in by_publication
        for text in condition_sentences(publication.text)
    ]
