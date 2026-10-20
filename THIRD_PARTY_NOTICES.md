# Сторонние зависимости A-01

Runtime: Python 3.12 (PSF License), PostgreSQL 17 (PostgreSQL License).
Модели LLM, OCR, новостные интеграции и исходные датасеты в эту ветку не включены.

Версии из requirements.lock; лицензии указаны по метаданным дистрибутивов.
Сохраняйте при распространении полные license/copyright notices из dist-info/licenses.

| Компонент | Версия | Лицензия |
| --- | --- | --- |
| alembic | 1.20.0 | MIT |
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| certifi | 2026.10.19 | MPL-2.0 |
| click | 8.5.0 | BSD-3-Clause |
| colorama | 0.4.6 | См. лицензию в dist-info |
| dnspython | 2.9.0 | ISC |
| email-validator | 2.3.0 | Unlicense |
| fastapi | 0.153.0 | MIT |
| greenlet | 3.5.6 | MIT AND PSF-2.0 |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| iniconfig | 2.3.1 | MIT |
| Mako | 1.4.3 | MIT |
| MarkupSafe | 3.0.4 | BSD-3-Clause |
| opentelemetry-api | 1.45.1 | Apache-2.0 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pluggy | 1.7.0 | MIT |
| psycopg | 3.3.6 | LGPL-3.0-only |
| psycopg-binary | 3.3.6 | LGPL-3.0-only |
| pydantic | 2.14.1 | MIT |
| pydantic_core | 2.50.1 | MIT |
| pydantic-settings | 2.16.1 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| pytest | 9.1.1 | MIT |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| python-multipart | 0.0.32 | Apache-2.0 |
| ruff | 0.17.1 | MIT |
| SQLAlchemy | 2.0.55 | MIT |
| starlette | 1.9.0 | BSD-3-Clause |
| typing_extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | MIT |
| tzdata | 2026.5 | Apache-2.0 |
| uvicorn | 0.54.0 | BSD-3-Clause |

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
