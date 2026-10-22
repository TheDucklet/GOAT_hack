# R-01 / R-03 / R-04 / R-05 · HTTP-запросы интерфейса

Основания: TASKS.md (R-01/A-01), 00-system-overview.pdf, 01-roman-tasks.pdf и опубликованный HTTP-контракт Алексея. Дата: 20.10.2026.

## Входной контракт

A-01 получена из `a-01/alexey/api-contract`, коммит `7f86298b52ea88fe49c9abe0ab1c6c0ce81c81d7`. R-01 основана на этой ветке. Источник истины — [openapi.json](openapi.json); примеры — [examples.json](examples.json) из того же коммита. Исходные backend-файлы и JSON не изменены.

`frontend/src/shared/api/schema.d.ts` генерируется из OpenAPI (`npm run contracts:generate`), `types.ts` содержит только алиасы этих схем. `npm run contracts:check` выявляет рассогласование с OpenAPI. Mock импортирует оригинальный examples.json напрямую и использует примеры me, successful_user, membership, feed, chat, pending_job, stats, error и insufficient_data. Для CompanyOut и внешнего InsightOut отдельных примеров нет: только эти обёртки составлены дополнительно и тоже валидируются по OpenAPI. Административная mock-сессия отличается от примера MeOut только email и system_role.

Существенные детали контракта: `/me` и login возвращают **плоский MeOut**, без обёртки user; ErrorOut.field_errors — **массив `{loc,message,type}`**, как в backend/app/errors.py; FeedItem.relevance_reasons и sources — массивы объектов; отправка сообщения — `{text}`; JobOut содержит **id**, не job_id. Регистрация принимает пароль 10–256 символов, вход — 1–256. Должность — произвольная строка.

В R-03 подключён опубликованный backend A-13, включающий живые auth и доступы из A-02/A-03. Историческая приёмка R-01 использовала локальный mock по A-01; HTTP-режим никогда не заменяет 501 или сбой backend тестовым успехом.

## Реализованные экраны

| Экран / действие | Запрос | Читаемые поля / результат |
| --- | --- | --- |
| Запуск, восстановление сессии | `GET /me` | `id,email,system_role,status`; `memberships[].id,user_id,company_id,status,position_text,interests`; `csrf_token` |
| `/login`, отправка формы | `POST /auth/login` `{email,password}` | MeOut; CSRF в памяти; возврат к защищённому URL или `/app` |
| `/register`, отправка формы | `POST /auth/register` `{email,password}` | UserOut, 201 → `/login`; системная роль не отправляется |
| Header защищённых страниц | `GET /companies` | Массив доступных `id,name,profile_version`; выбранная компания задаётся общим контекстом |
| Header, выход | `POST /auth/logout` | 204; очистка CSRF/состояния, переход на `/login` |
| `/app` | Общие `/me` и `/companies` | Название компании; постоянная ссылка «Бизнес-аналитика» |
| `/app/companies` | `GET /me`, `GET /companies` | Все собственные членства: id, company_id, status, position_text, interests; названия только активных компаний |
| Заявка на компанию | `POST /memberships/requests` `{company_id,position_text,interests}` | 201 MembershipOut; показ pending без расширения доступа |
| Профиль в карточке членства | `PATCH /memberships/{id}/profile` `{position_text,interests}` | MembershipOut; обновление сохранённого профиля в состоянии текущей сессии |
| «Обновить доступ» | `GET /me`; при изменении active-членств `GET /companies` | Подтверждение/отклонение берётся с сервера, список доступных компаний перечитывается |
| `/app/analytics`, первая страница, смена компании, «Обновить ленту» | `GET /companies/{id}/feed?limit=20&offset=0` | `items[].event_id,title,summary,published_at,status,sources,relevance_reasons`; `total,limit,offset` |
| «Загрузить ещё» | `GET /companies/{id}/feed?limit=20&offset=N` | Следующая страница дополняет список; N — offset ответа + число элементов; порядок API сохраняется, повторные event_id не дублируются |
| Выбор заголовка события | Запрос не нужен | `event_id` и FeedItem поступают в панели аналитики/чата через общее AnalyticsSelection; прежний chat очищается при смене события |
| `/admin` | `GET /admin/stats` | `positive_feedback,negative_feedback,failed_jobs`; число оценок — сумма первых двух; 403 → «Нет доступа» |

В UserOut нет отдельного поля имени: header показывает локальную часть email до `@` и email. `position_text` не используется как разрешение. Административная ссылка зависит только от system_role; прямой `/admin` всегда проверяется запросом к серверу. Список компаний приходит только из `/companies` и сверяется с active-членствами `/me`; клиент не расширяет его по pending/rejected. Без доступной компании аналитика показывает приглашение подать заявку. Список членств показывает также pending/rejected; для них доступен идентификатор компании, публичного каталога или поиска имён компаний в контракте нет.

Должность не выбирается из списка. `position_text` передаётся целиком; `interests` получается из непустых строк поля, по одной теме на строку. Ограничения 1000 символов / 30 интересов проверяет сервер; ошибки 422, включая `interests.N`, связываются с соответствующим полем. 409 email_exists связывается с email; 404/409 заявки — с company_id. Payload профиля не содержит system_role, user_id или status. После обновления страницы профиль восстанавливается из `/me`, а не из localStorage. Новый пользователь регистрируется без сессии и входит отдельно.

