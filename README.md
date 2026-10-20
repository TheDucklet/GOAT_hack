# GOAT_hack

Реализованы **A-01** (модели, первая миграция, HTTP-контракт) и **R-01**
(React/TypeScript, маршруты, общий layout, API-клиент и mock на примерах A-01).

- [OpenAPI](docs/contracts/openapi.json)
- [Примеры ответов](docs/contracts/examples.json)
- [Правила контракта](docs/contracts/README.md)
- [Установка, миграции и проверки](backend/README.md)
- [Запуск frontend и демонстрационные аккаунты](frontend/README.md)
- [Запросы экранов и обработка ошибок](docs/contracts/ui-requests.md)
- [Результаты проверок R-01](docs/qa/r-01.md)
- [Исходный реестр задач команды](TASKS.md)

Операции приложения в этой ветке возвращают **501 not_implemented**. Правила доступа
объявлены в контракте, их исполнение реализуется в A-02 и следующих задачах.
