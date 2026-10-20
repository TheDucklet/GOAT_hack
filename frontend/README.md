# Frontend · R-01

Общий Docker-запуск web/api/worker/postgres теперь описан в [корневом README](../README.md). Docker-сборка frontend всегда использует HTTP API через nginx; инструкция ниже предназначена для отдельной разработки frontend.

React + TypeScript + React Router; сборка Vite. Node.js 24.22.0 (минимум 24.15 в ветке 24), npm. Зависимости зафиксированы в package-lock.json.

Из корня репозитория:

```powershell
cd frontend
npm ci
Copy-Item .env.example .env
npm run dev
```

Открыть <http://127.0.0.1:5173>. Файл-пример явно включает локальный mock. Без `.env` используется настоящий HTTP API, автоматического переключения на mock при ошибке нет.

Демонстрационный вход: `demo@example.org` или `admin@example.org`; пароль `Demo-password-2026`. Это синтетические аккаунты только mock-адаптера. Пользователь начинает без сессии. Для проверки 503 используйте email `unavailable@example.org`, для 403 — `blocked@example.org`, для 422 отправьте пустую форму регистрации. Непустой пароль позволяет дойти до сценариев 403/503 на форме входа. Прямой `/admin` под `demo@example.org` также возвращает 403.

Маршруты: `/login`, `/register`, `/app`, `/app/analytics`, `/admin`. Авторизация восстанавливается через `/me`; защищённый URL после входа сохраняется. Общий header содержит компанию и имя из локальной части email, поскольку отдельное поле имени в доступном описании User отсутствует. Страница аналитики — каркас для R-04–R-06; формы управления членствами и административные таблицы относятся к следующим задачам.

## Настоящий backend

В `.env` установить:

```dotenv
VITE_API_MODE=http
VITE_API_BASE_URL=/api
API_PROXY_TARGET=http://127.0.0.1:8000
```

Vite проксирует `/api/*` в backend без префикса `/api`; браузер работает с одним origin. Для отдельного API можно указать полный `VITE_API_BASE_URL`, например `http://127.0.0.1:8000`; backend должен разрешать конкретный frontend origin и credentials в CORS. Согласовать cookie/SameSite/HTTPS с Алексеем. Секреты и LLM-ключи не помещать в VITE-переменные: они видны браузеру.

Один экземпляр `src/api/index.ts` используется всеми экранами. Cookie отправляются через `credentials: include`; `X-CSRF-Token` берётся из `/me` или login и хранится в памяти. CSRF добавляется к изменяющим защищённым запросам. Auth-данные не записываются в localStorage/sessionStorage. В mock используется отдельная JS-cookie с синтетической идентичностью; она не является настоящей защищённой сессией. Сессию HTTP-режима создаёт только backend.

## Проверки и сборка

```powershell
npm run contracts:check
npm test
$env:VITE_API_MODE='http'
npm run build
npm run preview
```

Mock запрещён в production-сборке. Для локальной демонстрации используйте dev-сервер. `npm test` проверяет маршруты, формы, роли, обработку ошибок, cookies и CSRF без backend и LLM-ключей. Build проверяет TypeScript и создаёт `dist/`; preview слушает <http://127.0.0.1:4173>.

На production-хостинге необходим SPA fallback: `/login`, `/register`, `/app`, `/app/analytics`, `/admin` должны отдавать `index.html`. Пример для nginx:

```nginx
location /api/ {
    proxy_pass http://api:8000/;
}
location / {
    try_files $uri $uri/ /index.html;
}
```

Vite dev/preview уже поддерживают прямые URL. Docker и общая конфигурация nginx/CI — задача R-02.

Типы генерируются из опубликованной A-01 (7f86298), примеры импортируются прямо из `docs/contracts/examples.json`. При изменении OpenAPI выполнить `npm run contracts:generate`, затем `npm run contracts:check` и тесты. HTTP-примеры и дополнительные обёртки mock проверяются по JSON Schema 2020-12. Внутренний AI-пример UserFocus отсутствует в HTTP OpenAPI и проверяется тестами A-01 на стороне Python.

Для повторения браузерного прогона, оставив dev-сервер с mock включённым:

```powershell
python -m pip install playwright==1.58.0
python tests/browser_smoke.py --channel msedge
```

Если Edge отсутствует, установить Chromium: `python -m playwright install chromium` и запустить без `--channel`. Скрипт проверяет прямые URL, 401/403/422/503, вход/выход и ширину 390px; сохраняет отчёт и снимки в `docs/qa/`.

После HTTP-сборки и запуска preview можно отдельно проверить настоящий fetch и cookie/CSRF на перехваченных ответах A-01: `python tests/http_smoke.py --channel msedge`. Это проверка транспорта браузера, не интеграционная проверка живого backend.

Контракт экранов и точные форматы запросов описаны в [ui-requests.md](../docs/contracts/ui-requests.md). Бизнес-endpoints в A-01 ещё возвращают 501; подключение живого auth требует следующих backend-задач.
