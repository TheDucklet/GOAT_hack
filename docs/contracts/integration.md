# Интеграция backend, frontend и AI

Дополнение A-14: `/companies/{id}/context` возвращает CompanyContext v2 с
`data_semantics_version=company-data-2`. См. [семантику данных](../data/data-semantics.md)
и общие `company-context-v2-examples.json`. Wire-типы генерируются из OpenAPI;
AI input принимает v1/v2. Неподтверждённые признаки имеют value=null, raw/normalized
сохранены отдельно; source-происхождение признака находится в provenance.

Дополнение F-13: [контракт бизнес-влияния v2](insight-v2.md). HTTP принимает v1/v2,
worker сохраняет новые поля и проверяет каталог ссылок v2. С F-14 AI producer
возвращает v2 (`docs/ai/impact.md`). Новые поля UI берёт из generated OpenAPI types,
примеры — из общего `insight-v2-examples.json`, политику — из `notice-policy.json`.

Версия backend: 0.1.0. Это реализованный интерфейс для согласования с Романом и Фёдором;
подключение их модулей ещё не принято совместно. HTTP-контракт генерируется из FastAPI:
`openapi.json`; согласованные примеры — `examples.json`.

## Для Романа

- Базовый URL API задаётся конфигурацией frontend. Cookie передаётся через credentials: include.
- Login возвращает MeOut с csrf_token; `/me` восстанавливает пользователя и членства.
- Заголовок X-CSRF-Token нужен для POST/PATCH/logout после входа. Регистрация создаёт user;
  пользователь затем отдельно входит и запрашивает членство.
- `/companies` возвращает только активные доступные компании. Должность хранится в Membership.
- Feed: `{items,total,limit,offset}`; элемент содержит event_id, title, summary, published_at,
  rank_score, relevance_reasons, status, sources. Пока AI не обработал событие, summary может быть null.
- Insight POST: 200 — InsightOut `{id,company_id,event_id,versions,result}`;
  202 — JobOut `{id,status,result,error}`. Поле ID задания называется id.
- Опрашивать GET `/jobs/{id}`. При done и result.insight_id читать GET `/insights/{id}`.
- Чат: POST `/chats` → id, затем POST `/chats/{id}/messages` → JobOut.
  При done перечитать GET `/chats/{id}/messages`. Порядок — sequence по возрастанию.
- Пока предыдущий вопрос обрабатывается, повторная отправка в тот же чат даёт 409 chat_busy.
- Все ErrorOut: `{code,message,request_id,field_errors}`. Даже неизвестный путь возвращает этот формат.
- `/admin/news/{event_id}` оперирует кластером события, а не ID отдельной публикации.
  Все исходные публикации и ссылки сохраняются. Скрытие исключает событие из новой ленты.
- Upload возвращает `{document,job,source_id}`; при повторной загрузке job может быть null.
  По source_id можно открыть GET `/sources/{id}`, затем locator.url.
- Bank evidence содержит locator.page с нумерацией от 1 и URL защищённого PDF с #page=N.
- Company evidence содержит feature_path, снимок значения/происхождения и текущую версию профиля;
  stale=true означает, что профиль с момента вывода обновился. Снимок не подменяется текущим значением.
- Системный admin управляет материалами, но доступ к аналитике конкретной компании требует членства.

## Для Фёдора

Задайте AI_MODULE, например `app.ai.bridge`. Backend загружает модуль через importlib.
Все функции синхронные и вызываются в отдельном worker-процессе, а не в HTTP-запросе.
Функции возвращают dict либо Pydantic model с model_dump. Ключи/модель/лимит обслуживает
ваш модуль. При изменении модели/промптов увеличьте AI_GENERATION_VERSION.

| Функция | Именованные аргументы | Результат |
| --- | --- | --- |
| derive_user_focus | position_text: str, interests: list[str] | UserFocus: topics, priorities, unknowns, version |
| summarize_event | event: dict | SummaryResult: summary, facts, entities, topics |
| ingest_bank_document | document: dict, path: str | IngestResult: document_date или null, chunks |
| search_bank_analytics | query: str, as_of: ISO date, limit: int, repository: BankRepository | dict с найденными фрагментами; рекомендуемый ключ items |
| build_insight | company_context: dict, user_focus: dict, event: dict, tools: AnalysisTools | AIEnvelope с result=InsightResult |
| answer_chat | company_context: dict, user_focus: dict, event: dict, history: list, tools: AnalysisTools | AIEnvelope с result=ChatResult |

