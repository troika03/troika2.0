# Неуспешные Python проверки: повтор 6–7 октября 2026 года

Проверки выполнены на native Windows в рабочей копии `codex/product-foundation`
от HEAD `be0cf38` с изменениями текущей задачи и незавершёнными изменениями
параллельных сессий. Это результаты тестов, а не число сломанных функций клиента.
Пользовательские отказы и очередь ремонта находятся в [аудите](../TROIKA_FUNCTIONAL_AUDIT.md).

Первый default запуск через `scripts/run_tests.sh -j 6` сохранил 939 результатов
файлов и был прерван без final summary. Оставшиеся 297 файлов выполнены тем же
runner четырьмя завершёнными партиями с `--file-timeout 90`. Для этих партий
TEMP/TMP перенесены на D: из-за нехватки места на C:. Неудачные промежуточные
попытки не включены. Последний целевой запуск пяти изменённых файлов заменяет
их предыдущие результаты. Файлы учитываются один раз; integration/e2e/docker
исключены из default discovery. Это составной прогон, а не один зелёный запуск.

Внешний launcher последней партии получил `KeyboardInterrupt`; дочерний runner
сохранил final summary `100% complete` и результаты всех 57 файлов партии.
Coverage опирается на эти сохранённые результаты, а не на успешный exit launcher.

Покрытие: **1236 уникальных файлов**. Счётчики сохранившихся per-file
результатов: **24693 passed, 396 failed,
205 skipped, 1 errors, 0 xfailed**.
Неуспешных file runs: **146**. Нулевые counts могут означать
collection/import error или timeout; столбец runner_summary сохраняет исходный
итог. Ограничение времени и среда отличаются от baseline 5 октября, поэтому
разница counters сама по себе не доказывает исправление или регрессию.

Полные результаты: [PYTHON_CHECKS_2026_10_07.tsv](PYTHON_CHECKS_2026_10_07.tsv).
Исторический baseline 5 октября сохранён отдельно. Windows/POSIX ограничения,
зависимости, fixtures и продуктовые ошибки требуют классификации и целевого
воспроизведения. Весь красный baseline нельзя списать на платформу.

