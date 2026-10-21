"""Application-owned notice; export to JSON for consumers, never ask an LLM for it."""

POLICY_VERSION = "notice_v1"
DISCLAIMER = (
    "Материал подготовлен с использованием ИИ, носит информационный характер и не является "
    "индивидуальной инвестиционной рекомендацией. Выводы ИИ не являются официальной позицией банка."
)


def notice_policy() -> dict[str, str]:
    return {"policy_version": POLICY_VERSION, "disclaimer": DISCLAIMER}