**AIEnvelope**: `{result, evidence: [EvidenceOut], trace: dict}`. Evidence может ссылаться
на уже существующие записи из event.evidence; новые evidence передаются списком.
Каждое существенное утверждение — `{claim_id,text,evidence_refs}`.
InsightResult содержит facts, bank_view (список или null), ai_interpretation, risks,
opportunities, actions, unknowns, evidence_refs и trace_id.
ChatResult: answer, evidence_refs, unknowns, trace_id, usage.

EvidenceOut: `{id,kind,source_id,version,locator,excerpt}`:

- news: source_id — ID публикации из event.publications; version — её content_hash,
  который уже присутствует в event.evidence; locator.url ведёт к первоисточнику.
- bank: source_id — ID BankDocument; version — document.version, locator.page — от 1 до page_count.
- company: source_id — текущая company_id, version — profile_version,
  locator.feature_path — `features.<CSV_COLUMN>`. Backend добавляет снимок значения и происхождения.

Чужой клиентский источник, неизвестный evidence, неверная версия или PDF-страница
отклоняются до публикации. В bank_view требуется банковское evidence.
Семантическую поддержку выводов фрагментами и самопроверку выполняет модуль Фёдора;
backend проверяет структуру, существование и доступность источников.

**topics** — словарь категорий в списки строк:

- industry: точные ОКВЭД или наименования видов деятельности;
- product: имена флагов CL_PRODUCT_* либо FACTORING_MARK;
- geo: точные значения региона, города, страны;
- relation: синтетические ID компаний;
- дополнительные ключи допустимы для сопоставления с UserFocus.topics.

Каждый элемент OCR chunks: `{page:int,text:str,quality:dict?}`. Фрагменты должны покрывать
все страницы; пустая/некорректная страница делает job failed. Backend заменяет старые
chunks только после проверки всего результата; исходный PDF не меняется.
document содержит id, version, page_count, filename. document_date — ISO YYYY-MM-DD либо null.
path — серверный путь, он не передаётся браузеру и не должен появляться в открытых логах.

## Инструменты агента и БД

`tools` — доверенный Python-объект, а не инструкция из новости:

- `tools.get_company_context()` — профиль только разрешённой компании;
  попытка передать company_id другой компании отклоняется;
- `tools.get_event()` — выбранное видимое событие, публикации и существующие evidence;
- `tools.search_bank_analytics(query, as_of, limit=5)` — вызов вашей функции поиска с
  авторизованным BankRepository. limit ограничивается 5, query — 1000 символами.

`repository.search_chunks(query, as_of, limit=5)` выполняет PostgreSQL full-text search
по русскому тексту и фильтру даты. Возвращает chunk_id, document_id, version,
index_version, page, document_date, date_unknown и text. Документы позже as_of исключены;
неизвестная дата остаётся явно неизвестной. Создан GIN-индекс.
Это слой доступа к данным; вашу логику RAG, уточнения запроса и оценки релевантности
можно строить поверх него.

Хранение моделей — app.models, транзакции — app.db. Контекст, публикации, результаты,
evidence и trace записывает backend; AI-функции не выполняют commit/rollback этой транзакции.
Трасса сохраняется по уникальному trace_id; повторное использование чужого ID отклоняется.

## Ошибки и кеш

Для типизированной ошибки поднимайте `AIError(code, message)` из app.integrations.ai.
`budget_exhausted` не повторяется. Временные timeout/rate_limited/provider_unavailable
могут повторяться backend до общего числа 3 попыток job; budget adapter должен это учитывать.
Не передавайте exception-сообщения SDK с ключами в message.

Ключ Insight учитывает пользователя, компанию, profile_version, event.version,
position_text/interests, состав и индекс банковского корпуса, AI_MODULE и
AI_GENERATION_VERSION. UserFocus кешируется по точному вводу должности/интересов.
Версия AI_MODULE/AI_GENERATION_VERSION входит также в ключ кеша UserFocus; при изменении
его алгоритма достаточно увеличить AI_GENERATION_VERSION.

## Границы сдачи

Тестовый AI находится исключительно в backend/tests/fake_ai.py. Он не является
подключённым продуктовым модулем. Подключение реальной разрешённой LLM, OCR 64 страниц,
качество RAG/агента и соблюдение общего AI-бюджета принимаются совместно с Фёдором.
