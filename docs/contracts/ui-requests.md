# R-01 · HTTP-запросы интерфейса

Основания: TASKS.md (R-01/A-01), 00-system-overview.pdf, 01-roman-tasks.pdf и опубликованный HTTP-контракт Алексея. Дата: 20.10.2026.

## Входной контракт

A-01 получена из `a-01/alexey/api-contract`, коммит `7f86298b52ea88fe49c9abe0ab1c6c0ce81c81d7`. R-01 основана на этой ветке. Источник истины — [openapi.json](openapi.json); примеры — [examples.json](examples.json) из того же коммита. Исходные backend-файлы и JSON не изменены.

`frontend/src/api/schema.d.ts` генерируется из OpenAPI (`npm run contracts:generate`), `types.ts` содержит только алиасы этих схем. `npm run contracts:check` выявляет рассогласование с OpenAPI. Mock импортирует оригинальный examples.json напрямую и использует примеры me, successful_user, membership, feed, chat, pending_job, stats, error и insufficient_data. Для CompanyOut и внешнего InsightOut отдельных примеров нет: только эти обёртки составлены дополнительно и тоже валидируются по OpenAPI. Административная mock-сессия отличается от примера MeOut только email и system_role.

Существенные детали контракта: `/me` и login возвращают **плоский MeOut**, без обёртки user; ErrorOut.field_errors — **массив `{loc,message,type}`**, как в backend/app/errors.py; FeedItem.relevance_reasons и sources — массивы объектов; отправка сообщения — `{text}`; JobOut содержит **id**, не job_id. Регистрация принимает пароль 10–256 символов, вход — 1–256. Должность — произвольная строка.

A-01 пока возвращает 501 contract-only для бизнес-операций. Настоящие auth/доступы реализуются в A-02/A-03. Для приёмки R-01 допустим локальный mock на опубликованных примерах; HTTP-режим никогда не заменяет 501 или сбой backend тестовым успехом.

## Реализованные экраны

| Экран / действие | Запрос | Читаемые поля / результат |
| --- | --- | --- |
| Запуск, восстановление сессии | `GET /me` | `id,email,system_role,status`; `memberships[].id,user_id,company_id,status,position_text,interests`; `csrf_token` |
| `/login`, отправка формы | `POST /auth/login` `{email,password}` | MeOut; CSRF в памяти; возврат к защищённому URL или `/app` |
| `/register`, отправка формы | `POST /auth/register` `{email,password}` | UserOut, 201 → `/login`; системная роль не отправляется |
| Header защищённых страниц | `GET /companies` | Массив доступных `id,name,profile_version`; выбранная компания задаётся общим контекстом |
| Header, выход | `POST /auth/logout` | 204; очистка CSRF/состояния, переход на `/login` |
| `/app` | Общие `/me` и `/companies` | Название компании; постоянная ссылка «Бизнес-аналитика» |
| `/app/analytics` | Общие `/me` и `/companies` | Подготовленный маршрут; лента/карточка/чат подключаются в R-04–R-06 |
| `/admin` | `GET /admin/stats` | `positive_feedback,negative_feedback,failed_jobs`; число оценок — сумма первых двух; 403 → «Нет доступа» |

В UserOut нет отдельного поля имени: header показывает локальную часть email до `@` и email. `position_text` не используется как разрешение. Административная ссылка зависит только от system_role; прямой `/admin` всегда проверяется запросом к серверу. Список компаний приходит только из `/companies`; клиент не расширяет его по pending-членствам. При отсутствии доступных компаний показывается сообщение об ожидаемом подтверждении членства.

## Методы единого клиента для следующих задач

Эти методы типизированы и доступны из того же экземпляра; экраны R-01 их ещё не вызывают.

| Задача | Метод / endpoint | Поля |
| --- | --- | --- |
| R-04 | `feed` → `GET /companies/{id}/feed?limit=&offset=` | `items[].event_id,title,summary,published_at,rank_score,relevance_reasons,status,sources`; `total,limit,offset` |
| R-05 | `buildInsight` → `POST /companies/{id}/insights` `{event_id}` | 200: `id,company_id,event_id,versions,result`; 202: JobOut |
| R-05 | `insight` → `GET /insights/{id}` | `result.facts,bank_view,ai_interpretation,risks,opportunities,actions,unknowns,evidence_refs,trace_id`; Claim: `claim_id,text,evidence_refs` |
| R-06 | `createChat` → `POST /chats` `{company_id,event_id}` | `id,company_id,event_id` |
| R-06 | `sendMessage` → `POST /chats/{id}/messages` `{text}` | JobOut; 202 |
| R-06 | `messages` → `GET /chats/{id}/messages` | Массив `id,chat_id,sequence,role,text,result,created_at` |
| R-05/R-06 | `job` → `GET /jobs/{id}` | `id,status,result,error`; queued/running/done/failed; при result.insight_id потребитель читает карточку |

FeedItem.summary и published_at могут быть null. Bank_view — массив Claim либо null; отсутствие банковского материала не подменяется AI-мнением. Evidence содержит id/kind/source_id/version/locator/excerpt. Детальные схемы, включая произвольные locator и result.error, берутся из generated types.

## Транспорт и ошибки

`VITE_API_BASE_URL` задаёт адрес; HTTP — режим по умолчанию. Локальный mock включается только `VITE_API_MODE=mock` в dev. Сборка с mock запрещена, включая пользовательские build modes. Все экраны используют один `ApiClient` с настоящим fetch или mock transport. Автоматического перехода на mock нет.

Все запросы передают `credentials: include`. `/me` и login обновляют CSRF в памяти; изменяющие защищённые запросы добавляют `X-CSRF-Token`. Если токена ещё нет, клиент сначала читает `/me`. Login/register не требуют CSRF до сессии. Успешный logout и защищённый 401 очищают токен. Пароли/токены не пишутся в browser storage или логи.

| Ответ | Поведение UI |
| --- | --- |
| Защищённый 401 | Состояние anonymous; переход на `/login` с сохранением URL для возврата |
| 401 при login | Видимая ошибка формы, возможность исправить данные, без цикла редиректов |
| 403 | «Нет доступа» и request_id; отказавшие данные не показываются |
| 422 | Общее сообщение и ошибки рядом с email/password; loc `[body,email]` преобразуется в email; `aria-invalid`, `aria-describedby`; неизвестные поля сохраняются в общем сообщении |
| 503 / ошибка сети | Видимое сообщение; форма сохраняет ввод и разрешает повтор; загрузочные экраны имеют кнопку «Повторить» |
| Ошибка прокси с HTML | Сохраняется HTTP-статус; пользователю показывается понятное сообщение |
| Не-JSON при успешном ответе | Типизированная ошибка 502 без подставных данных |
| 501 contract-only | Видимая ошибка backend, mock не включается |

Проверка сессии отличает 503 от отсутствия входа. При смене компании Outlet перемонтируется: локальный event/chat не переносится между компаниями. React выводит текст с экранированием, без вставки сырого HTML.

## Проверка

Инструкции запуска и демонстрационные аккаунты — в [frontend/README.md](../../frontend/README.md). Схемы и все исходные JSON-примеры проверяются в contracts.test.ts; методы, ошибки, маршруты и формы — в остальных тестах. Фактические результаты — в [r-01.md](../qa/r-01.md).

Проверка коллегами, PR и объединение в общую ветку фиксируются отдельно от локального автоматического прогона. Работающий backend A-02/A-03 нужен для проверки настоящей HttpOnly-сессии; A-01 не выдаётся за реализованный auth.
