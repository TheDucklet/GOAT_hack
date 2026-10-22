# Контракт бизнес-влияния v2 — F-13

Версия от 22.10.2026. Канонические wire-модели: `backend/app/schemas.py`.
Контракт опубликован для F-14/A-15/R-05. С F-14 `build_insight` возвращает v2
(генератор описан в `docs/ai/impact.md`), записи v1 остаются читаемым историческим форматом.
Реализация контракта готова к ревью команды; отдельного подтверждения коллег пока нет.

## Версии и общие примеры

`InsightOut.result` принимает **tagless v1** или результат с `schema_version: "v2"`.
Поле `schema_version` находится внутри `result`, а не HTTP/AI-envelope.
У v1 состав и обязательность полей сохранены, старые записи БД не мигрируются.
Явные `v1`, `v3`, повреждённый v2 и неизвестные поля отклоняются; автоматического
понижения v2 до v1 нет. Переход к v2 сохраняет старые шесть секций карточки.

Общие артефакты для всех участников:

| Файл | Назначение |
| --- | --- |
| `examples.json`, `ai-examples.json` | Исходные примеры v1, без изменений |
| `insight.schema.json` | JSON Schema результата v1/v2, генерируется из Python |
| `insight-envelope-v2.schema.json` | JSON Schema AI-envelope v2 |
| `insight-v2-examples.json` | Одни fixtures для Python и frontend, все данные учебные |
| `openapi.json` | HTTP API с `InsightOut.result = InsightResultV2 \| InsightResult` |
| `notice-policy.json` | Экспорт обязательной политики приложения |
| `frontend/src/shared/api/schema.d.ts` | Сгенерированные типы из OpenAPI |

Формат AI-envelope прежний: `{result, evidence, trace}`. В v2 `evidence`
содержит полный каталог ровно всех ссылок результата, включая news/company.
В v1 сохраняется прежнее поведение с источниками, уже сохранёнными backend.
AI проверяет v2 через `InsightEnvelopeV2`; worker через `parse_insight_result`,
затем сохраняет evidence и проверяет их доступность через существующий `check_refs`.

## Владельцы и отображение полей

Все перечисленные поля обязательны, кроме application defaults политики и
`quantitative_scenario`, который присутствует только при количественном сценарии.
Nullable поля передаются как `null`, пустые списки — как `[]`.

| Поле result | Кто задаёт | Проверка backend / AI | Отображение R-05 / A-15 |
| --- | --- | --- | --- |
| `schema_version` | Версия producer в коде | Только `v2`; неизвестная версия — ошибка | Выбор renderer, без предположений по наличию текста |
| `personalized_summary` | AI | `StatementV2` или null; для известной силы обязательно | Краткий персональный вывод; null → «Недостаточно данных» |
| `mechanism` | AI | Список утверждений с evidence; для известной силы непустой | Событие → признак компании → условный механизм → последствия |
| `impact_level`, `impact_reason` | AI предлагает | enum; low/medium/high требуют summary, mechanism и reason с evidence | Сила и обоснование; undetermined → «Не определена», без числового процента |
| `time_horizon` | AI предлагает | `{label, starts_on, ends_on}`, даты ISO или null, упорядочены | Горизонт последствий, отдельно от даты публикации новости |
| `assumptions` | AI | Список StatementV2; тип fact запрещён | Условия применимости вывода |
| `relevance_status` | AI предлагает, backend перепроверяет на выдаче в A-15 | active/review_required/expired/undetermined | Отдельный статус актуальности карточки |
| `valid_from`, `valid_until`, `review_after` | AI предлагает, backend принимает после temporal-проверки | ISO date или null; from ≤ review ≤ until, когда границы известны | Начало/окончание актуальности и срок пересмотра |
| `relevance_reason` | AI | Для определённого статуса обязательно evidence | Почему вывод ещё действует или требует пересмотра |
| `bank_view_context` | AI из метаданных evidence, backend сверяет | missing/current/historical/undated; даты совпадают с процитированными PDF | Историческую позицию подписать датой; undated не показывать как сегодняшнюю |
| `next_actions` | AI выбирает из allowlist | Строгая структура, без произвольных параметров и URL | ask_question → чат, contact_manager_demo → локальная демо-заглушка, hide_insight → скрытие |
| `policy_version`, `disclaimer` | **Приложение** | Constants/defaults из `app/notice_policy.py`, подмена отклоняется | Всегда `InsightNotice`, независимо от текста модели и версии карточки |
| `facts`, `bank_view`, `ai_interpretation`, `risks`, `opportunities`, `actions` | AI | Теперь StatementV2; facts/bank_view только fact; bank_view=null при отсутствии | Факты, позиция банка и выводы ИИ разделены |
| `unknowns`, `evidence_refs`, `trace_id` | AI; backend проверяет источники/доступ | union ссылок всех новых и старых полей, уникальные claim_id; trace непустой | Неизвестное видно пользователю; evidence → drawer, trace → диагностика |

