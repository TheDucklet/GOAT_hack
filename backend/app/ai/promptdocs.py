import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from app.ai.agent.prompts import (
    AGENT_PROMPT_VERSION,
    PLAN_SYSTEM_PROMPT,
    QUERY_SYSTEM_PROMPT,
    VERIFY_SYSTEM_PROMPT,
)
from app.ai.benchmark.judge import JUDGE_SYSTEM_PROMPT
from app.ai.chat.prompts import ANSWER_SYSTEM_PROMPT, CHAT_PROMPT_VERSION, ROUTER_SYSTEM_PROMPT
from app.ai.gate.prompts import GATE_PROMPT_VERSION, GATE_SYSTEM_PROMPT
from app.ai.impact.prompts import IMPACT_PROMPT_VERSION, IMPACT_SYSTEM_PROMPT
from app.ai.insights.prompts import INSIGHT_PROMPT_VERSION, INSIGHT_SYSTEM_PROMPT
from app.ai.ocr.engine import SYSTEM_PROMPT as OCR_SYSTEM_PROMPT
from app.ai.ocr.settings import OCR_PROMPT_VERSION
from app.ai.personalization.focus import FOCUS_PROMPT_VERSION, FOCUS_SYSTEM_PROMPT
from app.ai.providers.settings import DEFAULT_TASK_MODELS
from app.ai.summarization.industries import SELECTION_SYSTEM_PROMPT
from app.ai.summarization.prompts import (
    FACT_CHECK_PROMPT_VERSION,
    FACT_CHECK_SYSTEM_PROMPT,
    SUMMARY_PROMPT_VERSION,
    SUMMARY_SYSTEM_PROMPT,
)

DEFAULT_DIRECTORY = Path(__file__).with_name("prompts")


@dataclass(frozen=True)
class PromptDoc:
    file: str
    task: str
    version: str
    system: str
    user: str
    output: str