R-04 использует настоящий endpoint A-06. Смена компании очищает страницы, событие и chat, отменяет запросы; запоздавшие ответы игнорируются. Обновление ленты очищает выбор и перечитывает первую страницу. При 503 следующей страницы уже загруженные события сохраняются; «Повторить» повторяет тот же offset. При 403 загруженные события и выбор удаляются. Пустая выдача показывает «Нет подходящих событий». Отсутствующие summary/дата/источники/причины имеют явные подписи; даты показаны по Москве, исходный published_at сохранён в time[datetime]. Ссылки источников допускают только абсолютные HTTP(S) URL и открываются с noopener/noreferrer. Текст не интерпретируется как HTML. Полный Insight подключён в R-05; сообщения чата относятся к R-06. R-04 передаёт общий выбранный контекст и не запускает генерацию.

## Методы единого клиента

Методы типизированы и используют один HttpClient. Feed подключён в R-04, карточка и основания — в R-05; чат относится к R-06.

| Задача | Метод / endpoint | Поля |
| --- | --- | --- |
| R-04 | `feed` → `GET /companies/{id}/feed?limit=&offset=` | `items[].event_id,title,summary,published_at,rank_score,relevance_reasons,status,sources`; `total,limit,offset` |
| R-05 | `buildInsight` → `POST /companies/{id}/insights` `{event_id}` | 200: `id,company_id,event_id,versions,result`; 202: JobOut |
| R-05 | `insight` → `GET /insights/{id}` | `result.facts,bank_view,ai_interpretation,risks,opportunities,actions,unknowns,evidence_refs,trace_id`; Claim: `claim_id,text,evidence_refs` |
| R-06 | `createChat` → `POST /chats` `{company_id,event_id}` | `id,company_id,event_id` |
| R-06 | `sendMessage` → `POST /chats/{id}/messages` `{text}` | JobOut; 202 |
| R-06 | `messages` → `GET /chats/{id}/messages` | Массив `id,chat_id,sequence,role,text,result,created_at` |
| R-05/R-06 | `job` → `GET /jobs/{id}` | `id,status,result,error`; queued/running/done/failed; при result.insight_id потребитель читает карточку |
| R-05/R-06 | `source` → `GET /sources/{id}`; PDF → `GET /sources/{id}/file` | `kind,source_id,version,locator,excerpt`; авторизованное чтение, точная страница в `#page=N` |

FeedItem.summary и published_at могут быть null. Bank_view — массив Claim либо null; отсутствие банковского материала не подменяется AI-мнением. Evidence содержит id/kind/source_id/version/locator/excerpt. Детальные схемы, включая произвольные locator и result.error, берутся из generated types.

## Карточка и основания R-05

Выбор события открывает контекст карточки. «Подготовить анализ» явно вызывает `buildInsight(companyId,eventId,signal)` один раз. Рендер и выбор события сами не создают задания. Ответ 200 отображается непосредственно; при 202 общий `waitForJob` читает `GET /jobs/{id}` раз в 2 секунды, максимум 120 секунд ожидания на попытку, затем читает `GET /insights/{result.insight_id}`. Ожидание можно продолжить вручную; сетевой сбой после принятого задания повторяет GET, а не POST. Failed/budget_exhausted не превращаются в готовый ответ; новый запуск выполняется только вручную. При смене company/event запросы и таймеры отменяются, запоздалый результат игнорируется. Компания и событие в ответе проверяются перед отображением.

`AnalyticsSelection` хранит `insightId` вместе с company/event/chat. Для будущей ленты R-13 доступен `selectEvent(event, insightId)`: переданный идентификатор читается GET без генерации. Проверка актуальности перечитывает сохранённую карточку; `stale` виден и предлагает ручное обновление анализа. При 403 содержимое очищается, при 401 действует общий возврат ко входу.

Карточки v1 и v2 используют общие секции facts/bank_view/ai_interpretation/risks/opportunities/actions/unknowns. V2 дополнительно показывает personalized_summary/mechanism/impact_level/impact_reason/time_horizon/assumptions, сроки актуальности и review_after. Типы fact/hypothesis/scenario сохраняются; в v1 отсутствующий тип интерпретации явно не объявляется фактом. Количественный сценарий показывает входы, единицы, периоды, диапазон и предпосылки; формула отображается текстом. `undetermined` означает «Недостаточно данных». Устаревший или отсутствующий банковский материал не блокирует внешний анализ.

| Основание | Запрос и отображение |
| --- | --- |
| Любое утверждение | Общий `EvidenceLink` по нажатию читает `GET /sources/{evidence_id}` через тот же HttpClient с cookie. Ссылки модели напрямую не используются. |
| Новость | `locator.url` допускает только абсолютный HTTP(S) без credentials; `published_at`, excerpt, version; noopener/noreferrer. |
| Банковский PDF | `locator.document_date`, положительный целый `locator.page`; ссылка строится как `${API_BASE}/sources/{evidence_id}/file#page=N`. Страница и домен из произвольного URL модели не принимаются. GET PDF повторно проверяет серверную сессию. |
| Признак компании | Точный `locator.feature_path`, значение/quality, версия и stale. Доступ проверяет сервер, произвольный company_id клиент не запрашивает. |

`InsightNotice` использует только [notice-policy.json](notice-policy.json). Полный notice_v1 постоянно находится внутри панели, включая v1, пустую/неполную карточку, загрузку и ошибки. Поле disclaimer из ответа модели не управляет текстом приложения. HTML, excerpt и формулы не исполняются. Синтетический браузерный regression описан в [r-05.md](../qa/r-05.md); он использует настоящий API/PG/worker и отдельный синтетический producer, не является прогоном платной модели.

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
