# Сторонние компоненты AI-модуля

Документ дополняет `docs/notices/backend.md` и перечисляет модели, OCR, данные и сервисы, которые использует `backend/app/ai`. Лицензии моделей сверены 21 октября 2026 года по полю лицензии в карточках моделей на Hugging Face, ссылки приведены в таблице. Перед публикацией репозитория лицензии стоит сверить повторно, потому что карточки могут измениться.

## Языковые модели

Все модели вызываются только через шлюз организаторов, веса в репозитории и на серверах проекта не хранятся. Разрешённый список задан приложением 3 кейса и повторён в `ALLOWED_MODEL_IDS` (`backend/app/ai/providers/models.py`), вызов модели вне списка завершается ошибкой `model_not_allowed` до обращения к сети.

| Модель | ID в шлюзе | Лицензия | Карточка | Задачи в проекте |
| --- | --- | --- | --- | --- |
| Gemma 4 26B A4B | `google/gemma-4-26b-a4b-it` | Apache-2.0 | [google/gemma-4-26B-A4B-it](https://huggingface.co/google/gemma-4-26B-A4B-it) | `derive_user_focus`, `select_industries`, `chat_router`, `agent_query` |
| Qwen3.6 35B A3B | `qwen/qwen3.6-35b-a3b` | Apache-2.0 | [Qwen/Qwen3.6-35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B) | `summarize_event`, `build_insight`, `answer_chat`, `agent_plan`, `agent_check` |
| Qwen3-VL 30B A3B Instruct | `qwen/qwen3-vl-30b-a3b-instruct` | Apache-2.0 | [Qwen/Qwen3-VL-30B-A3B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-30B-A3B-Instruct) | `ocr_vision` |
| GLM-5.3-Flash | `z-ai/glm-5.3-flash` | MIT | [zai-org/GLM-5.3-Flash](https://huggingface.co/zai-org/GLM-5.3-Flash) | не назначена |
| DeepSeek-V4.1-Flash | `deepseek/deepseek-v4.1-flash` | MIT | [deepseek-ai/DeepSeek-V4.1-Flash](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash) | не назначена |
| Kimi K2.6 | `moonshotai/kimi-k2.6` | Modified MIT | [moonshotai/Kimi-K2.6](https://huggingface.co/moonshotai/Kimi-K2.6) | не назначена |

Три последние модели разрешены, но в `DEFAULT_TASK_MODELS` не используются: Kimi K2.6 в 4–8 раз дороже остальных, а для остальных задач хватает первых трёх. Назначение можно изменить переменной `AI_LLM_TASK_MODELS`. Условия Modified MIT для Kimi K2.6 содержатся в файле LICENSE репозитория модели, при использовании её результатов в продукте их нужно прочитать отдельно.

## Распознавание PDF

Страницы PDF превращаются в изображения и распознаются моделью `qwen/qwen3-vl-30b-a3b-instruct` через тот же шлюз. Отдельных OCR-движков, локальных моделей и обученных нами весов нет.

| Компонент | Версия | Лицензия | Назначение |
| --- | --- | --- | --- |
| `pypdfium2` (включает PDFium) | 5.14.0 | BSD-3-Clause, Apache-2.0 | отрисовка страниц PDF в изображения |
| `Pillow` | 13.0.0 | MIT-CMU | обрезка и нарезка изображений страниц |
| `pypdf` | 6.21.1 | BSD-3-Clause | подсчёт страниц |

Лицензии библиотек указаны по метаданным установленных дистрибутивов, версии зафиксированы в `backend/requirements.lock`.

## Прочие библиотеки AI-модуля

| Компонент | Версия | Лицензия | Назначение |
| --- | --- | --- | --- |
| `httpx` | 0.28.1 | BSD-3-Clause | запросы к шлюзу моделей |
| `pydantic` | 2.14.1 | MIT | схемы входов и ответов |
| `pydantic-settings` | 2.16.1 | MIT | чтение переменных окружения `AI_*` |

## Данные

| Данные | Источник | Как используются |
| --- | --- | --- |
| Профили компаний (`df_Uid_data_hack.csv`, `df_Uid_payment_hack.csv`, `df_Fid_Uid_link_hack.csv`) | организаторы кейса, набор `data1`, идентификаторы обезличены | признаки компании в карточках и чате, словарь отраслей для суммаризации, четыре профиля в `docs/ai/fixtures/companies.json` |
| Аналитические материалы Альфа-Банка, девять PDF | организаторы кейса, набор `data2` | распознаются OCR, индексируются для поиска; тексты фрагментов лежат в `docs/ai/fixtures/bank-chunks.json`, `docs/ai/ocr-report.json` и в цитатах примеров |
| Новости | публикации, которые собирает backend, и синтетические тексты для проверок (`docs/ai/fixtures/events.json`, `docs/quality/fixtures/acceptance-inputs.json`) | суммаризация и карточки; в синтетических новостях числа вымышлены |

Данные организаторов предоставлены для участия в хакатоне. Фрагменты материалов банка в файлах репозитория нужны для воспроизводимых проверок без базы данных. Если репозиторий будет публиковаться за пределами команды и жюри, эти файлы (`bank-chunks.json`, `ocr-report.json`, примеры карточек и чата) нужно заменить синтетическими или удалить.

## Сервисы и моделируемые интеграции

- Шлюз моделей организаторов (`AI_LLM_BASE_URL`, по умолчанию `https://changellenge.up.railway.app/v1`) с ключом команды и лимитом, эквивалентным 500 руб. в сутки. Ключ хранится только в серверном окружении и не попадает в репозиторий и frontend.
- PostgreSQL 17 с полнотекстовым поиском для `search_bank_analytics`, лицензия PostgreSQL License, описана в `docs/notices/backend.md`.
- Локальный инструмент `LocalTools` и поиск по снимку `bank-chunks.json` в командах проверки (`python -m app.ai.insights`, `agent`, `chat`, `evaluation`). Он моделирует `AnalysisTools` backend без базы данных и в рабочий режим не подключается.
- Подставной провайдер `ScriptedTransport` (`app/ai/providers/testing.py`) используется только в тестах.