PROMPTS: tuple[PromptDoc, ...] = (
    PromptDoc(
        "summarize_event.md",
        "summarize_event",
        SUMMARY_PROMPT_VERSION,
        SUMMARY_SYSTEM_PROMPT,
        "Текст с заголовком события, датой публикации и пронумерованными публикациями. Каждая публикация "
        "заключена между маркерами `<<<` и `>>>` и подписана меткой `[P1]`, `[P2]` и так далее. Тексты "
        "публикаций обрезаются и очищаются от предложений, похожих на инструкции.",
        "JSON с полями `summary`, `facts` (текст, дословная цитата и метка публикации), `entities` и `topics` "
        "(`theme`, `industry_keywords`, `regions`, `countries`, `products`). Код оставляет только факты "
        "с цитатой из своей публикации и числами из неё.",
    ),
    PromptDoc(
        "select_industries.md",
        "select_industries",
        SUMMARY_PROMPT_VERSION,
        SELECTION_SYSTEM_PROMPT,
        'JSON `{"news": "начало текста новости", "list": "пронумерованный список видов деятельности"}`.',
        'JSON `{"selected": [номера]}`. Номера вне списка отбрасываются.',
    ),
    PromptDoc(
        "derive_user_focus.md",
        "derive_user_focus",
        FOCUS_PROMPT_VERSION,
        FOCUS_SYSTEM_PROMPT,
        'JSON `{"position_text": "должность", "interests": ["интерес"]}` после очистки и обрезки.',
        "JSON с полями `themes` и `priorities`. Темы приводятся к общему словарю, приоритеты очищаются "
        "от запрещённых слов.",
    ),
    PromptDoc(
        "build_insight.md",
        "build_insight",
        INSIGHT_PROMPT_VERSION,
        INSIGHT_SYSTEM_PROMPT,
        "JSON с полями `event` (заголовок, дата, темы), `news` (факты под метками `N1`...), `user_focus`, "
        "`company_features` (признаки профиля под метками `C1`...), `matched_with_event` и `bank_fragments` "
        "(фрагменты банка под метками `B1`... с датой документа). Идентификаторов компании и пользователя "
        "во входе нет.",
        "JSON с полями `bank_view`, `ai_interpretation`, `risks`, `opportunities`, `actions` "
        "(объекты `text` и `evidence_ids` с метками) и `unknowns`. Код заменяет метки идентификаторами "
        "источников и проверяет числа и основания.",
    ),
    PromptDoc(
        "build_impact.md",
        "build_impact",
        IMPACT_PROMPT_VERSION,
        IMPACT_SYSTEM_PROMPT,
        "JSON с полями `event`, `news` (факты под метками `N1`...), `user_focus`, `company_features` "
        "(подтверждённые признаки профиля под метками `C1`...), `profile_gaps` (поля профиля, которых нет "
        "или которые не подтверждены), `matched_with_event`, `bank_fragments` (подтверждённые утверждения "
        "банка под метками `B1`... с датой документа) и `known_missing_parameters`.",
        "JSON с полями `summary`, `mechanism`, `impact_level`, `impact_reason`, `horizon`, `assumptions`, "
        "`relevance_reason`, `unknowns`. Код проверяет ссылки, числа и даты каждого утверждения, определяет "
        "итоговую силу влияния по рубрике и сам задаёт горизонт, срок актуальности, действия и политику "
        "уведомления.",
    ),
    PromptDoc(
        "agent_plan.md",
        "agent_plan",
        AGENT_PROMPT_VERSION,
        PLAN_SYSTEM_PROMPT,
        "JSON с полями `event` (заголовок и темы), `facts`, `company` (до десяти признаков профиля) "
        "и `matched_with_event`.",
        "JSON с полями `needs` (шаги анализа) и `queries` (один-два запроса к материалам банка).",
    ),
    PromptDoc(
        "agent_query.md",
        "agent_query",
        AGENT_PROMPT_VERSION,
        QUERY_SYSTEM_PROMPT,
        "JSON с полями `event`, `facts`, `company_industry`, `previous_queries` (прежние запросы "
        "с числом найденных фрагментов) и `problems` (причины неудачной проверки).",
        "JSON с полями `query` и `reason`. Запрос, совпадающий по словам с прежним, заменяется запасным.",
    ),
    PromptDoc(
        "agent_check.md",
        "agent_check",
        AGENT_PROMPT_VERSION,
        VERIFY_SYSTEM_PROMPT,
        "JSON с полями `event_title`, `event_facts` и `claims` (номер, текст утверждения о позиции банка "
        "и процитированные фрагменты).",
        'JSON `{"verdicts": [{"claim": номер, "verdict": "supported|insufficient|contradiction", '
        '"reason": "..."}]}`.',
    ),
    PromptDoc(
        "chat_router.md",
        "chat_router",
        CHAT_PROMPT_VERSION,
        ROUTER_SYSTEM_PROMPT,
        "JSON с полями `question` (вопрос после защиты от обхода прав), `history` (до шести прежних "
        "сообщений) и `event_title`.",
        "JSON с полями `intent` (`importance`, `missing_data`, `bank_position`, `details`, `other`) "
        "и `search_query`.",
    ),
    PromptDoc(
        "answer_chat.md",
        "answer_chat",
        CHAT_PROMPT_VERSION,
        ANSWER_SYSTEM_PROMPT,
        "JSON с полями `question`, `history`, `event`, `news` (метки `N1`...), `user_focus`, "
        "`company_features` (метки `C1`...), `matched_with_event`, `bank_fragments` (метки `B1`...) "
        "и `known_missing_parameters`.",
        "JSON с полями `answer`, `evidence_ids` (метки) и `unknowns`. Код удаляет метки из текста, "
        "предложения с числами без источника и ответ без действительных оснований.",
    ),
    PromptDoc(
        "benchmark_judge.md",
        "benchmark_judge",
        "judge-1",
        JUDGE_SYSTEM_PROMPT,
        'JSON `{"claims": [...]}`, каждое утверждение содержит `id`, `section`, `statement_type`, `text` и дословные '
        "фрагменты источников `sources`. Идентификаторов компаний и пользователей во входе нет.",
        'JSON `{"verdicts": [{"id": "...", "verdict": "supported|unsupported|contradicted", '
        '"reason": "..."}]}`. Используется только в бенчмарке качества и не влияет на карточки.',
    ),
    PromptDoc(
        "verify_event_facts.md",
        "verify_event_facts",
        FACT_CHECK_PROMPT_VERSION,
        FACT_CHECK_SYSTEM_PROMPT,
        "JSON с полями `rejected_premises` и `claims`: утверждения (факты события и предложения краткого содержания) с `id`, "
        "`section`, `statement_type`, `text` и `sources`, где источник – полный текст публикации.",
        'JSON `{"verdicts": [{"id": "...", "verdict": "supported|unsupported|contradicted", "reason": "..."}]}`. '
        "Утверждение без явного supported не попадает в факты события и краткое содержание.",
    ),
    PromptDoc(
        "gate_verify.md",
        "gate_verify",
        GATE_PROMPT_VERSION,
        GATE_SYSTEM_PROMPT,
        "JSON с полями `rejected_premises` и `claims`: у каждого утверждения `id`, `section`, `statement_type`, `text` и "
        "`sources` с видом источника (`news`, `company`, `bank`), его текстом и для материалов банка названием, датой и "
        "страницей. Идентификаторов компаний и пользователей во входе нет.",
        'JSON `{"verdicts": [{"id": "...", "verdict": "supported|unsupported|contradicted", "reason": "..."}]}`. '
        "Вердикты используются программным допуском к публикации: утверждение без явного supported из карточки убирается.",
    ),
    PromptDoc(
        "ocr_vision.md",
        "ocr_vision",
        OCR_PROMPT_VERSION,
        OCR_SYSTEM_PROMPT,
        "Короткое поручение «Распознай страницу целиком» или «Распознай фрагмент N из M» и изображение "
        "страницы PDF (300 dpi, не больше 3600 пикселей по большей стороне).",
        "JSON с полями `text`, `title` и `date_text`.",
    ),
)


def render(doc: PromptDoc) -> str:
    model = DEFAULT_TASK_MODELS[doc.task]
    return (
        f"# Промпт задачи `{doc.task}`\n\n"
        f"Версия `{doc.version}`, модель по умолчанию `{model}`. Файл создан командой "
        "`python -m app.ai.promptdocs write` из кода и проверяется тестом, поэтому вручную его не правят. "
        "Тексты клиентов и ключи в шаблон не попадают.\n\n"
        "## Системное сообщение\n\n"
        f"```text\n{doc.system}\n```\n\n"
        "## Пользовательское сообщение\n\n"
        f"{doc.user}\n\n"
        "## Ответ модели\n\n"
        f"{doc.output}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ai.promptdocs")
    parser.add_argument("command", choices=["write", "check"])
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    args = parser.parse_args(argv)
    stale = []
    for doc in PROMPTS:
        path = args.directory / doc.file
        text = render(doc)
        if args.command == "write":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
        elif not path.exists() or path.read_text(encoding="utf-8").replace("\r\n", "\n") != text:
            stale.append(doc.file)
    if stale:
        print("Устарели файлы промптов: " + ", ".join(stale), file=sys.stderr)
        return 1
    print(f"промптов: {len(PROMPTS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