Даты карточки — календарные ISO `YYYY-MM-DD`; проверка наступления даты в A-15
использует календарь Europe/Moscow. `published_at` события остаётся timestamp
исходного события и не копируется в срок актуальности.
`valid_until=null` означает «окончание не установлено», а не «бессрочно подтверждено».
`review_after` — момент обязательной перепроверки, а не автоматическое истечение.
При достижении review backend должен выдать `review_required`, а при истечении
valid_until — `expired` независимо от сохранённого active. Эта runtime-логика — A-15.
Универсального TTL 7 дней нет; пример длительного эффекта остаётся active после
старой даты публикации. Для active требуется valid_from, для expired — valid_until.

## Утверждения, сценарии, ограничения

`StatementV2 = {claim_id, text, evidence_refs, statement_type, quantitative_scenario?}`.
`statement_type`: `fact`, `hypothesis`, `scenario`. Ссылка означает происхождение
входа, а не доказательство гипотезы: UI обязан сохранять этот ярлык. Даже предпосылка
имеет ссылки на данные, из которых она сформулирована; неподтверждённые свойства
компании остаются в `unknowns`. Если нет данных для вывода, summary/reason=null,
mechanism=[], impact_level=undetermined; нельзя заменять неизвестность на low.

Качественная рубрика для F-14: high — подтверждённая существенная экспозиция и
близкий/масштабный триггер; medium — подтверждённый канал с ограниченным масштабом
или более дальним горизонтом; low — доказанно малая/косвенная экспозиция;
undetermined — нельзя обосновать экспозицию или силу. Обоснование описывает факторы
и ограничения. Ни один уровень не кодирует вероятность или денежный прогноз.

Для количественного сценария нужен `statement_type=scenario` и объект
`quantitative_scenario`: непустые `inputs` с name/value/unit/period/input_refs,
`formula`, единица и период результата, `assumptions`, `result_range:{lower,upper}`.
Числа конечные, имена входов уникальные, диапазон упорядочен, input_refs входят
в evidence_refs утверждения. Значения должны извлекаться из подтверждённых
источников, а не из оценки модели. Неизвестные числа не подставляются.
`formula` — декларативное описание для отображения и сверки, **никогда eval/exec**.
F-14 выполняет расчёт кодом из allowlist формул и проверяет диапазон;
произвольная формула должна быть отклонена исполнителем. Полей вероятности нет.
JSON Schema проверяет форму; Python дополнительно проверяет связи полей и ссылок.
Достоверность текстов, чисел в свободном тексте, применимость дат и семантика
источников требуют генератора/верификатора F-14/F-15: структурная проверка их
не заменяет. F-13 не объявляет доказанной истинность любого валидного JSON.

Действия не исполняются на основании ответа LLM. `ask_question` требует question;
для других действий question отсутствует или null; tool/command/url/args и неизвестные поля
запрещены. Переход в чат и скрытие выполняются обычным авторизованным UI/API.
`contact_manager_demo` не отправляет сообщение менеджеру и не создаёт продуктовую заявку.