| Неуспешный файл | Passed | Failed | Errors | Skipped | Исходный итог runner |
|---|---:|---:|---:|---:|---|
| `tests/acp/test_edit_approval.py` | 7 | 1 | 0 | 0 | 7✓ 1✗, 26.8s |
| `tests/acp/test_ping_suppression.py` | 8 | 1 | 0 | 0 | 8✓ 1✗, 13.2s |
| `tests/acp_adapter/test_acp_images.py` | 5 | 3 | 0 | 0 | 5✓ 3✗, 9.8s |
| `tests/agent/lsp/test_workspace.py` | 11 | 1 | 0 | 0 | 11✓ 1✗, 13.0s |
| `tests/agent/test_codex_ttfb_watchdog.py` | 0 | 0 | 0 | 0 | 46.4s |
| `tests/agent/test_context_references.py` | 13 | 1 | 0 | 0 | 13✓ 1✗, 31.9s |
| `tests/agent/test_gemini_cloudcode.py` | 87 | 1 | 0 | 0 | 87✓ 1✗, 38.2s |
| `tests/agent/test_non_stream_stale_timeout.py` | 0 | 0 | 0 | 0 | 44.0s |
| `tests/agent/test_proxy_and_url_validation.py` | 12 | 3 | 0 | 0 | 12✓ 3✗, 17.0s |
| `tests/agent/test_save_url_image.py` | 7 | 1 | 0 | 0 | 7✓ 1✗, 18.5s |
| `tests/agent/test_shell_hooks.py` | 46 | 7 | 0 | 0 | 46✓ 7✗, 26.5s |
| `tests/agent/test_shell_hooks_consent.py` | 21 | 2 | 0 | 0 | 21✓ 2✗, 22.4s |
| `tests/agent/test_skill_commands.py` | 39 | 2 | 0 | 0 | 39✓ 2✗, 47.0s |
| `tests/agent/test_subdirectory_hints.py` | 23 | 2 | 0 | 0 | 23✓ 2✗, 32.0s |
| `tests/cli/test_cli_approval_ui.py` | 10 | 1 | 0 | 0 | 10✓ 1✗, 20.0s |
| `tests/cli/test_cli_browser_connect.py` | 15 | 1 | 0 | 0 | 15✓ 1✗, 16.4s |
| `tests/cli/test_cli_file_drop.py` | 34 | 1 | 0 | 0 | 34✓ 1✗, 25.0s |
| `tests/cli/test_cli_image_command.py` | 7 | 2 | 0 | 0 | 7✓ 2✗, 22.0s |
| `tests/cli/test_cli_secret_capture.py` | 2 | 3 | 0 | 0 | 2✓ 3✗, 21.3s |
| `tests/cli/test_surrogate_sanitization.py` | 0 | 0 | 0 | 0 | 54.7s |
| `tests/cron/test_cron_workdir.py` | 20 | 1 | 0 | 0 | 20✓ 1✗, 11.8s |
| `tests/cron/test_file_permissions.py` | 2 | 6 | 0 | 0 | 2✓ 6✗, 9.3s |
| `tests/cron/test_scheduler.py` | 124 | 4 | 0 | 0 | 124✓ 4✗, 44.2s |
| `tests/gateway/test_agent_cache.py` | 0 | 0 | 0 | 0 | 104.4s |
| `tests/gateway/test_config_env_bridge_authority.py` | 0 | 6 | 0 | 0 | 6✗, 12.8s |
| `tests/gateway/test_email.py` | 59 | 1 | 0 | 0 | 59✓ 1✗, 15.3s |
| `tests/gateway/test_feishu.py` | 85 | 71 | 0 | 45 | 85✓ 71✗ 45s, 59.1s |
| `tests/gateway/test_msgraph_webhook.py` | 35 | 9 | 0 | 0 | 35✓ 9✗, 8.9s |
| `tests/gateway/test_platform_base.py` | 100 | 1 | 0 | 2 | 100✓ 1✗ 2s, 10.6s |
| `tests/gateway/test_reasoning_command.py` | 17 | 1 | 0 | 0 | 17✓ 1✗, 13.1s |
| `tests/gateway/test_restart_drain.py` | 16 | 1 | 0 | 0 | 16✓ 1✗, 9.7s |
| `tests/gateway/test_runtime_footer.py` | 21 | 4 | 0 | 0 | 21✓ 4✗, 6.7s |
| `tests/gateway/test_setup_feishu.py` | 11 | 3 | 0 | 0 | 11✓ 3✗, 5.5s |
| `tests/gateway/test_stream_consumer.py` | 88 | 1 | 0 | 0 | 88✓ 1✗, 11.9s |
| `tests/gateway/test_stt_config.py` | 4 | 2 | 0 | 0 | 4✓ 2✗, 7.5s |
| `tests/gateway/test_tts_media_routing.py` | 1 | 6 | 0 | 0 | 1✓ 6✗, 4.2s |
| `tests/gateway/test_update_command.py` | 26 | 2 | 0 | 0 | 26✓ 2✗, 6.6s |
| `tests/gateway/test_update_streaming.py` | 20 | 1 | 0 | 0 | 20✓ 1✗, 14.1s |
| `tests/hermes_cli/test_api_key_providers.py` | 0 | 0 | 0 | 0 | 55.2s |
| `tests/hermes_cli/test_auth_nous_provider.py` | 57 | 1 | 0 | 0 | 57✓ 1✗, 35.2s |
| `tests/hermes_cli/test_auth_qwen_provider.py` | 31 | 1 | 0 | 0 | 31✓ 1✗, 6.7s |
| `tests/hermes_cli/test_banner.py` | 5 | 1 | 0 | 0 | 5✓ 1✗, 8.2s |
| `tests/hermes_cli/test_bedrock_model_picker.py` | 0 | 0 | 0 | 0 | 44.2s |
| `tests/hermes_cli/test_cmd_update.py` | 0 | 0 | 0 | 0 | 39.1s |
| `tests/hermes_cli/test_codex_cli_model_picker.py` | 0 | 0 | 0 | 0 | 32.9s |
| `tests/hermes_cli/test_container_boot.py` | 1 | 25 | 0 | 0 | 1✓ 25✗, 5.2s |
| `tests/hermes_cli/test_curses_color_compat.py` | 0 | 0 | 1 | 0 | 1e, 4.3s |
| `tests/hermes_cli/test_debug.py` | 67 | 1 | 0 | 0 | 67✓ 1✗, 11.3s |
| `tests/hermes_cli/test_determine_api_mode_hostname.py` | 0 | 0 | 0 | 0 | 70.0s |
| `tests/hermes_cli/test_gateway.py` | 27 | 6 | 0 | 0 | 27✓ 6✗, 7.4s |
| `tests/hermes_cli/test_gateway_linger.py` | 5 | 1 | 0 | 0 | 5✓ 1✗, 5.2s |
| `tests/hermes_cli/test_gateway_wsl.py` | 15 | 4 | 0 | 0 | 15✓ 4✗, 7.1s |
| `tests/hermes_cli/test_gemini_free_tier_setup_block.py` | 0 | 0 | 0 | 0 | 50.5s |
| `tests/hermes_cli/test_hooks_cli.py` | 9 | 5 | 0 | 0 | 9✓ 5✗, 3.9s |
| `tests/hermes_cli/test_inventory.py` | 0 | 0 | 0 | 0 | 33.5s |
| `tests/hermes_cli/test_kanban_boards.py` | 54 | 2 | 0 | 0 | 54✓ 2✗, 20.1s |
| `tests/hermes_cli/test_kanban_core_functionality.py` | 163 | 1 | 0 | 1 | 163✓ 1✗ 1s, 21.9s |
| `tests/hermes_cli/test_kanban_db.py` | 170 | 2 | 0 | 0 | 170✓ 2✗, 39.8s |
| `tests/hermes_cli/test_model_catalog.py` | 22 | 1 | 0 | 0 | 22✓ 1✗, 13.7s |
| `tests/hermes_cli/test_model_provider_persistence.py` | 0 | 0 | 0 | 0 | 103.0s |
| `tests/hermes_cli/test_model_switch_copilot_api_mode.py` | 0 | 0 | 0 | 0 | 34.5s |
| `tests/hermes_cli/test_model_switch_custom_providers.py` | 0 | 0 | 0 | 0 | 44.7s |
| `tests/hermes_cli/test_model_switch_opencode_anthropic.py` | 0 | 0 | 0 | 0 | 75.8s |
| `tests/hermes_cli/test_openai_codex_model_validation_fallback.py` | 0 | 0 | 0 | 0 | 35.0s |
| `tests/hermes_cli/test_opencode_go_flat_namespace.py` | 0 | 0 | 0 | 0 | 59.5s |
| `tests/hermes_cli/test_overlay_slug_resolution.py` | 0 | 0 | 0 | 0 | 32.7s |
| `tests/hermes_cli/test_path_completion.py` | 24 | 2 | 0 | 0 | 24✓ 2✗, 4.3s |
| `tests/hermes_cli/test_plugins_cmd.py` | 70 | 1 | 0 | 0 | 70✓ 1✗, 8.1s |
| `tests/hermes_cli/test_relaunch.py` | 24 | 1 | 0 | 1 | 24✓ 1✗ 1s, 5.8s |
| `tests/hermes_cli/test_service_manager.py` | 43 | 8 | 0 | 0 | 43✓ 8✗, 8.5s |
| `tests/hermes_cli/test_session_browse.py` | 19 | 14 | 0 | 0 | 19✓ 14✗, 7.3s |
| `tests/hermes_cli/test_setup.py` | 0 | 0 | 0 | 0 | 44.5s |
| `tests/hermes_cli/test_setup_openclaw_migration.py` | 32 | 1 | 0 | 0 | 32✓ 1✗, 9.8s |
| `tests/hermes_cli/test_tools_config.py` | 63 | 15 | 0 | 0 | 63✓ 15✗, 18.0s |
| `tests/hermes_cli/test_tui_resume_flow.py` | 0 | 0 | 0 | 0 | 35.1s |
| `tests/hermes_cli/test_update_autostash.py` | 0 | 0 | 0 | 0 | 40.9s |
| `tests/hermes_cli/test_update_post_pull_syntax_guard.py` | 6 | 2 | 0 | 0 | 6✓ 2✗, 3.8s |
| `tests/hermes_cli/test_update_stale_dashboard.py` | 8 | 6 | 0 | 5 | 8✓ 6✗ 5s, 4.3s |
| `tests/hermes_cli/test_update_yes_flag.py` | 0 | 0 | 0 | 0 | 40.2s |
| `tests/hermes_cli/test_web_server_oauth_write.py` | 1 | 1 | 0 | 0 | 1✓ 1✗, 4.7s |
| `tests/hermes_cli/test_xai_provider_labels.py` | 1 | 1 | 0 | 0 | 1✓ 1✗, 8.2s |
| `tests/plugins/image_gen/test_openai_provider.py` | 24 | 1 | 0 | 0 | 24✓ 1✗, 7.6s |
| `tests/plugins/image_gen/test_xai_provider.py` | 20 | 1 | 0 | 0 | 20✓ 1✗, 113.4s |
| `tests/plugins/memory/test_hindsight_provider.py` | 93 | 3 | 0 | 0 | 93✓ 3✗, 20.9s |
| `tests/plugins/test_disk_cleanup_plugin.py` | 37 | 1 | 0 | 0 | 37✓ 1✗, 7.9s |
| `tests/plugins/test_kanban_dashboard_plugin.py` | 94 | 0 | 0 | 0 | 94✓, 1224.1s |
| `tests/plugins/test_kanban_worker_runs.py` | 11 | 0 | 0 | 0 | 11✓, 1174.2s |
| `tests/plugins/test_langfuse_plugin.py` | 37 | 0 | 0 | 0 | 37✓, 1177.3s |
| `tests/plugins/test_teams_pipeline_plugin.py` | 15 | 2 | 0 | 0 | 15✓ 2✗, 1091.3s |
| `tests/plugins/video_gen/test_fal_plugin.py` | 18 | 0 | 0 | 0 | 18✓, 1088.8s |
| `tests/run_agent/test_860_dedup.py` | 4 | 4 | 0 | 0 | 4✓ 4✗, 60.2s |
| `tests/run_agent/test_codex_app_server_integration.py` | 0 | 0 | 0 | 0 | 35.8s |
| `tests/run_agent/test_compression_boundary_hook.py` | 1 | 2 | 0 | 0 | 1✓ 2✗, 37.8s |
| `tests/run_agent/test_compression_persistence.py` | 4 | 2 | 0 | 0 | 4✓ 2✗, 27.8s |
| `tests/run_agent/test_context_token_tracking.py` | 0 | 0 | 0 | 0 | 37.0s |
| `tests/run_agent/test_dict_tool_call_args.py` | 0 | 0 | 0 | 0 | 33.2s |
| `tests/run_agent/test_invalid_context_length_warning.py` | 0 | 0 | 0 | 0 | 48.0s |
| `tests/run_agent/test_partial_stream_finish_reason.py` | 0 | 0 | 0 | 0 | 36.2s |
| `tests/run_agent/test_primary_runtime_restore.py` | 0 | 0 | 0 | 0 | 125.2s |
| `tests/run_agent/test_provider_attribution_headers.py` | 0 | 0 | 0 | 0 | 94.9s |
| `tests/run_agent/test_provider_fallback.py` | 0 | 0 | 0 | 0 | 153.9s |
| `tests/run_agent/test_provider_parity.py` | 0 | 0 | 0 | 0 | 211.0s |
| `tests/run_agent/test_real_interrupt_subagent.py` | 0 | 1 | 0 | 0 | 1✗, 47.2s |
| `tests/run_agent/test_run_agent.py` | 0 | 0 | 0 | 0 | 280.9s |
| `tests/run_agent/test_run_agent_codex_responses.py` | 0 | 0 | 0 | 0 | 296.2s |
| `tests/skills/test_google_oauth_setup.py` | 13 | 2 | 0 | 0 | 13✓ 2✗, 6.9s |
| `tests/skills/test_openclaw_migration.py` | 38 | 3 | 0 | 0 | 38✓ 3✗, 12.3s |
| `tests/test_bitwarden_secrets.py` | 34 | 2 | 0 | 0 | 34✓ 2✗, 6.5s |
| `tests/test_hermes_logging.py` | 48 | 2 | 0 | 0 | 48✓ 2✗, 12.2s |
| `tests/test_install_sh_symlink_stomp.py` | 1 | 1 | 0 | 0 | 1✓ 1✗, 9.9s |
| `tests/test_live_system_guard_self_test.py` | 26 | 7 | 0 | 1 | 26✓ 7✗ 1s, 12.0s |
| `tests/test_model_tools.py` | 22 | 2 | 0 | 0 | 22✓ 2✗, 12.6s |
| `tests/test_subprocess_home_isolation.py` | 15 | 1 | 0 | 0 | 15✓ 1✗, 8.0s |
| `tests/test_toolsets.py` | 24 | 3 | 0 | 0 | 24✓ 3✗, 9.9s |
| `tests/test_transform_tool_result_hook.py` | 8 | 1 | 0 | 0 | 8✓ 1✗, 14.5s |
| `tests/tools/test_browser_homebrew_paths.py` | 18 | 4 | 0 | 0 | 18✓ 4✗, 6.5s |
| `tests/tools/test_checkpoint_manager.py` | 75 | 2 | 0 | 0 | 75✓ 2✗, 59.4s |
| `tests/tools/test_credential_files.py` | 27 | 2 | 0 | 0 | 27✓ 2✗, 11.9s |
| `tests/tools/test_docker_find.py` | 8 | 1 | 0 | 0 | 8✓ 1✗, 5.2s |
| `tests/tools/test_file_operations.py` | 75 | 2 | 0 | 0 | 75✓ 2✗, 6.4s |
| `tests/tools/test_file_tools_live.py` | 0 | 0 | 0 | 0 | 51 tests, 90.7s |
| `tests/tools/test_file_write_safety.py` | 11 | 5 | 0 | 0 | 11✓ 5✗, 5.4s |
| `tests/tools/test_kanban_codex_lane_skill.py` | 2 | 1 | 0 | 0 | 2✓ 1✗, 7.7s |
| `tests/tools/test_local_background_child_hang.py` | 5 | 3 | 0 | 0 | 5✓ 3✗, 36.9s |
| `tests/tools/test_local_env_blocklist.py` | 17 | 1 | 0 | 0 | 17✓ 1✗, 16.5s |
| `tests/tools/test_local_env_cwd_recovery.py` | 8 | 1 | 0 | 0 | 8✓ 1✗, 8.5s |
| `tests/tools/test_local_interrupt_cleanup.py` | 0 | 2 | 0 | 0 | 2✗, 8.8s |
| `tests/tools/test_local_shell_init.py` | 9 | 5 | 0 | 0 | 9✓ 5✗, 17.0s |
| `tests/tools/test_local_tempdir.py` | 0 | 3 | 0 | 0 | 3✗, 10.3s |
| `tests/tools/test_mcp_oauth.py` | 0 | 0 | 0 | 0 | 67 tests, 6.8s |
| `tests/tools/test_microsoft_graph_auth.py` | 14 | 1 | 0 | 0 | 14✓ 1✗, 6.2s |
| `tests/tools/test_modal_bulk_upload.py` | 8 | 1 | 0 | 0 | 8✓ 1✗, 5.9s |
| `tests/tools/test_modal_sandbox_fixes.py` | 20 | 2 | 0 | 0 | 20✓ 2✗, 9.5s |
| `tests/tools/test_pr_6656_regressions.py` | 9 | 1 | 0 | 0 | 9✓ 1✗, 6.0s |
| `tests/tools/test_process_registry.py` | 57 | 2 | 0 | 5 | 57✓ 2✗ 5s, 10.3s |
| `tests/tools/test_skills_hub.py` | 122 | 3 | 0 | 0 | 122✓ 3✗, 38.5s |
| `tests/tools/test_skills_tool.py` | 86 | 1 | 0 | 0 | 86✓ 1✗, 12.3s |
| `tests/tools/test_ssh_bulk_upload.py` | 16 | 5 | 0 | 0 | 16✓ 5✗, 7.6s |
| `tests/tools/test_tirith_security.py` | 50 | 40 | 0 | 0 | 50✓ 40✗, 12.9s |
| `tests/tools/test_vercel_sandbox_environment.py` | 15 | 1 | 0 | 0 | 15✓ 1✗, 20.4s |
| `tests/tools/test_vision_tools.py` | 69 | 1 | 0 | 0 | 69✓ 1✗, 21.5s |
| `tests/tools/test_web_providers.py` | 12 | 2 | 0 | 0 | 12✓ 2✗, 18.6s |
| `tests/tools/test_web_providers_searxng.py` | 24 | 1 | 0 | 0 | 24✓ 1✗, 11.6s |
| `tests/tools/test_web_tools_config.py` | 47 | 2 | 0 | 0 | 47✓ 2✗, 9.7s |
| `tests/tools/test_windows_native_support.py` | 55 | 3 | 0 | 0 | 55✓ 3✗, 13.7s |
| `tests/tools/test_zombie_process_cleanup.py` | 8 | 1 | 0 | 0 | 8✓ 1✗, 21.5s |
