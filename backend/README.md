# A-01: схемы backend и HTTP-контракт

Требуется Python 3.12. Проверенный набор зависимостей зафиксирован в requirements.lock.
Из корня репозитория:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock
Set-Location backend
Copy-Item .env.example .env
```

Задайте DATABASE_URL в `.env` для своей PostgreSQL. Применение первой миграции:

```powershell
..\.venv\Scripts\python.exe -m app.cli migrate
..\.venv\Scripts\python.exe -m alembic check
```

Просмотр контракта и повторная генерация файла:

```powershell
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# В другом терминале из backend/:
..\.venv\Scripts\python.exe -m app.cli export-openapi
```

Swagger: http://127.0.0.1:8000/docs. `/health` сообщает mode=contract-only и не
проверяет соединение с БД. Операции возвращают 501; это не реализация авторизации,
импорта, сбора новостей, очереди или AI. Все JSON-примеры синтетические.

Проверки, не требующие PostgreSQL или LLM:

```powershell
..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
..\.venv\Scripts\ruff.exe check app tests migrations
```

Для проверки миграции на PostgreSQL создайте отдельную БД `goat_a01_test` и задайте
`A01_TEST_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/goat_a01_test`.
Проверка не удаляет таблицы и не выполняет downgrade. Не используйте рабочую БД.

В Linux/macOS замените команды Windows на `.venv/bin/python` с соответствующим
относительным путём. Исходные CSV/PDF, .env и локальные файлы БД в Git не включаются.
