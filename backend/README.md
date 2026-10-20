# Backend GOAT

Python 3.12, FastAPI, SQLAlchemy и PostgreSQL 17. Зависимости зафиксированы в
`requirements.lock`; SQLite используется только для быстрых локальных проверок.

[Архитектура и правила расширения](../docs/architecture.md) описывают границы HTTP, доменных сервисов, очереди, worker и AI. Producers используют `app.services.queue`, а обработчики добавляются в `app.services.job_handlers.HANDLERS`. Общие доступы — `services.access`, сессии — `services.sessions`, аудит — `services.audit`; импорты HTTP-роутеров из сервисов запрещены проверкой `python ../scripts/check_architecture.py`.

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
| AI_MODULE | Пусто до подключения Python-модуля Фёдора |
| AI_GENERATION_VERSION | 1; версия генерации для ключа кеша |
| RANKING_WEIGHTS | JSON: industry=4, product=3, geo=2, relation=2, focus=2 |
| ADMIN_PASSWORD / DEMO_PASSWORD | Секреты только для соответствующих CLI-команд |

Лента ранжирует максимум 2000 последних видимых событий; связанные компании в профиле
ограничены 100 записями на тип связи, платежи — top-10 в каждом направлении.
Эти границы предназначены для MVP и должны учитываться при расширении.

Начальная миграция опубликованной ветки имеет версию 0001. Проверка запуска этой ветки записана в ../docs/qa/publication-clean-start.json. Образ Docker и общая сборка пока не проверены.
