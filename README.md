# GOAT_hack

Сервис персонализированной новостной аналитики для бизнеса. Frontend: React/TypeScript; backend: FastAPI; отдельный worker и PostgreSQL. AI-модуль Фёдора включён в main и подключается через серверный интерфейс `app.ai.bridge`; его настройки и проверки описаны в `backend/app/ai/README.md`.

Работают регистрация, вход, серверная cookie-сессия и экран «Компании и профиль»: заявка, статусы членств, произвольная должность и интересы. «Бизнес-аналитика» показывает персональную ленту, карточку с основаниями и контекстный чат R-04/R-05/R-06. В R-07 администратор подтверждает/отклоняет заявки и блокирует/разблокирует пользователей через `/admin/memberships` и `/admin/users`; действия требуют подтверждения, блокировка отзывает сессии. Mock не используется в Docker-сборке. [Подготовка demo-доступов](docs/demo/access-management.md), [приёмка R-07](docs/qa/r-07.md).

Ветка `R-00-merge` упорядочивает текущую сборку. [Архитектура и правила расширения](docs/architecture.md): структура `app/features/shared` во frontend, границы backend-сервисов и worker, источники общих компонентов, соответствие будущим задачам и проверки импортов в CI.

[Актуальные задачи после анализа вебинара](TASKS.md): R-05–R-12 пересмотрены; R-13–R-14, A-14–A-18 и F-13–F-17 дополняют выполненные модули. [Обоснование, источники и неоднозначности данных](docs/planning/webinar-review.md), [персональные планы и генерация PDF](docs/planning/README.md). Новая постановка ориентирована на готовые персональные инсайты, корректную семантику данных и проверяемый путь к действию.

## Запуск одной командой

Требуется Docker с Linux containers и Docker Compose **2.24+** (Docker Desktop подходит). Node.js, Python и PostgreSQL на хост устанавливать не нужно. Из корня репозитория:

```powershell
docker compose up --build
```

По умолчанию запускается локальное окружение с синтетическими настройками без LLM-ключей. Для своей конфигурации до запуска скопируйте `.env.example` в `.env` и измените значения:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Приложение: <http://localhost:8080>. Проверка API: <http://localhost:8080/health>. Swagger: <http://localhost:8080/api/docs>. Состояние сервисов: `docker compose ps`.

Compose поднимает ровно четыре сервиса: `web`, `api`, `worker`, `postgres`. PostgreSQL сначала проходит healthcheck; API применяет миграции и запускает HTTP-сервер; затем запускаются worker и web. Планировщик работает только в процессе `python -m app.worker`, в API его нет. Все сервисы имеют healthcheck. PostgreSQL и API не публикуют порты хоста: запросы браузера идут через nginx на том же origin.

## Миграции и тестовые аккаунты

В другом терминале после запуска:

```powershell
docker compose exec api python -m app.cli migrate
docker compose exec api python -m app.cli seed-demo
```

Первая команда повторяет уже автоматически применённые миграции и безопасна для текущей версии. Повторный seed не размножает компании и пользователей и не меняет существующие пароли.

Seed создаёт `user_a@goat.example.org`, `user_b@goat.example.org` и `admin@goat.example.org`. Пароль берётся из `DEMO_PASSWORD`; локальное значение по умолчанию — `Local-demo-password-2026`. Пользователи получают разные синтетические компании. Администратор управляет сервисом, но доступ к аналитике компании также требует членства.

Отдельный администратор:

```powershell
docker compose exec -e ADMIN_PASSWORD api python -m app.cli create-admin --email owner@example.org
```

Перед этой командой задайте `ADMIN_PASSWORD` в окружении текущего терминала. Для существующей учётной записи используйте административный API с аудитом.

## Конфигурация и AI

