# AI-модуль

Пакет `app.ai` превращает новости, профили компаний и материалы Альфа-Банка в персональную аналитику с проверяемыми источниками. Backend подключает его одной переменной `AI_MODULE=app.ai.bridge` и вызывает через `app.integrations.ai.call_ai`. Все обращения к языковым моделям идут через одну функцию `call_llm` (`providers/gateway.py`), поэтому лимит расходов, учёт токенов и список разрешённых моделей действуют на каждый вызов.

## Подключение

1. Скопируйте `.env.ai.example` в `.env.ai` в корне репозитория (в Compose файл подхватывают `api` и `worker`) и заполните:
   - `AI_MODULE=app.ai.bridge`;
   - `AI_LLM_API_KEY` – ключ команды из инструкции организаторов, значение хранится только на сервере;
   - `AI_GENERATION_VERSION` – число, которое увеличивают при смене модели, промптов или логики, чтобы backend не отдавал устаревшие карточки.
2. Перезапустите `api` и `worker`: `docker compose up -d --build api worker`.
3. Проверьте доступ к шлюзу из каталога `backend` (один реальный вызов и два контролируемых сбоя, ключ в отчёт не попадает):

   ```bash
   python -m app.ai.providers.check
   ```

Без ключа и без `AI_MODULE` backend явно возвращает `ai_unavailable`, заготовки вместо ответов не подставляются.

## Функции для backend

| Функция | Вход | Результат |
| --- | --- | --- |
| `ingest_bank_document(document, path)` | запись документа и путь к PDF | страницы, дата документа и фрагменты текста с номерами страниц |
| `search_bank_analytics(query, as_of, limit, repository)` | запрос, дата события, число результатов (до 5), репозиторий фрагментов | фрагменты банка с документом, страницей, цитатой и признаками `historical`, `date_unknown` |
| `summarize_event(event)` | событие с публикациями | сводка, проверенные факты с цитатами, сущности и темы |
| `derive_user_focus(position_text, interests)` | должность и интересы | `UserFocus`: темы из общего словаря, приоритеты, `unknowns` |
| `build_insight(company_context, user_focus, event, tools)` | профиль, фокус, событие, инструменты | карточка влияния: `facts`, `bank_view`, `ai_interpretation`, `risks`, `opportunities`, `actions`, `unknowns`, `evidence` и трасса |
| `answer_chat(company_context, user_focus, event, history, tools)` | то же и история диалога | ответ с `evidence_refs`, `unknowns`, `trace_id`, `usage` |

Схемы входов и ответов описаны в `docs/contracts/ai.md`, примеры лежат в `docs/contracts/ai-examples.json`. `summarize_event`, `derive_user_focus` и `build_insight` отдаются через кеш результатов, `answer_chat` не кешируется, потому что зависит от истории диалога.

Что делает каждая функция и почему, описано в `docs/ai/`: [OCR](../../../docs/ai/ocr.md), [поиск](../../../docs/ai/rag.md), [суммаризация и фокус](../../../docs/ai/summarization.md), [карточка](../../../docs/ai/insights.md), [агент](../../../docs/ai/agent.md), [чат](../../../docs/ai/chat.md), [проверка оснований](../../../docs/ai/validation.md), [бюджет и кеш](../../../docs/ai/budget-cache.md), [шлюз](../../../docs/ai/providers.md).

## Разрешённые модели

Допустимы только модели приложения 3 кейса, список зашит в `ALLOWED_MODEL_IDS`, вызов другой модели завершается `model_not_allowed` до обращения к сети. Назначение по умолчанию задаёт `DEFAULT_TASK_MODELS` (`providers/settings.py`), лицензии и ссылки приведены в `docs/notices/ai.md`.

| ID модели | Задачи по умолчанию |
| --- | --- |
| `google/gemma-4-26b-a4b-it` | `derive_user_focus`, `select_industries`, `chat_router`, `agent_query` |
| `qwen/qwen3.6-35b-a3b` | `summarize_event`, `build_insight`, `answer_chat`, `agent_plan`, `agent_check` |
| `qwen/qwen3-vl-30b-a3b-instruct` | `ocr_vision` |
| `z-ai/glm-5.3-flash`, `deepseek/deepseek-v4.1-flash`, `moonshotai/kimi-k2.6` | разрешены, но не назначены |

## Переменные окружения