Позиция банка ссылается только на bank evidence. Каждый такой источник содержит
source_id, version, locator.page (от 1) и для датированной позиции
locator.document_date; metadata dates совпадают с процитированными документами.
Историческая позиция не становится current из-за даты генерации карточки.
Missing bank_view допускает внешний анализ и требует объяснения в unknowns.

## notice_v1 и fallback v1

Обязательный текст:

> Материал подготовлен с использованием ИИ, носит информационный характер и не является индивидуальной инвестиционной рекомендацией. Выводы ИИ не являются официальной позицией банка.

Источником является Python-модуль приложения. Экспортированную JSON-политику
frontend импортирует независимо от результата LLM. Notice уже показан на странице
аналитики; при выносе карточки/чата на отдельный маршрут нужно использовать тот же
компонент. Для v1 тоже показывается notice_v1, хотя сама историческая запись
не получает новых полей. У модели нет переключателя отключения notice.

Для v1 UI показывает старые секции, без персонального summary v2, без придуманных
mechanism и дат. Сила/актуальность — «Не оценена в этой версии»; null bank_view —
«Позиция банка не найдена». Из существующего текста нельзя вычислять low/high
или превращать старое actions в исполняемые команды. `isInsightV2` — общий guard.
Fallback предназначен для валидного v1, а не для маскировки ошибки контракта v2.

## Версии кеша и передача следующим задачам

Общий namespace в `app/insight_versions.py`: contract, schema, semantics, policy.
Он включён и в AI result cache, и в backend Insight cache. Producer schema
с F-14 равен v2 (INSIGHT_SCHEMA_VERSION изменён одновременно с генератором).
Любое несовместимое изменение схемы меняет INSIGHT_CONTRACT_VERSION;
перетолкование данных — DATA_SEMANTICS_VERSION / data_semantics_version входного
контекста, изменение политики — POLICY_VERSION. Версия профиля отдельно сохраняется.
A-14 при переходе на нормализованные данные должен обновить общий semantics namespace
и profile_version. Пока CompanyContext строгий и legacy, расширение его входа — A-14.

AI cache уже включает insight/agent/validation prompt versions и модели;
изменение prompt version автоматически исключает его старые результаты.
Backend cache работает независимо от AI cache и включает AI_MODULE и
AI_GENERATION_VERSION: **при изменении prompt/model/validation надо менять
AI_GENERATION_VERSION на обоих сервисах api и worker**. Автоматическая передача
этих runtime-версий в backend остаётся A-17; её отсутствие не скрыто.
Без corpus_version у tools AI cache обходится; это существующее поведение,
подключение AnalysisTools.corpus_version также остаётся A-17.
Сохранённые старые карточки по id читаются как исторические v1; смена namespace
влияет на повторный запрос генерации, не удаляет историю. Перед выдачей из кеша
A-15 дополнительно проверяет review/expiry, а не полагается только на ключ.

## Проверка и воспроизведение

Из корня репозитория, в окружении с `backend/requirements.lock`:

```powershell
$env:PYTHONPATH = (Resolve-Path backend).Path
python scripts/export_insight_contracts.py
python -m app.cli export-openapi --output docs/contracts/openapi.json
python scripts/export_insight_contracts.py --check
```

Из backend: `python -m pytest tests/test_insight_v2_contract.py tests/test_ai_cache.py tests/test_contract_examples.py tests/test_a01.py -q`.
Из frontend: `npm run contracts:generate`, `npm run contracts:check`, `npm test`, `npm run build`.
Generated artifacts проверяются на drift тестами; CI читает тот же fixture-файл.
Семь fixtures: strong_grounded_impact, unknown_strength, historical_bank_position,
missing_bank_position, incomplete_profile, long_lived_active_insight,
quantitative_scenario_synthetic. Никаких платных LLM-вызовов для проверки F-13 нет.