| Файл / переменная | Назначение |
| --- | --- |
| `.env` | Локальные параметры Compose, БД, cookie, demo seed и worker |
| `WEB_PORT` / `WEB_BIND_HOST` | 8080 / 127.0.0.1; адрес публикации web |
| `PUBLIC_ORIGIN` | Точный адрес приложения для проверки Origin при входе |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Учетные данные и БД внутри сети Compose |
| `DATABASE_URL` | Необязательный полный URL вместо автоматически собранного; пароль со спецсимволами URI нужно percent-encode |
| `ENVIRONMENT`, `COOKIE_SECURE` | development/false для локального HTTP; production требует HTTPS и Secure cookie |
| `DEMO_PASSWORD` | Пароль только для явно запускаемого seed-demo, минимум 10 символов |
| `NEWS_POLL_MINUTES`, `WORKER_POLL_SECONDS`, `JOB_TIMEOUT_SECONDS` | Параметры расписания и обработки заданий |
| `.env.ai` / `AI_ENV_FILE` | Необязательный серверный файл Фёдора; передаётся только API и worker |

Список provider-переменных Фёдора ещё не передан. Это не мешает собрать и проверить R-02. В `.env.ai.example` указаны только подтверждённые backend-переменные `AI_MODULE` и `AI_GENERATION_VERSION`. После передачи скопируйте пример в `.env.ai`, укажите модуль и добавьте подтверждённые имена переменных и ключи. `.env.ai` не обязателен при запуске; frontend и PostgreSQL его не получают. Новые ключи не нужно перечислять в Compose.

```powershell
Copy-Item .env.ai.example .env.ai
# Заполнить .env.ai после передачи AI-модуля и переменных.
docker compose up -d --build api worker
```

Пока `AI_MODULE` пуст, backend явно сообщает о недоступности AI; карточки и ответы не подменяются заготовками. Реальные LLM-ключи не нужны для CI: существующие backend-тесты используют свои тестовые реализации. Env-файлы игнорируются Git и исключены из Docker build contexts; значения ключей не передаются в frontend build.

## Постоянные данные и перезапуск

PostgreSQL хранится в named volume `postgres_data`, документы — в `documents`. Оба имени получают префикс проекта Compose. API и worker используют один каталог `/srv/backend/storage`; новый файловый том наследует права непривилегированного пользователя `goat` из backend-образа. Документы раздаются через защищённый API, не статически из тома.

```powershell
docker compose restart
docker compose down
docker compose up -d --wait
```

Обычный `down` сохраняет named volumes: записи, сессии и документы доступны после повторного создания контейнеров. Журналы: `docker compose logs -f api worker`.

## CI и проверка R-02

`.github/workflows/ci.yml` запускается на push и pull request:

1. Node 24.22.0: установка `npm ci` по package-lock.json, проверка generated types, frontend-тесты и build.
2. Python 3.12.14: установка по requirements.lock, `pip check`, Ruff и существующие backend-тесты на отдельных PostgreSQL-базах `goat_test` и `goat_a01_test`.
3. Сборка и запуск всех четырёх контейнеров без секретов; HTTP-проверка и пересоздание контейнеров с проверкой сохранности данных; открытие login в Chrome headless. Отчёт, журналы и снимок браузера сохраняются как CI artifact.

Версии базовых Docker-образов и GitHub Actions зафиксированы digest/SHA. Backend и frontend используют переданные lock-файлы.

Локальная приёмка в отдельном проекте (скрипт пересоздаёт **указанный** стек, сохраняя тома; основной проект не затрагивается):

```powershell
docker compose -p goat-r02-check up --build -d --wait
python scripts/verify_compose.py --project goat-r02-check --base-url http://127.0.0.1:8080
```

Для скрипта нужен только Python 3.10+ со стандартной библиотекой. Отчёт — `artifacts/r02-compose.json`; его результат также проверяется CI. Если основной проект уже использует порт 8080, задайте отдельный `WEB_PORT` и передайте соответствующий `--base-url`.

- [Результаты приёмки R-02](docs/qa/r-02.md)
- [Результаты приёмки R-03](docs/qa/r-03.md)
- [Архитектурная проверка R-00-merge](docs/qa/r-00.md)
- [Backend и команды эксплуатации](backend/README.md)
- [Frontend без Docker](frontend/README.md)
- [OpenAPI](docs/contracts/openapi.json) и [интеграция с AI](docs/contracts/integration.md)
- [Запросы экранов](docs/contracts/ui-requests.md)
- [Реестр задач](TASKS.md) и [сторонние компоненты](THIRD_PARTY_NOTICES.md)