Backend: `AI_MODULE`, `AI_GENERATION_VERSION`. Остальные читает сам модуль, значения по умолчанию подходят для работы.

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `AI_LLM_BASE_URL` | `https://changellenge.up.railway.app/v1` | адрес шлюза моделей |
| `AI_LLM_API_KEY` | пусто | ключ команды |
| `AI_LLM_TIMEOUT_SECONDS` | 60 | таймаут одного обращения |
| `AI_LLM_MAX_RETRIES` | 2 | повторы при временном сбое, не больше 2 |
| `AI_LLM_RETRY_BACKOFF_SECONDS` | 1 | начальная пауза между повторами |
| `AI_LLM_TEMPERATURE` | 0.2 | температура по умолчанию |
| `AI_LLM_REASONING_EFFORT` | `none` | режим рассуждений моделей |
| `AI_LLM_TASK_MODELS` | см. выше | JSON-словарь задача → ID модели |
| `AI_LLM_TARIFFS_PATH` | `providers/tariffs.json` | файл тарифов |
| `AI_LLM_USAGE_LOG_PATH` | пусто | журнал usage, одна строка на вызов |
| `AI_LLM_DAILY_LIMIT_RUB` | из `budget/limits.json` (500) | дневной лимит расходов |
| `AI_LLM_BUDGET_LIMITS_PATH` | `budget/limits.json` | лимиты и параметры оценки стоимости |
| `AI_LLM_BUDGET_LEDGER_PATH` | пусто | журнал расходов, без него учёт в памяти процесса |
| `AI_CACHE_DIR` | пусто | каталог кеша результатов, без него кеш в памяти |
| `AI_CACHE_ENABLED` | `true` | выключатель кеша результатов |
| `AI_OCR_DPI` | 300 | разрешение отрисовки страницы |
| `AI_OCR_MAX_SIDE_PIXELS` | 3600 | предел длинной стороны изображения |
| `AI_OCR_MAX_TOKENS` | 3500 | предел выходных токенов на фрагмент |
| `AI_OCR_PAGE_MAX_TOKENS` | 4500 | предел выходных токенов на страницу целиком |
| `AI_OCR_TILE_HEIGHT_PIXELS` | 1800 | высота фрагмента при запасном разрезании |
| `AI_OCR_REQUEST_TIMEOUT_SECONDS` | 240 | таймаут запроса распознавания |
| `AI_OCR_MIN_PAGE_CHARS` | 3 | минимальная длина текста страницы |
| `AI_OCR_WORKERS` | 3 | число параллельных страниц |
| `AI_OCR_PAGE_ATTEMPTS` | 2 | число попыток на фрагмент |
| `AI_OCR_CACHE_DIR` | `storage/ai-cache/ocr` | каталог кеша OCR |
| `AI_RAG_CHUNK_CHARS` | 1200 | размер фрагмента текста для поиска |
| `AI_RAG_OVERLAP_CHARS` | 200 | перекрытие фрагментов |

## Лимиты

- **Бюджет.** Лимит команды 500 руб. в сутки. Сутки считаются по МСК и начинаются в 3:00, как сброс бюджета шлюза. Перед вызовом резервируется оценка стоимости с учётом `max_tokens`, после вызова уточняется по `usage.cost`. При исчерпании возвращается `budget_exhausted` без обращения к модели. Состояние суток показывает `python -m app.ai.budget status`.
- **Повторы.** Временные сбои шлюза повторяются не больше двух раз, ответ с некорректным JSON не повторяется. Backend дополнительно повторяет задания не больше трёх раз, это нужно учитывать в бюджете.
- **Агент.** Не больше двух дополнительных поисков по материалам банка, поиск возвращает не больше 5 фрагментов.
- **Кеш.** Карточка кешируется по `company_id`, `profile_version`, `event_version`, `focus_hash`, `corpus_version`, версиям промптов и моделей. Для кеша карточки `tools` должен предоставлять `corpus_version()`, иначе карточка строится без кеша.
- **OCR.** Распознавание всех девяти материалов (64 страницы) стоит около 14 руб., результаты страниц кешируются на диске по хешу файла, версии промпта и модели.

## Ошибки

Ошибки поднимаются как `app.integrations.ai.AIError` с полями `code` и `message`, ошибки обращения к модели (`LLMError`) дополнительно содержат `request_id` и `retryable`. Сообщения написаны для пользователя, ключ и тексты запросов в них не попадают.

