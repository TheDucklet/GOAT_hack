# Backend GOAT

Персональная лента v2 и фиксированная пагинация описаны в ../docs/contracts/feed-v2.md.
Текущий frontend сохраняет прежний FeedOut без параметра contract_version.
Для нового формата передаётся contract_version=v2. До завершения worker возвращается queued.
FEED_CANDIDATE_LIMIT ограничивает shortlist. FEED_PREPARE_TOP_K ограничивает подготовку карточек.
Миграция 0003 добавляет снимки и персональные исключения с сохранением прежних таблиц.

Python 3.12, FastAPI, SQLAlchemy и PostgreSQL 17. Зависимости зафиксированы в
`requirements.lock`; SQLite используется только для быстрых локальных проверок.

[Архитектура и правила расширения](../docs/architecture.md) описывают границы HTTP, доменных сервисов, очереди, worker и AI. Producers используют `app.services.queue`, а обработчики добавляются в `app.services.job_handlers.HANDLERS`. Общие доступы — `services.access`, сессии — `services.sessions`, аудит — `services.audit`; импорты HTTP-роутеров из сервисов запрещены проверкой `python ../scripts/check_architecture.py`.

## Восстановление чата R-06

`GET /chats/{id}` возвращает авторизованный контекст компании/события и последнее задание для восстановления истории и незавершённой обработки. `POST /chats/{id}/messages` совместим со старым `{text}`; необязательный `client_message_id` обеспечивает идемпотентность, `retry:true` повторяет failed последнего неотвеченного вопроса без копирования Message. Проверки владельца, активного членства и доступности события выполняются на сервере. Состояние остаётся в существующих Chat/Message/Job, миграция не требуется. [Точные запросы и ограничения](../docs/contracts/ui-requests.md#контекстный-чат-r-06).

## Материалы R-08

Административные PDF/news/jobs используют существующие API и worker. Успешная индексация возвращает в Job.result `document_id,chunks,source_id`; source_id ведёт к проверенному распознанному фрагменту первой страницы и защищённому оригиналу. Повтор готового SHA не создаёт новый job. GET /admin/jobs добавляет kind и target_id для материальных операций без выдачи полного payload. Одновременные PostgreSQL-постановки с одним активным dedup_key возвращают одну запись; завершённый job освобождает ключ. [Обновление корпуса и работа оператора](../docs/demo/material-operations.md).

## Установка

Из корня репозитория, PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock
Set-Location backend
Copy-Item .env.example .env
```

Если окружение уже создано в этой рабочей папке, первые две команды повторять не требуется.
В Linux/macOS используйте `python3.12 -m venv .venv` и `.venv/bin/python`.
Все следующие команды выполняются **из backend/**; в примерах Windows интерпретатор —
`..\.venv\Scripts\python.exe`.

Создайте отдельную PostgreSQL-БД и её пользователя, задайте `DATABASE_URL` в `.env`.
Существующие базы других проектов не используются.

```powershell
..\.venv\Scripts\python.exe -m app.cli migrate
$env:DEMO_PASSWORD='задайте-свой-длинный-пароль'
..\.venv\Scripts\python.exe -m app.cli seed-demo
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

API-документация: `http://127.0.0.1:8000/docs`; готовность БД: `GET /health`.
В другом терминале из backend/:

```powershell
..\.venv\Scripts\python.exe -m app.worker
```

Scheduler запускается только в worker. Несколько worker используют атомарное получение
задания и PostgreSQL advisory lock для расписания; API самостоятельно сбор не планирует.

## Аккаунты и доступ

`seed-demo` создаёт `user_a@goat.example.org`, `user_b@goat.example.org` и
`admin@goat.example.org` с паролем из DEMO_PASSWORD. Пользователи привязаны к разным
синтетическим компаниям одной отрасли. Повторный seed не меняет существующие пароли.
DEMO_PASSWORD можно хранить в локальном `.env`; он игнорируется Git.

Отдельного первого администратора создавайте так:

```powershell
$env:ADMIN_PASSWORD='задайте-другой-длинный-пароль'
..\.venv\Scripts\python.exe -m app.cli create-admin --email owner@example.org
```

Для существующего пользователя роль меняется административным API с аудитом.
Публичная регистрация принимает только email/password и не даёт доступ к компаниям.

Последовательность для frontend: login → сохранить HttpOnly cookie браузером → `/me` →
передавать csrf_token в заголовке `X-CSRF-Token` всех изменяющих запросов.
Cookie отправляется с `credentials: include`; пароль и сессию не хранить в localStorage.
Для production задайте `ENVIRONMENT=production`, `COOKIE_SECURE=true` и точные CORS_ORIGINS.
Для одного origin удобнее проксировать API через frontend; cross-site cookie отдельно не включена.

## Импорт и новости

Входная папка должна содержать три исходных CSV с разделителем `;`:
`df_Uid_data_hack.csv`, `df_Fid_Uid_link_hack.csv`, `df_Uid_payment_hack.csv`.

```powershell
..\.venv\Scripts\python.exe -m app.cli import-clients --directory D:\Alfa_hak
..\.venv\Scripts\python.exe -m app.cli collect-news
```

Импорт транзакционный. Совпадающая активная версия файлов не импортируется повторно.
Другой набор атомарно заменяет активные платежи/связи, сохраняя отчёты прежних версий.
Возврат к ранее импортированному набору восстанавливает его как активный.
Дублирующиеся пары платежей суммируются в профиле; сами строки не удаляются как «дубли».
PAY_CNT суммируется отдельно от числа строк. Противоречивые поля компании остаются unknown;
связанные через людей компании не помечаются как доказанное владение.

Реальные исходные данные остаются вне Git. Контрольный отчёт:
`../docs/data/import-report.json`. Для независимой сверки всей суммы, PAY_CNT и трёх компаний:

```powershell
$env:PYTHONPATH='.'
..\.venv\Scripts\python.exe scripts/verify_snapshot.py --directory D:\Alfa_hak --report ..\docs\qa\real-snapshot.json
```

Источники заданы в `app/services/news.py`: RSS Банка России и Интерфакса.
Сохраняются оригинальные ссылки, текст публикации или RSS-описания, даты и хеши.
HTTP-переходы на непроверенные адреса не выполняются. При сбое одного источника второй
продолжает обрабатываться. В source сохраняются last_success_at и код последней ошибки.
Сбор автоматически запускается с NEWS_POLL_MINUTES; по умолчанию каждые 20 минут.

## AI и задания

Задайте `AI_MODULE` — Python-модуль Фёдора, реализующий функции из
`../docs/contracts/integration.md`. Ключи LLM остаются конфигурацией его server-side модуля.
`AI_GENERATION_VERSION` увеличивается при смене модели, промптов или логики, чтобы
не использовать устаревшие Insight. Не указывайте `tests.fake_ai` в рабочей конфигурации.

POST insight возвращает готовую карточку (200) или Job (202). При done прочитайте
`GET /insights/{result.insight_id}`. Для чата после done перечитайте историю сообщений.
Порядок истории определяется `sequence`, а не точностью часов.

Ошибки runtime: `ai_unavailable`, `ai_contract_error`, `invalid_evidence`,
`budget_exhausted` (возвращается модулем Фёдора), `processing_failed` и `worker_lost`.
Фёдор должен использовать `app.integrations.ai.AIError` для типизированных ошибок.
Временные `timeout`, `rate_limited`, `provider_unavailable`, `source_fetch_failed`
повторяются с задержкой; всего не более трёх попыток job. Его LLM-adapter должен
учитывать эти повторы при своём бюджете. Дневной AI-бюджет контролирует модуль Фёдора.

Повтор OCR: `POST /admin/documents/{id}/reindex`.
Повтор обработки события: `POST /admin/news/{event_id}/retry`.
Повтор failed insight/chat: повторите исходный пользовательский запрос; старый failed job
сохраняется в истории. Задания потерянного worker не перезапускаются вслепую.
PDF ограничен 50 МБ, проверяется парсером и хранится по SHA256. Каталог не публикуется
статически; чтение идёт через защищённый `/sources/{evidence_id}/file`.

## Проверки

```powershell
..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Для PostgreSQL создайте отдельные базы `goat_test` и `goat_a01_test`.

```powershell
$env:A01_TEST_DATABASE_URL='postgresql+psycopg://goat:пароль@localhost:5432/goat_a01_test'
$env:TEST_DATABASE_URL='postgresql+psycopg://goat:пароль@localhost:5432/goat_test'
..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
..\.venv\Scripts\ruff.exe check app tests migrations scripts
..\.venv\Scripts\python.exe -m alembic check
..\.venv\Scripts\python.exe -m app.cli export-openapi
```

Тесты пересоздают таблицы только в временной SQLite или явно названных `goat_test` и `goat_a01_test`;
реальные исходники и LLM-ключ не нужны. Ошибки привязаны к request_id; в логи не выводятся
пароли, URL подключения БД, сырые prompts и закрытые ответы инструментов.

## Docker-интерфейс для Романа

Контекст сборки — `backend/`, Dockerfile здесь же. API: стандартная команда образа.
Worker: `python -m app.worker`. Миграции: `python -m app.cli migrate` перед запуском
обработчиков. Healthcheck: GET `/health` на порту 8000.

В Compose нужны постоянные тома PostgreSQL и STORAGE_DIR, один и тот же STORAGE_DIR
для api/worker, env DATABASE_URL/AI_MODULE и недоступные клиенту секреты.
Для файлового тома обеспечьте права записи непривилегированному пользователю `goat`.
Общий Compose и frontend Dockerfile находятся в зоне Романа; они здесь не подменяются.

## Конфигурация

| Переменная | Назначение / значение по умолчанию |
| --- | --- |
| DATABASE_URL | SQLAlchemy URL PostgreSQL; адрес, пользователь и пароль вашего окружения |
| ENVIRONMENT | development; production требует Secure cookie |
| COOKIE_SECURE / COOKIE_NAME | false / goat_session |
| SESSION_HOURS | 24, диапазон 1–168 |
| CORS_ORIGINS | JSON-массив точных адресов frontend |
| STORAGE_DIR | storage; постоянный каталог PDF |
| MAX_PDF_BYTES | 52428800 |
| NEWS_POLL_MINUTES | 20, минимум 1 |
| WORKER_POLL_SECONDS | 2 |
| JOB_TIMEOUT_SECONDS | 900; потерянный job отмечается failed после освобождения его блокировки |
| AI_MODULE | app.ai.bridge для живой интеграции через серверный env |
| AI_GENERATION_VERSION | 1; версия генерации для ключа кеша |
| RANKING_WEIGHTS | JSON: industry=4, product=3, geo=2, relation=2, focus=2 |
| ADMIN_PASSWORD / DEMO_PASSWORD | Секреты только для соответствующих CLI-команд |

Лента ранжирует максимум 2000 последних видимых событий; связанные компании в профиле
ограничены 100 записями на тип связи, платежи — top-10 в каждом направлении.
Эти границы предназначены для MVP и должны учитываться при расширении.

Текущая миграция имеет версию 0005. Пустой запуск и обновление заполненной базы проверены. Живой прогон общей сборки с AI находится в docs/qa/a17-live.json относительно корня репозитория.

Эксплуатация после A16, A17 и A18.

Для подключения AI скопируйте .env.ai.example из корня в игнорируемый .env.ai. Задайте AI_MODULE значением app.ai.bridge и поместите выданный ключ только в AI_LLM_API_KEY этого серверного файла. Не передавайте ключ через параметры командной строки. API и worker получают настройки из одного файла. Web и PostgreSQL ключ не получают.

Общий Compose закрепляет AI_CACHE_DIR, AI_LLM_BUDGET_LEDGER_PATH и AI_LLM_USAGE_LOG_PATH внутри постоянного тома documents. Не удаляйте этот том при пересоздании контейнеров. Журнал содержит резервы до отправки запроса и окончательные списания. Незавершённый резерв после аварии сохраняется до смены бюджетных суток. Он намеренно не освобождается автоматически, поскольку удалённый запрос мог быть оплачен. Повреждение журнала требует восстановления из резервной копии и не должно исправляться удалением бюджета.

Стандартный предел составляет 500 рублей на командный ключ в день. Бюджетные сутки начинаются в 03.00 по московскому времени согласно инструкции организаторов. Локальная приёмка выполнялась с дополнительным ограничением 10 рублей. Этот предел уменьшал расходы проверки и не изменял политику шлюза. Журнал текущего хоста не учитывает обращения коллег из других окружений. Резервирование опирается на оценку токенов и тарифов. При расхождении с фактическим биллингом окончательным ограничением остаётся сам шлюз.

На один call_llm допускается максимум три транспортные попытки. На одно задание допускается максимум три запуска. Для одного повторяемого вызова это не более девяти транспортных попыток. В живой проверке использовались две транспортные попытки на вызов и максимум шесть с повторами задания. Это не предел всех вызовов многошагового агента. Его внутренние шаги ограничены отдельно. Перед каждой транспортной попыткой резервируется бюджет. При таймауте расход считается консервативно по резерву, поскольку отсутствие ответа не доказывает бесплатность запроса.

GET /admin/runtime-metrics возвращает возраст очереди, статусы заданий, число повторных запусков и состояние локального бюджета. В JobOut доступны received_at, enqueued_at, started_at, ready_at, attempts и trace_id. Последнее поле обозначает идентификатор задания. AI результат содержит отдельный trace_id, а сохранённая трасса связывает его с job_id. Логи usage содержат идентификатор вызова, задачу, модель, токены, задержку, статус, число попыток и стоимость. Они не содержат ключ, полный prompt или профиль клиента.

Для ограниченной проверки можно задать NEWS_COLLECTION_ENABLED=false, NEWS_MAX_NEW_PUBLICATIONS=1, FEED_CANDIDATE_LIMIT=3 и FEED_PREPARE_TOP_K=1. Отключение расписания не отключает явный административный запуск сбора. Для обычного режима действуют расписание, предел ста новых публикаций за сбор, тридцать кандидатов и три карточки.

NEWS_SOURCES_CONFIG задаёт JSON файл дополнительных источников. В Compose каталог config доступен только для чтения как /srv/config. Значение /srv/config/news-sources.example.json добавляет ещё один официальный канал Банка России. При работе Python напрямую используйте доступный локальный путь. Источник использует существующий адаптер RSS. Добавление новой отрасли производится через данные профиля и темы события. Подробности источников и условий использования находятся в docs/quality/performance-v2.md.

Персональные действия и формулы продуктовых метрик описаны в docs/product/events.md. Срок хранения продуктовых событий задаёт PRODUCT_EVENT_RETENTION_DAYS. По умолчанию это 90 дней. Для дополнительных тестовых аккаунтов используется PRODUCT_TEST_EMAILS. Постоянный тип contact_manager записывает только демонстрационное действие.

Полная сверка исходных данных запускается из backend с PYTHONPATH, указывающим на backend, и DATABASE_URL отдельной базы goat_a18. Команда python ../scripts/verify_data_coverage.py --directory <каталог CSV> --output ../docs/quality/data-coverage-v2.json выполняет импорт и сопоставляет каждую строку. Команда python -m scripts.benchmark_feed --output ../docs/quality/feed-performance-v2.json использует ту же изолированную базу и явно синтетический AI. Эти команды нельзя направлять на пользовательскую базу. Повторный benchmark требует нового состояния снимка, иначе это уже измерение прогретого результата.

Для живой приёмки запустите из корня docker compose -p goat-a17-local -f compose.yaml -f compose.acceptance.yaml up --build -d --wait. Версионированный файл compose.acceptance.yaml задаёт порт 8085, отключённое расписание, одну новость, одну карточку и дополнительный предел 10 рублей. Команда python scripts/verify_ai_runtime.py --project goat-a17-local --pdf <одна разрешённая страница PDF> --output docs/qa/a17-live.json запускается из корня и обращается к http://127.0.0.1:8085/api. Она использует реальные платные вызовы. Прогон требует разрешения на передачу содержимого внешнему шлюзу. Повторно обработанный PDF берётся из сохранённого результата без второго OCR. После готового прогона команда docker compose -p goat-a17-local -f compose.yaml -f compose.acceptance.yaml exec api python -m scripts.verify_runtime_cache проверяет AI кеш в новом процессе.

Ограничения одного файлового хоста, окна 2000 событий, времени, памяти и измеренной нагрузки зафиксированы в docs/quality/performance-v2.md. Эти результаты не являются обещанием неограниченной масштабируемости. Облачный GitHub CI в рамках этой локальной работы не запускался.
