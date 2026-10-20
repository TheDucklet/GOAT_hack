# Проверки опубликованного backend

Проверено 20 октября 2026 года. Отчёт относится к накопленной реализации этой ветки. Точный коммит доступен в соответствующем запросе на слияние. Объединение веток и совместная приёмка команды ещё не выполнены.

На SQLite прошли 70 проверок. На PostgreSQL прошли 70 проверок. Ruff и проверка форматирования прошли. Сохранённый OpenAPI совпадает с приложением. Проверяется начальная миграция 0001 и повторный upgrade.

Из каталога backend выполняется следующая команда.

```powershell
..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Для проверки PostgreSQL TEST_DATABASE_URL должен указывать на отдельную базу goat_test. A01_TEST_DATABASE_URL указывает на отдельную базу goat_a01_test. Таблицы тестовой базы пересоздаются. Настоящий LLM и исходные CSV для этих тестов не нужны.

Дополнительно проверена чувствительность тестов к регрессиям. Временное отключение проверки членства вызвало ожидаемое падение теста чужой компании. Временное отключение устранения дублей вызвало ожидаемое падение теста повторного сбора. После каждой проверки исходные файлы восстановлены побайтно. Результаты находятся в regression-detection.json.

Проверка `test_examples_validate` прошла на SQLite и PostgreSQL.

Проверка `test_published_openapi_is_generated_from_current_contract` прошла на SQLite и PostgreSQL.

Проверка `test_every_operation_documents_access_request_response_and_pending_implementation` прошла на SQLite и PostgreSQL.

Проверка `test_contract_operations_do_not_claim_business_functionality` прошла на SQLite и PostgreSQL.

Проверка `test_position_is_free_text_and_public_registration_cannot_select_system_role` прошла на SQLite и PostgreSQL.

Проверка `test_contract_includes_all_required_task_routes` прошла на SQLite и PostgreSQL.

Проверка `test_initial_migration_on_empty_database` прошла на SQLite и PostgreSQL.

Проверка `test_auth_registration_logout_and_csrf` прошла на SQLite и PostgreSQL.

Проверка `test_membership_approval_and_profile_do_not_grant_admin` прошла на SQLite и PostgreSQL.

Проверка `test_cross_company_chat_job_source_and_profile_isolation` прошла на SQLite и PostgreSQL.

Проверка `test_block_revokes_sessions` прошла на SQLite и PostgreSQL.

Проверка `test_import_idempotency_conflicts_unknown_counterparties_and_aggregates` прошла на SQLite и PostgreSQL.

Проверка `test_import_invalid_numeric_rolls_back` прошла на SQLite и PostgreSQL.

Проверка `test_explainable_ranking_and_freshness` прошла на SQLite и PostgreSQL.

Проверка `test_news_deduplication_and_conservative_clustering` прошла на SQLite и PostgreSQL.

Проверка `test_source_failure_does_not_stop_other_source` прошла на SQLite и PostgreSQL.

Проверка `test_job_claim_and_scheduler_dedup` прошла на SQLite и PostgreSQL.

Проверка `test_ai_unavailable_is_failed_without_fake_answer` прошла на SQLite и PostgreSQL.

Проверка `test_insight_chat_persistence_feedback_and_cache` прошла на SQLite и PostgreSQL.

Проверка `test_cache_invalidates_on_profile_focus_and_event_change` прошла на SQLite и PostgreSQL.

Проверка `test_document_upload_dedup_protected_file_and_reindex` прошла на SQLite и PostgreSQL.

Проверка `test_pdf_size_limit` прошла на SQLite и PostgreSQL.

Проверка `test_hidden_news_excluded_from_feed` прошла на SQLite и PostgreSQL.

Проверка `test_openapi_covers_required_routes_and_structured_errors` прошла на SQLite и PostgreSQL.

Проверка `test_published_examples_validate_against_current_schemas` прошла на SQLite и PostgreSQL.

Проверка `test_insight_cache_versions` прошла на SQLite и PostgreSQL.

Проверка `test_invalid_ai_evidence_rolls_back_all_outputs` прошла на SQLite и PostgreSQL.

Проверка `test_job_retries_are_bounded` прошла на SQLite и PostgreSQL.

Проверка `test_parallel_worker_claims_are_distinct` прошла на SQLite и PostgreSQL.

Проверка `test_revoked_membership_prevents_pending_ai_job` прошла на SQLite и PostgreSQL.

Проверка `test_aware_time_is_converted_instead_of_relabelled` прошла на SQLite и PostgreSQL.

Проверка `test_expired_session_is_rejected_in_postgres_timezone` прошла на SQLite и PostgreSQL.

Проверка `test_chat_order_does_not_depend_on_timestamps` прошла на SQLite и PostgreSQL.

Проверка `test_empty_sqlite_can_be_migrated_and_upgraded_twice` прошла на SQLite и PostgreSQL.

Проверка `test_agent_tools_cannot_select_another_company` прошла на SQLite и PostgreSQL.

Проверка `test_bank_repository_date_filter_and_source_locators` прошла на SQLite и PostgreSQL.

Проверка `test_scheduler_repeats_on_interval_and_marks_lost_worker` прошла на SQLite и PostgreSQL.

Файлы real-snapshot.json, live-api.json, worker-schedule.json и restart.json сохранены из локальной проверки полной реализации до разделения на задачи. Они подтверждают тот локальный запуск и не заменяют приёмку общей сборки из GitHub. Проверены 1380585 платежей и два автоматических сбора. В одном RSS элементе была ошибка обработки, отражённая в отчёте worker.

Подключение настоящих AI и OCR остаётся у Фёдора. Frontend и общий Compose остаются у Романа. Образ Docker и совместная сборка здесь не проверены.
