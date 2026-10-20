# Сторонние компоненты backend

Python 3.12 используется на условиях PSF License. PostgreSQL 17 используется на условиях PostgreSQL License. Версии библиотек зафиксированы в backend/requirements.lock. Лицензии приведены по метаданным дистрибутивов. При распространении следует сохранять их файлы license и copyright notices.

Компонент `alembic` имеет версию `1.20.0`. MIT.

Компонент `annotated-doc` имеет версию `0.0.5`. MIT.

Компонент `annotated-types` имеет версию `0.8.0`. MIT.

Компонент `anyio` имеет версию `4.15.1`. MIT.

Компонент `argon2-cffi` имеет версию `25.1.0`. MIT.

Компонент `argon2-cffi-bindings` имеет версию `26.1.0`. MIT.

Компонент `beautifulsoup4` имеет версию `4.15.0`. MIT License.

Компонент `certifi` имеет версию `2026.10.19`. MPL-2.0.

Компонент `cffi` имеет версию `2.1.1`. MIT-0.

Компонент `click` имеет версию `8.5.0`. BSD-3-Clause.

Компонент `colorama` имеет версию `0.4.6`. Условия приведены в файлах лицензии установленного дистрибутива.

Компонент `dnspython` имеет версию `2.9.0`. ISC.

Компонент `email-validator` имеет версию `2.3.0`. Unlicense.

Компонент `fastapi` имеет версию `0.153.0`. MIT.

Компонент `feedparser` имеет версию `6.0.14`. BSD-2-Clause.

Компонент `feedparser-sgmllib` имеет версию `2.1.0`. PSF-2.0.

Компонент `greenlet` имеет версию `3.5.6`. MIT AND PSF-2.0.

Компонент `h11` имеет версию `0.16.0`. MIT.

Компонент `httpcore` имеет версию `1.0.9`. BSD-3-Clause.

Компонент `httpx` имеет версию `0.28.1`. BSD-3-Clause.

Компонент `idna` имеет версию `3.20`. BSD-3-Clause.

Компонент `iniconfig` имеет версию `2.3.1`. MIT.

Компонент `Mako` имеет версию `1.4.3`. MIT.

Компонент `MarkupSafe` имеет версию `3.0.4`. BSD-3-Clause.

Компонент `opentelemetry-api` имеет версию `1.45.1`. Apache-2.0.

Компонент `packaging` имеет версию `26.3`. Apache-2.0 OR BSD-2-Clause.

Компонент `pluggy` имеет версию `1.7.0`. MIT.

Компонент `psycopg` имеет версию `3.3.6`. LGPL-3.0-only.

Компонент `psycopg-binary` имеет версию `3.3.6`. LGPL-3.0-only.

Компонент `pycparser` имеет версию `3.11`. BSD-3-Clause.

Компонент `pydantic` имеет версию `2.14.1`. MIT.

Компонент `pydantic_core` имеет версию `2.50.1`. MIT.

Компонент `pydantic-settings` имеет версию `2.16.1`. MIT.

Компонент `Pygments` имеет версию `2.21.0`. BSD-2-Clause.

Компонент `pypdf` имеет версию `6.21.1`. BSD-3-Clause.

Компонент `pytest` имеет версию `9.1.1`. MIT.

Компонент `python-dotenv` имеет версию `1.2.4`. BSD-3-Clause.

Компонент `python-multipart` имеет версию `0.0.32`. Apache-2.0.

Компонент `ruff` имеет версию `0.17.1`. MIT.

Компонент `soupsieve` имеет версию `3.0.3`. MIT.

Компонент `SQLAlchemy` имеет версию `2.0.55`. MIT.

Компонент `starlette` имеет версию `1.9.0`. BSD-3-Clause.

Компонент `typing_extensions` имеет версию `4.16.0`. PSF-2.0.

Компонент `typing-inspection` имеет версию `0.4.4`. MIT.

Компонент `tzdata` имеет версию `2026.5`. Apache-2.0.

Компонент `uvicorn` имеет версию `0.54.0`. BSD-3-Clause.

Источниками новостей служат RSS Банка России и Интерфакса. Приложение сохраняет ссылки и происхождение публикаций. Реальные CSV и PDF организаторов остаются вне Git. Тестовые материалы синтетические. Модели и OCR в этот backend не включены. Их перечень передаёт Фёдор.

## Frontend R-01

Версии зафиксированы в frontend/package-lock.json. Сохраняйте LICENSE/NOTICE зависимостей при распространении.

| Компонент | Версия | Лицензия |
| --- | --- | --- |
| Node.js | 24.22.0 | MIT и лицензии встроенных компонентов |
| React / react-dom | 19.3.1 | MIT |
| react-router-dom | 7.18.4 | MIT |
| TypeScript | 5.9.3 | Apache-2.0 |
| Vite | 8.3.4 | MIT |
| @vitejs/plugin-react | 6.1.2 | MIT |
| Vitest | 5.0.5 | MIT |
| jsdom | 30.1.3 | MIT |
| @testing-library/react | 16.3.3 | MIT |
| @testing-library/user-event | 14.6.8 | MIT |
| @testing-library/jest-dom | 7.0.1 | MIT |
| @types/node | 24.12.0 | MIT |
| @types/react | 19.3.0 | MIT |
| @types/react-dom | 19.3.0 | MIT |
| openapi-typescript | 7.13.0 | MIT |
| ajv | 8.17.1 | MIT |
| ajv-formats | 3.0.1 | MIT |
| Playwright Python (необязательные браузерные проверки) | 1.58.0 | Apache-2.0 |

Локальный mock моделирует HTTP API на синтетических JSON-примерах A-01. Его JS-cookie используется только в dev и не заменяет HttpOnly-сессию backend. Моделей LLM или внешних AI-сервисов во frontend нет. Шрифты системные, внешние изображения не используются.

## Инфраструктура R-02

Официальные образы Node.js 24.22.0, Python 3.12.14, PostgreSQL 17.10 и nginx 1.30.2 закреплены digest в Dockerfiles/Compose. Лицензии: nginx — [BSD-2-Clause](https://nginx.org/LICENSE); Docker Compose — [Apache-2.0](https://github.com/docker/compose/blob/main/LICENSE). При распространении сохраняйте лицензионные файлы компонентов и пакетов, входящих в официальные образы. GitHub Actions закреплены commit SHA в workflow. Runtime-сервисы или модели LLM дополнительно не подключены: список переменных/компонентов AI передаёт Фёдор отдельно.