| Код | Когда возникает | Повтор |
| --- | --- | --- |
| `ai_unavailable` | не задан `AI_MODULE` или ключ, шлюз отклонил ключ | нет |
| `ai_contract_error` | вход не соответствует схеме, шлюз отклонил запрос | нет |
| `budget_exhausted` | исчерпан дневной лимит | нет, до 3:00 МСК |
| `model_not_allowed` | модель задачи не входит в разрешённый список | нет |
| `timeout`, `rate_limited`, `provider_unavailable` | временные сбои шлюза | да |
| `invalid_json` | модель вернула ответ, не разбирающийся по схеме | нет |
| `invalid_ocr` | число страниц PDF не совпало с записью документа | нет |
| `not_found` | файл документа не найден | нет |
| `forbidden` | инструмент запросил данные другой компании | нет |

## Команды

Все команды выполняются из каталога `backend` с интерпретатором, в котором установлен `requirements.lock`. Команды с обращением к моделям требуют `AI_LLM_API_KEY`.

| Задача | Команда |
| --- | --- |
| число страниц PDF | `python -m app.ai.ocr count --dir <каталог_с_PDF>` |
| пробное распознавание страниц | `python -m app.ai.ocr probe --pdf <файл> --pages 1,2` |
| отчёт OCR по каталогу | `python -m app.ai.ocr report --dir <каталог_с_PDF>` |
| загрузка PDF в БД и индексация (нужны `DATABASE_URL` и ключ) | `python -m app.ai.rag reindex --pdf-dir <каталог_с_PDF> --migrate` |
| проверка пяти запросов к индексу | `python -m app.ai.rag check` |
| выгрузка фрагментов в снимок | `python -m app.ai.rag export` |
| проверка оснований на фикстурах | `python -m app.ai.validation check` |
| остаток дневного бюджета | `python -m app.ai.budget status --ledger storage/ai-budget.jsonl` |
| приёмочные сценарии на новых входах | `python -m app.ai.evaluation run` |
| запросы, страницы OCR и повтор поиска без сети | `python -m app.ai.evaluation retrieval`, `ocr`, `search --scenario S7` |
| демонстрационная трасса повторного поиска | `python -m app.ai.evaluation demo` |
| актуальность файлов промптов | `python -m app.ai.promptdocs check` |

Повтор распознавания документа в работающем сервисе – `POST /admin/documents/{id}/reindex`.

## Как проверить OCR, поиск и анализ

1. Запустите сервис с заполненным `.env.ai` (раздел «Подключение»), войдите администратором (`create-admin` описан в корневом `README.md`).
2. **OCR и индекс.** Загрузите PDF из набора `data2` административным запросом `POST /admin/documents`. Задание `ingest_document_job` вызывает `ingest_bank_document`, распознанные страницы берутся из кеша OCR, если файл уже обрабатывался. Статус документа `done` означает, что фрагменты проиндексированы. Для пакетной загрузки используйте `python -m app.ai.rag reindex --pdf-dir <каталог_с_PDF> --migrate`.
3. **Поиск.** Выполните `python -m app.ai.rag check`: команда прогоняет пять запросов из `docs/ai/retrieval-queries.json` и печатает `{"passed": 5, "total": 5}`.
4. **Анализ.** Откройте событие ленты и запросите карточку (`POST` insight) либо задайте вопрос в чате. В ответе у каждого утверждения есть `claim_id` и `evidence_refs`, у банковских источников указаны страница PDF и цитата, а недостающее перечислено в `unknowns`.
5. Без базы данных и сети воспроизведите дополнительный поиск командой `python -m app.ai.evaluation search --scenario S7`: запросы агента выполняются заново по снимку материалов банка и сверяются с записанными.

## Шаблоны промптов

Системные сообщения всех десяти задач лежат в `prompts/` вместе с версией, моделью по умолчанию и описанием входа и ответа. Файлы создаёт команда `python -m app.ai.promptdocs write` из кода, актуальность проверяет тест. В шаблонах нет текстов клиентов, ключей и профилей, входы описаны только структурой.

## Демонстрация агентной логики

`docs/demo/agent-trace.json` – одна короткая трасса: первые поиски не нашли материалов, агент изменил запрос, проверка отклонила утверждение, не относящееся к событию, второй уточнённый поиск нашёл подтверждение со страницами и цитатами банка. Файл собирает `python -m app.ai.evaluation demo` из записи приёмки `docs/quality/acceptance/S7.json`.

## Проверки

```bash
pytest
ruff check app tests
python ../scripts/check_architecture.py
```

Тесты работают с подставным провайдером без сети и ключа. Результаты приёмки на новых входах описаны в `docs/quality/ai-evaluation.md`.
