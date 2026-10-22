# Контракты AI-функций

Схемы лежат в `backend/app/ai/schemas/`, примеры – в `docs/contracts/ai-examples.json`. Схемы наследуют модели из `backend/app/schemas.py` и только ужесточают их, поэтому любой результат, прошедший проверку здесь, проходит и проверку backend без правок.

## Функции

Функции вызываются через `backend/app/integrations/ai.py:call_ai` из worker-процесса, значения именованных аргументов описаны в `docs/contracts/integration.md`.

| Функция | Вход (`app.ai.schemas`) | Выход | Допустимые коды ошибок |
| --- | --- | --- | --- |
| `derive_user_focus` | `DeriveUserFocusInput` | `GroundedUserFocus` | `budget_exhausted`, `model_not_allowed`, `timeout`, `rate_limited`, `provider_unavailable`, `invalid_json` |
| `summarize_event` | `SummarizeEventInput` | `GroundedSummaryResult` | те же |
| `ingest_bank_document` | `IngestBankDocumentInput` | `GroundedIngestResult` | `invalid_ocr`, `not_found`, `model_not_allowed`, `budget_exhausted`, `timeout` |
| `search_bank_analytics` | `SearchBankAnalyticsInput` | `BankSearchResult` | `forbidden`, `ai_contract_error` |
| `build_insight` | `BuildInsightInput` | `InsightEnvelopeV2` (с F-14; `InsightEnvelope` остаётся форматом v1) | коды LLM, `forbidden`, `ai_contract_error` |
| `answer_chat` | `AnswerChatInput` | `ChatEnvelope` | коды LLM, `forbidden`, `ai_contract_error` |

Полный перечень входов, выходов и ошибок доступен в коде как `app.ai.schemas.FUNCTION_CONTRACTS`.

С F-15 элемент результата `search_bank_analytics` дополнительно содержит необязательные `title` (название документа), `temporal_status` (`current`, `historical`, `undated`, `period_expired`, `applicability_unknown`) и `temporal_reason`. `historical` истинен для любого статуса, кроме `current`. Репозиторий может передавать имя файла в поле `filename`, backend делает это с F-15. В `locator` банковского evidence добавляются `document_date` и `title`.

## Ошибки

Ошибка поднимается как `AIError(code, message)` из `app.integrations.ai`. Допустимые значения `code` перечислены в `AIErrorCode`. Повторяются только `timeout`, `rate_limited` и `provider_unavailable` (константа `RETRYABLE_CODES`), остальные коды завершают задание сразу. Текст `message` пишется на русском и не содержит ключей, путей и сообщений SDK.

## Evidence

Поля `id`, `kind`, `source_id`, `version`, `locator`, `excerpt` совпадают с `EvidenceOut`. Состав `locator` определяется видом источника.

| kind | locator | Как строится ссылка |
| --- | --- | --- |
| `news` | `{"url": "https://..."}` | переход на первоисточник по `url` |
| `bank` | `{"page": N}`, нумерация с 1 | `GET /sources/{source_id}/file#page=N` |
| `company` | `{"feature_path": "features.<COLUMN>"}` | показ признака профиля и его происхождения |

Функция `evidence_target(evidence)` возвращает готовое описание перехода (`type`, `href`, `page`, `feature_path`).

## Insight

Поля результата совпадают с `InsightResult`. Дополнительно проверяются условия.

- Каждое утверждение (`facts`, `bank_view`, `ai_interpretation`, `risks`, `opportunities`, `actions`) имеет непустой `claim_id` и хотя бы один `evidence_refs`.
- `claim_id` не повторяется внутри карточки.
- `evidence_refs` верхнего уровня равен объединению ссылок всех утверждений.
- При отсутствии банковских материалов `bank_view` равен `null`, а причина указана в `unknowns`. Пустой список недопустим.
- Карточка без фактов обязана содержать `unknowns`.
- В `InsightEnvelope` утверждение из `bank_view` не может ссылаться на evidence с `kind`, отличным от `bank`, если это evidence передано в том же ответе.

`AI-интерпретация` ссылается на предпосылки (новость и признаки компании), а `bank_view` – только на банковские фрагменты, поэтому интерфейс может показывать их раздельно.

## Особенности для backend

- `ingest_bank_document` возвращает фрагменты `{page, text, quality}`, где `quality` содержит `engine`, `chunk_index`, `char_start`, `char_end`, `confidence`. Название документа и SHA-хеш поле `IngestResult` не вмещает (модель запрещает лишние ключи), поэтому они фиксируются в `docs/ai/ocr-report.json`.
- Признак неизвестной даты (`date_unknown`) вычисляется из `document_date is None`, как в `BankRepository.search_chunks`.
- `answer_chat` возвращает `usage` в виде `ChatUsage` (`llm_calls`, `input_tokens`, `output_tokens`, `cost_rub`, `models`).
