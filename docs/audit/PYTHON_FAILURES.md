# Неуспешные Python проверки на Windows

Проверка 2026-10-05; это результаты automated tests, не перечень доказанных
ошибок каждого пользовательского сценария. Поломки ordinary Troika перечислены
в [основном аудите](../TROIKA_FUNCTIONAL_AUDIT.md).

Первый default прогон обнаружил 1233 файла и завершился с exit 1. Его журнал
содержит результаты 938 файлов без итогового summary; недостающие 295 файлов
запущены повторно через тот же runner с прямым сохранением stdout/stderr.
Процент первого runner был 0% из-за отсутствия предварительного count; это
не означает, что tests не запускались. Counts ниже собраны из per-file результатов.
У внешнего launcher повторного запуска зафиксирован `KeyboardInterrupt`, но
дочерний runner сохранил final summary `100% complete` и результаты всех 295 файлов.
Причина прерывания launcher в этой ревизии не установлена.
Raw logs оставлены вне Git; сюда включены только test paths, counts и identifiers.

Integration/e2e/docker исключены из default discovery; отдельный Discord voice
integration run дал 34 passed. Это не Android voice E2E.

## Итог и исключения

Coverage: 1233 уникальных файлов; 25032 passed, 407 failed, 205 skipped, 1 errors, 0 xfailed. Неуспешных file runs: 125.

Один failure `tests/product/test_product_positioning.py` возник при сокращении
README в этой ревизии. Product promise/audience восстановлены; отдельный повтор
дал 2 passed. Он остаётся в исходных counts для прозрачности, но не является
незакрытым дефектом финального изменения. Остальные failures здесь не исправлялись.

Windows paths/newlines/permissions, POSIX shell/systemd/PTY и asyncio pipe
ограничения требуют отдельной классификации. Provider mocks, catalog drift и
agent behavior failures также требуют целевого воспроизведения. Нельзя списать
весь красный baseline на платформу или объявить каждый test failure поломкой продукта.

Полные file results: [PYTHON_CHECKS.tsv](PYTHON_CHECKS.tsv). Нулевые test counts
в failed file могут означать collection/import error или timeout; количество
таких файлов важнее одного суммарного failed counter.

## Неуспешные файлы

| Test file | Passed | Failed | Errors | Skipped |
|---|---:|---:|---:|---:|
| `tests/acp/test_edit_approval.py` | 7 | 1 | 0 | 0 |
| `tests/acp/test_ping_suppression.py` | 8 | 1 | 0 | 0 |
| `tests/acp_adapter/test_acp_images.py` | 5 | 3 | 0 | 0 |
| `tests/agent/lsp/test_workspace.py` | 11 | 1 | 0 | 0 |
| `tests/agent/test_codex_ttfb_watchdog.py` | 0 | 0 | 0 | 0 |
| `tests/agent/test_context_references.py` | 13 | 1 | 0 | 0 |
| `tests/agent/test_gemini_cloudcode.py` | 87 | 1 | 0 | 0 |
| `tests/agent/test_proxy_and_url_validation.py` | 12 | 3 | 0 | 0 |
| `tests/agent/test_save_url_image.py` | 7 | 1 | 0 | 0 |
| `tests/agent/test_shell_hooks.py` | 46 | 7 | 0 | 0 |
| `tests/agent/test_shell_hooks_consent.py` | 21 | 2 | 0 | 0 |
| `tests/agent/test_skill_commands.py` | 39 | 2 | 0 | 0 |
| `tests/agent/test_subdirectory_hints.py` | 23 | 2 | 0 | 0 |
| `tests/cli/test_cli_browser_connect.py` | 15 | 1 | 0 | 0 |
| `tests/cli/test_cli_file_drop.py` | 34 | 1 | 0 | 0 |
| `tests/cli/test_cli_image_command.py` | 7 | 2 | 0 | 0 |
| `tests/cli/test_cli_secret_capture.py` | 2 | 3 | 0 | 0 |
| `tests/cli/test_surrogate_sanitization.py` | 0 | 0 | 0 | 0 |
| `tests/cron/test_cron_workdir.py` | 20 | 1 | 0 | 0 |
| `tests/cron/test_file_permissions.py` | 2 | 6 | 0 | 0 |
| `tests/cron/test_scheduler.py` | 124 | 4 | 0 | 0 |
| `tests/gateway/test_config_env_bridge_authority.py` | 0 | 6 | 0 | 0 |
| `tests/gateway/test_email.py` | 59 | 1 | 0 | 0 |
| `tests/gateway/test_feishu.py` | 85 | 71 | 0 | 45 |
| `tests/gateway/test_msgraph_webhook.py` | 35 | 9 | 0 | 0 |
| `tests/gateway/test_platform_base.py` | 100 | 1 | 0 | 2 |
| `tests/gateway/test_reasoning_command.py` | 17 | 1 | 0 | 0 |
| `tests/gateway/test_restart_drain.py` | 16 | 1 | 0 | 0 |
| `tests/gateway/test_runtime_footer.py` | 21 | 4 | 0 | 0 |
| `tests/gateway/test_setup_feishu.py` | 11 | 3 | 0 | 0 |
| `tests/gateway/test_stream_consumer.py` | 88 | 1 | 0 | 0 |
| `tests/gateway/test_stt_config.py` | 4 | 2 | 0 | 0 |
| `tests/gateway/test_tts_media_routing.py` | 1 | 6 | 0 | 0 |
| `tests/gateway/test_update_command.py` | 26 | 2 | 0 | 0 |
| `tests/gateway/test_update_streaming.py` | 20 | 1 | 0 | 0 |
| `tests/hermes_cli/test_atomic_json_write.py` | 13 | 1 | 0 | 0 |
| `tests/hermes_cli/test_auth_nous_provider.py` | 57 | 1 | 0 | 0 |
| `tests/hermes_cli/test_auth_qwen_provider.py` | 31 | 1 | 0 | 0 |
| `tests/hermes_cli/test_banner.py` | 5 | 1 | 0 | 0 |
| `tests/hermes_cli/test_container_boot.py` | 1 | 25 | 0 | 0 |
| `tests/hermes_cli/test_curses_color_compat.py` | 0 | 0 | 1 | 0 |
| `tests/hermes_cli/test_debug.py` | 67 | 1 | 0 | 0 |
| `tests/hermes_cli/test_gateway.py` | 27 | 6 | 0 | 0 |
| `tests/hermes_cli/test_gateway_linger.py` | 5 | 1 | 0 | 0 |
| `tests/hermes_cli/test_gateway_wsl.py` | 15 | 4 | 0 | 0 |
| `tests/hermes_cli/test_hooks_cli.py` | 9 | 5 | 0 | 0 |
| `tests/hermes_cli/test_kanban_boards.py` | 0 | 0 | 0 | 0 |
| `tests/hermes_cli/test_kanban_core_functionality.py` | 163 | 1 | 0 | 1 |
| `tests/hermes_cli/test_kanban_db.py` | 170 | 2 | 0 | 0 |
| `tests/hermes_cli/test_model_catalog.py` | 22 | 1 | 0 | 0 |
| `tests/hermes_cli/test_path_completion.py` | 24 | 2 | 0 | 0 |
| `tests/hermes_cli/test_plugins_cmd.py` | 70 | 1 | 0 | 0 |
| `tests/hermes_cli/test_relaunch.py` | 24 | 1 | 0 | 1 |
| `tests/hermes_cli/test_service_manager.py` | 43 | 8 | 0 | 0 |
| `tests/hermes_cli/test_session_browse.py` | 19 | 14 | 0 | 0 |
| `tests/hermes_cli/test_setup.py` | 17 | 2 | 0 | 0 |
| `tests/hermes_cli/test_setup_openclaw_migration.py` | 32 | 1 | 0 | 0 |
| `tests/hermes_cli/test_timeouts.py` | 0 | 0 | 0 | 0 |
| `tests/hermes_cli/test_tools_config.py` | 63 | 15 | 0 | 0 |
| `tests/hermes_cli/test_tui_resume_flow.py` | 0 | 0 | 0 | 0 |
| `tests/hermes_cli/test_update_autostash.py` | 0 | 0 | 0 | 0 |
| `tests/hermes_cli/test_update_post_pull_syntax_guard.py` | 6 | 2 | 0 | 0 |
| `tests/hermes_cli/test_update_stale_dashboard.py` | 8 | 6 | 0 | 5 |
| `tests/hermes_cli/test_update_yes_flag.py` | 0 | 0 | 0 | 0 |
| `tests/hermes_cli/test_web_server_oauth_write.py` | 1 | 1 | 0 | 0 |
| `tests/plugins/image_gen/test_openai_provider.py` | 24 | 1 | 0 | 0 |
| `tests/plugins/image_gen/test_xai_provider.py` | 20 | 1 | 0 | 0 |
| `tests/plugins/memory/test_hindsight_provider.py` | 93 | 3 | 0 | 0 |
| `tests/plugins/test_disk_cleanup_plugin.py` | 37 | 1 | 0 | 0 |
| `tests/plugins/test_teams_pipeline_plugin.py` | 15 | 2 | 0 | 0 |
| `tests/product/test_product_positioning.py` | 1 | 1 | 0 | 0 |
| `tests/run_agent/test_860_dedup.py` | 4 | 4 | 0 | 0 |
| `tests/run_agent/test_codex_app_server_integration.py` | 0 | 0 | 0 | 0 |
| `tests/run_agent/test_compression_boundary_hook.py` | 1 | 2 | 0 | 0 |
| `tests/run_agent/test_compression_persistence.py` | 4 | 2 | 0 | 0 |
| `tests/run_agent/test_context_token_tracking.py` | 0 | 0 | 0 | 0 |
| `tests/run_agent/test_dict_tool_call_args.py` | 0 | 0 | 0 | 0 |
| `tests/run_agent/test_invalid_context_length_warning.py` | 0 | 0 | 0 | 0 |
| `tests/run_agent/test_primary_runtime_restore.py` | 0 | 0 | 0 | 0 |
| `tests/run_agent/test_provider_fallback.py` | 0 | 0 | 0 | 0 |
| `tests/run_agent/test_provider_parity.py` | 0 | 0 | 0 | 0 |
| `tests/run_agent/test_real_interrupt_subagent.py` | 0 | 1 | 0 | 0 |
| `tests/run_agent/test_run_agent.py` | 0 | 0 | 0 | 0 |
| `tests/run_agent/test_run_agent_codex_responses.py` | 0 | 0 | 0 | 0 |
| `tests/skills/test_google_oauth_setup.py` | 13 | 2 | 0 | 0 |
| `tests/skills/test_openclaw_migration.py` | 38 | 3 | 0 | 0 |
| `tests/test_bitwarden_secrets.py` | 34 | 2 | 0 | 0 |
| `tests/test_hermes_logging.py` | 48 | 2 | 0 | 0 |
| `tests/test_install_sh_symlink_stomp.py` | 1 | 1 | 0 | 0 |
| `tests/test_live_system_guard_self_test.py` | 26 | 7 | 0 | 1 |
| `tests/test_model_tools.py` | 22 | 2 | 0 | 0 |
| `tests/test_subprocess_home_isolation.py` | 15 | 1 | 0 | 0 |
| `tests/test_toolsets.py` | 24 | 3 | 0 | 0 |
| `tests/test_transform_tool_result_hook.py` | 8 | 1 | 0 | 0 |
| `tests/tools/test_browser_homebrew_paths.py` | 18 | 4 | 0 | 0 |
| `tests/tools/test_checkpoint_manager.py` | 74 | 3 | 0 | 0 |
| `tests/tools/test_credential_files.py` | 27 | 2 | 0 | 0 |
| `tests/tools/test_docker_find.py` | 8 | 1 | 0 | 0 |
| `tests/tools/test_file_operations.py` | 75 | 2 | 0 | 0 |
| `tests/tools/test_file_tools_live.py` | 41 | 10 | 0 | 0 |
| `tests/tools/test_file_write_safety.py` | 11 | 5 | 0 | 0 |
| `tests/tools/test_kanban_codex_lane_skill.py` | 2 | 1 | 0 | 0 |
| `tests/tools/test_local_background_child_hang.py` | 5 | 3 | 0 | 0 |
| `tests/tools/test_local_env_blocklist.py` | 17 | 1 | 0 | 0 |
| `tests/tools/test_local_env_cwd_recovery.py` | 8 | 1 | 0 | 0 |
| `tests/tools/test_local_interrupt_cleanup.py` | 0 | 2 | 0 | 0 |
| `tests/tools/test_local_shell_init.py` | 9 | 5 | 0 | 0 |
| `tests/tools/test_local_tempdir.py` | 0 | 3 | 0 | 0 |
| `tests/tools/test_mcp_oauth.py` | 0 | 0 | 0 | 0 |
| `tests/tools/test_microsoft_graph_auth.py` | 14 | 1 | 0 | 0 |
| `tests/tools/test_modal_bulk_upload.py` | 8 | 1 | 0 | 0 |
| `tests/tools/test_modal_sandbox_fixes.py` | 20 | 2 | 0 | 0 |
| `tests/tools/test_pr_6656_regressions.py` | 9 | 1 | 0 | 0 |
| `tests/tools/test_process_registry.py` | 57 | 2 | 0 | 5 |
| `tests/tools/test_skills_hub.py` | 122 | 3 | 0 | 0 |
| `tests/tools/test_skills_tool.py` | 86 | 1 | 0 | 0 |
| `tests/tools/test_ssh_bulk_upload.py` | 16 | 5 | 0 | 0 |
| `tests/tools/test_tirith_security.py` | 50 | 40 | 0 | 0 |
| `tests/tools/test_vercel_sandbox_environment.py` | 15 | 1 | 0 | 0 |
| `tests/tools/test_vision_tools.py` | 69 | 1 | 0 | 0 |
| `tests/tools/test_web_providers.py` | 12 | 2 | 0 | 0 |
| `tests/tools/test_web_providers_searxng.py` | 24 | 1 | 0 | 0 |
| `tests/tools/test_web_tools_config.py` | 47 | 2 | 0 | 0 |
| `tests/tools/test_windows_native_support.py` | 55 | 3 | 0 | 0 |
| `tests/tools/test_zombie_process_cleanup.py` | 8 | 1 | 0 | 0 |

## Identifiers, сохранившиеся в журналах

Некоторые inline summaries ограничены последними 30 строками; список identifiers
может быть неполным. Таблица file runs выше покрывает все неуспешные файлы.


### `tests/acp/test_edit_approval.py`

- `tests/acp/test_edit_approval.py::test_write_file_approval_mutates_and_request_includes_diff`

### `tests/acp/test_ping_suppression.py`

- `tests/acp/test_ping_suppression.py::test_bare_ping_request_produces_proper_response_and_no_stderr_noise`

### `tests/acp_adapter/test_acp_images.py`

- `tests/acp_adapter/test_acp_images.py::test_acp_resource_link_file_is_inlined_as_text`
- `tests/acp_adapter/test_acp_images.py::test_acp_resource_link_image_file_is_inlined_as_image_url`
- `tests/acp_adapter/test_acp_images.py::test_acp_resource_link_image_mime_inferred_from_suffix`

### `tests/agent/lsp/test_workspace.py`

- `tests/agent/lsp/test_workspace.py::test_normalize_path_expands_tilde`

### `tests/agent/test_context_references.py`

- `tests/agent/test_context_references.py::test_blocks_sensitive_home_and_hermes_paths`

### `tests/agent/test_gemini_cloudcode.py`

- `tests/agent/test_gemini_cloudcode.py::TestCredentialIo::test_save_uses_0600_permissions`

### `tests/agent/test_proxy_and_url_validation.py`

- `tests/agent/test_proxy_and_url_validation.py::test_proxy_env_rejects_malformed_port[all_proxy]`
- `tests/agent/test_proxy_and_url_validation.py::test_proxy_env_rejects_malformed_port[http_proxy]`
- `tests/agent/test_proxy_and_url_validation.py::test_proxy_env_rejects_malformed_port[https_proxy]`

### `tests/agent/test_save_url_image.py`

- `tests/agent/test_save_url_image.py::TestSaveUrlImage::test_writes_real_bytes_to_hermes_home_cache`

### `tests/agent/test_shell_hooks.py`

- `tests/agent/test_shell_hooks.py::TestAllowlistConcurrency::test_script_is_executable_handles_interpreter_prefix`
- `tests/agent/test_shell_hooks.py::TestCallbackSubprocess::test_block_aggregation_through_plugin_manager`
- `tests/agent/test_shell_hooks.py::TestCallbackSubprocess::test_block_translation_end_to_end`
- `tests/agent/test_shell_hooks.py::TestCallbackSubprocess::test_matcher_regex_filters_callback`
- `tests/agent/test_shell_hooks.py::TestCallbackSubprocess::test_non_zero_exit_with_block_stdout_still_blocks`
- `tests/agent/test_shell_hooks.py::TestCallbackSubprocess::test_payload_schema_delivered`
- `tests/agent/test_shell_hooks.py::TestCallbackSubprocess::test_pre_llm_call_context_flows_through`

### `tests/agent/test_shell_hooks_consent.py`

- `tests/agent/test_shell_hooks_consent.py::TestAllowlistOps::test_mtime_recorded_on_approval`
- `tests/agent/test_shell_hooks_consent.py::TestAllowlistOps::test_tilde_path_approval_records_resolvable_mtime`

### `tests/agent/test_skill_commands.py`

- `tests/agent/test_skill_commands.py::TestInlineShellExpansion::test_inline_shell_runs_in_skill_directory`
- `tests/agent/test_skill_commands.py::TestSkillDirectoryHeader::test_supporting_files_shown_with_absolute_paths`

### `tests/agent/test_subdirectory_hints.py`

- `tests/agent/test_subdirectory_hints.py::TestSubdirectoryHintTracker::test_terminal_cd_command`
- `tests/agent/test_subdirectory_hints.py::TestSubdirectoryHintTracker::test_terminal_command_path_extraction`

### `tests/cli/test_cli_browser_connect.py`

- `tests/cli/test_cli_browser_connect.py::TestChromeDebugLaunch::test_manual_command_uses_wsl_windows_chrome_when_available`

### `tests/cli/test_cli_file_drop.py`

- `tests/cli/test_cli_file_drop.py::TestEscapedSpaces::test_tilde_prefixed_path`

### `tests/cli/test_cli_image_command.py`

- `tests/cli/test_cli_image_command.py::TestCollectQueryImages::test_collect_query_images_supports_tilde_paths`
- `tests/cli/test_cli_image_command.py::TestTermuxImageHints::test_termux_example_image_path_prefers_real_shared_storage_root`

### `tests/cli/test_cli_secret_capture.py`

- `tests/cli/test_cli_secret_capture.py::test_secret_capture_callback_can_be_completed_from_cli_state_machine`
- `tests/cli/test_cli_secret_capture.py::test_secret_capture_timeout_clears_hidden_input_buffer`
- `tests/cli/test_cli_secret_capture.py::test_secret_capture_uses_masked_prompt_without_tui`

### `tests/cron/test_cron_workdir.py`

- `tests/cron/test_cron_workdir.py::TestNormalizeWorkdir::test_tilde_expands`

### `tests/cron/test_file_permissions.py`

- `tests/cron/test_file_permissions.py::TestConfigFilePermissions::test_ensure_hermes_home_sets_0700`
- `tests/cron/test_file_permissions.py::TestConfigFilePermissions::test_save_config_sets_0600`
- `tests/cron/test_file_permissions.py::TestConfigFilePermissions::test_save_env_value_sets_0600`
- `tests/cron/test_file_permissions.py::TestCronFilePermissions::test_ensure_dirs_sets_0700`
- `tests/cron/test_file_permissions.py::TestCronFilePermissions::test_save_job_output_sets_0600`
- `tests/cron/test_file_permissions.py::TestCronFilePermissions::test_save_jobs_sets_0600`

### `tests/cron/test_scheduler.py`

- `tests/cron/test_scheduler.py::TestDeliverResultWrapping::test_delivery_extracts_media_tags_before_send`
- `tests/cron/test_scheduler.py::TestDeliverResultWrapping::test_live_adapter_media_only_no_text`
- `tests/cron/test_scheduler.py::TestDeliverResultWrapping::test_live_adapter_routes_image_to_send_image_file`
- `tests/cron/test_scheduler.py::TestDeliverResultWrapping::test_live_adapter_sends_media_as_attachments`

### `tests/gateway/test_config_env_bridge_authority.py`

- `tests/gateway/test_config_env_bridge_authority.py::test_config_display_busy_input_mode_wins_over_stale_env`
- `tests/gateway/test_config_env_bridge_authority.py::test_config_display_busy_text_mode_wins_over_stale_env`
- `tests/gateway/test_config_env_bridge_authority.py::test_config_gateway_timeout_wins_over_stale_env`
- `tests/gateway/test_config_env_bridge_authority.py::test_config_max_turns_wins_over_stale_env`
- `tests/gateway/test_config_env_bridge_authority.py::test_config_timezone_wins_over_stale_env`
- `tests/gateway/test_config_env_bridge_authority.py::test_env_value_survives_when_config_omits_key`

### `tests/gateway/test_email.py`

- `tests/gateway/test_email.py::TestConfigEnvOverrides::test_email_not_loaded_without_env`

### `tests/gateway/test_feishu.py`

- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_send_animation_degrades_to_document_send`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_send_document_reply_uses_thread_flag`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_send_document_uploads_file_and_sends_file_message`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_send_document_with_caption_uses_single_post_message`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_send_does_not_retry_deterministic_api_failure`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_send_falls_back_to_text_when_post_payload_is_rejected`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_send_falls_back_to_text_when_post_response_is_unsuccessful`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_send_image_downloads_then_uses_native_image_send`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_send_image_file_uploads_image_and_sends_image_message`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_send_image_file_with_caption_uses_single_post_message`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_send_replies_in_thread_when_thread_metadata_present`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_send_retries_transient_failure`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_send_splits_fenced_code_blocks_into_separate_post_rows`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_send_uses_metadata_reply_target_for_threaded_feishu_topic`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_send_uses_post_for_advanced_markdown_lines`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_send_uses_post_for_inline_markdown`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_send_video_uploads_file_and_sends_media_message`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_send_voice_uploads_opus_and_sends_audio_message`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_text_batch_flushes_when_message_count_limit_is_hit`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_text_batch_merges_rapid_messages_into_single_event`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_url_verification_requires_configured_verification_token`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_user_reaction_with_managed_emoji_is_still_routed`
- `tests/gateway/test_feishu.py::TestAdapterBehavior::test_webhook_request_uses_same_message_dispatch_path`
- `tests/gateway/test_feishu.py::TestDedupTTL::test_duplicate_within_ttl_is_rejected`
- `tests/gateway/test_feishu.py::TestDedupTTL::test_expired_entry_is_not_considered_duplicate`
- `tests/gateway/test_feishu.py::TestDedupTTL::test_load_backward_compat_list_format`
- `tests/gateway/test_feishu.py::TestDedupTTL::test_persist_saves_timestamps_as_dict`
- `tests/gateway/test_feishu.py::TestGroupMentionAtAll::test_at_all_in_content_accepts_without_explicit_bot_mention`
- `tests/gateway/test_feishu.py::TestGroupMentionAtAll::test_at_all_still_requires_policy_gate`

### `tests/gateway/test_msgraph_webhook.py`

- `tests/gateway/test_msgraph_webhook.py::TestMSGraphNotifications::test_bad_client_state_rejected_as_auth_failure[trio]`
- `tests/gateway/test_msgraph_webhook.py::TestMSGraphNotifications::test_client_state_compare_is_timing_safe[trio]`
- `tests/gateway/test_msgraph_webhook.py::TestMSGraphNotifications::test_duplicate_notification_deduped[trio]`
- `tests/gateway/test_msgraph_webhook.py::TestMSGraphNotifications::test_notifications_without_id_are_not_deduped[trio]`
- `tests/gateway/test_msgraph_webhook.py::TestMSGraphNotifications::test_resource_patterns_accept_leading_slash[trio]`
- `tests/gateway/test_msgraph_webhook.py::TestMSGraphNotifications::test_seen_receipts_are_bounded[trio]`
- `tests/gateway/test_msgraph_webhook.py::TestMSGraphNotifications::test_valid_notification_accepted_and_scheduled[trio]`
- `tests/gateway/test_msgraph_webhook.py::TestMSGraphSourceIPAllowlist::test_disabled_by_default_allows_all[trio]`
- `tests/gateway/test_msgraph_webhook.py::TestMSGraphSourceIPAllowlist::test_post_from_allowed_ip_accepted[trio]`

### `tests/gateway/test_platform_base.py`

- `tests/gateway/test_platform_base.py::TestMediaDeliveryPathValidation::test_recency_trust_denies_system_paths_even_when_fresh`

### `tests/gateway/test_reasoning_command.py`

- `tests/gateway/test_reasoning_command.py::TestReasoningCommand::test_run_agent_homeassistant_uses_default_platform_toolset`

### `tests/gateway/test_restart_drain.py`

- `tests/gateway/test_restart_drain.py::test_launch_detached_restart_command_uses_setsid`

### `tests/gateway/test_runtime_footer.py`

- `tests/gateway/test_runtime_footer.py::test_format_footer_all_fields`
- `tests/gateway/test_runtime_footer.py::test_format_footer_skips_missing_context_length`
- `tests/gateway/test_runtime_footer.py::test_home_relative_cwd_collapses_home`
- `tests/gateway/test_runtime_footer.py::test_home_relative_cwd_leaves_abs_path_alone`

### `tests/gateway/test_setup_feishu.py`

- `tests/gateway/test_setup_feishu.py::TestSetupFeishuAdapterIntegration::test_group_open_env_sets_adapter_group_policy`
- `tests/gateway/test_setup_feishu.py::TestSetupFeishuAdapterIntegration::test_open_dm_env_sets_correct_adapter_state`
- `tests/gateway/test_setup_feishu.py::TestSetupFeishuAdapterIntegration::test_qr_env_produces_valid_adapter_settings`

### `tests/gateway/test_stream_consumer.py`

- `tests/gateway/test_stream_consumer.py::TestSegmentBreakOnToolBoundary::test_edit_failure_sends_only_unsent_tail_at_finish`

### `tests/gateway/test_stt_config.py`

- `tests/gateway/test_stt_config.py::test_enrich_message_with_transcription_omits_duration_on_probe_failure`
- `tests/gateway/test_stt_config.py::test_enrich_message_with_transcription_surfaces_path_when_stt_disabled`

### `tests/gateway/test_tts_media_routing.py`

- `tests/gateway/test_tts_media_routing.py::test_base_adapter_routes_non_voice_telegram_ogg_media_tag_to_document_sender`
- `tests/gateway/test_tts_media_routing.py::test_base_adapter_routes_telegram_flac_media_tag_to_document_sender`
- `tests/gateway/test_tts_media_routing.py::test_base_adapter_routes_voice_tagged_telegram_ogg_media_tag_to_voice_sender`
- `tests/gateway/test_tts_media_routing.py::test_streaming_delivery_routes_non_voice_telegram_ogg_media_tag_to_document_sender`
- `tests/gateway/test_tts_media_routing.py::test_streaming_delivery_routes_telegram_flac_media_tag_to_document_sender`
- `tests/gateway/test_tts_media_routing.py::test_streaming_delivery_routes_telegram_mp3_media_tag_to_voice_sender`

### `tests/gateway/test_update_command.py`

- `tests/gateway/test_update_command.py::TestHandleUpdateCommand::test_fallback_when_no_setsid`
- `tests/gateway/test_update_command.py::TestHandleUpdateCommand::test_spawns_setsid`

### `tests/gateway/test_update_streaming.py`

- `tests/gateway/test_update_streaming.py::TestUpdateCommandGatewayFlag::test_spawns_with_gateway_flag`

### `tests/hermes_cli/test_atomic_json_write.py`

- `tests/hermes_cli/test_atomic_json_write.py::TestAtomicJsonWrite::test_concurrent_writes_dont_corrupt`

### `tests/hermes_cli/test_auth_nous_provider.py`

- `tests/hermes_cli/test_auth_nous_provider.py::test_shared_store_write_and_read_roundtrip`

### `tests/hermes_cli/test_auth_qwen_provider.py`

- `tests/hermes_cli/test_auth_qwen_provider.py::test_save_qwen_cli_tokens_permissions`

### `tests/hermes_cli/test_banner.py`

- `tests/hermes_cli/test_banner.py::test_build_welcome_banner_title_is_hyperlinked_to_release`

### `tests/hermes_cli/test_container_boot.py`

- `tests/hermes_cli/test_container_boot.py::test_corrupt_state_file_treated_as_no_prior_state`
- `tests/hermes_cli/test_container_boot.py::test_default_slot_always_registered_on_empty_home`
- `tests/hermes_cli/test_container_boot.py::test_default_slot_appears_before_named_profiles`
- `tests/hermes_cli/test_container_boot.py::test_default_slot_autostarts_when_root_state_running`
- `tests/hermes_cli/test_container_boot.py::test_default_slot_cleans_up_stale_runtime_files_at_root`
- `tests/hermes_cli/test_container_boot.py::test_default_slot_does_not_autostart_when_root_state_startup_failed`
- `tests/hermes_cli/test_container_boot.py::test_default_slot_does_not_autostart_when_root_state_stopped`
- `tests/hermes_cli/test_container_boot.py::test_default_slot_run_script_omits_profile_flag`
- `tests/hermes_cli/test_container_boot.py::test_directory_without_marker_file_is_skipped`
- `tests/hermes_cli/test_container_boot.py::test_invalid_profile_name_in_directory_raises`
- `tests/hermes_cli/test_container_boot.py::test_missing_profiles_root_still_registers_default_slot`
- `tests/hermes_cli/test_container_boot.py::test_profile_without_state_file_is_registered_but_not_started`
- `tests/hermes_cli/test_container_boot.py::test_profiles_default_subdir_is_skipped_with_warning`
- `tests/hermes_cli/test_container_boot.py::test_reconcile_log_does_not_rotate_below_threshold`
- `tests/hermes_cli/test_container_boot.py::test_reconcile_log_is_written`
- `tests/hermes_cli/test_container_boot.py::test_reconcile_log_rotates_when_size_exceeded`
- `tests/hermes_cli/test_container_boot.py::test_reconcile_log_rotation_overwrites_existing_dot1`
- `tests/hermes_cli/test_container_boot.py::test_register_service_cleans_up_stale_tmp_dir`
- `tests/hermes_cli/test_container_boot.py::test_register_service_overwrites_existing_slot`
- `tests/hermes_cli/test_container_boot.py::test_register_service_publishes_atomically`
- `tests/hermes_cli/test_container_boot.py::test_running_profile_is_registered_and_autostarted`
- `tests/hermes_cli/test_container_boot.py::test_stale_runtime_files_are_removed`
- `tests/hermes_cli/test_container_boot.py::test_starting_state_does_not_autostart`
- `tests/hermes_cli/test_container_boot.py::test_startup_failed_does_not_autostart`
- `tests/hermes_cli/test_container_boot.py::test_stopped_profile_is_registered_but_not_started`

### `tests/hermes_cli/test_curses_color_compat.py`

- `tests/hermes_cli/test_curses_color_compat.py`

### `tests/hermes_cli/test_debug.py`

- `tests/hermes_cli/test_debug.py::TestCaptureLogSnapshot::test_keeps_first_line_when_truncation_on_boundary`

### `tests/hermes_cli/test_gateway.py`

- `tests/hermes_cli/test_gateway.py::test_install_linux_gateway_from_setup_system_choice_as_root_installs`
- `tests/hermes_cli/test_gateway.py::test_install_linux_gateway_from_setup_system_choice_without_root_prints_followup`
- `tests/hermes_cli/test_gateway.py::test_run_gateway_refuses_root_in_official_docker`
- `tests/hermes_cli/test_gateway.py::test_run_gateway_root_guard_has_escape_hatch`
- `tests/hermes_cli/test_gateway.py::test_systemd_install_checks_linger_status`
- `tests/hermes_cli/test_gateway.py::test_systemd_status_warns_when_linger_disabled`

### `tests/hermes_cli/test_gateway_linger.py`

- `tests/hermes_cli/test_gateway_linger.py::test_systemd_install_calls_linger_helper`

### `tests/hermes_cli/test_gateway_wsl.py`

- `tests/hermes_cli/test_gateway_wsl.py::TestGatewayCommandWSLMessages::test_install_wsl_no_systemd`
- `tests/hermes_cli/test_gateway_wsl.py::TestGatewayCommandWSLMessages::test_start_wsl_no_systemd`
- `tests/hermes_cli/test_gateway_wsl.py::TestSupportsSystemdServicesWSL::test_native_linux`
- `tests/hermes_cli/test_gateway_wsl.py::TestSupportsSystemdServicesWSL::test_wsl_with_systemd`

### `tests/hermes_cli/test_hooks_cli.py`

- `tests/hermes_cli/test_hooks_cli.py::TestHooksDoctor::test_clean_script_runs`
- `tests/hermes_cli/test_hooks_cli.py::TestHooksDoctor::test_flags_invalid_json`
- `tests/hermes_cli/test_hooks_cli.py::TestHooksDoctor::test_flags_mtime_drift`
- `tests/hermes_cli/test_hooks_cli.py::TestHooksTest::test_fires_real_subprocess_and_parses_block`
- `tests/hermes_cli/test_hooks_cli.py::TestHooksTest::test_synthetic_payload_matches_production_shape`

### `tests/hermes_cli/test_kanban_core_functionality.py`

- `tests/hermes_cli/test_kanban_core_functionality.py::test_detect_crashed_workers_protocol_violation_auto_blocks`

### `tests/hermes_cli/test_kanban_db.py`

- `tests/hermes_cli/test_kanban_db.py::test_resolve_hermes_argv_hermes_bin_bare_name_uses_path`
- `tests/hermes_cli/test_kanban_db.py::test_resolve_hermes_argv_prefers_path_shim`

### `tests/hermes_cli/test_model_catalog.py`

- `tests/hermes_cli/test_model_catalog.py::TestManifestMatchesInRepoLists::test_in_repo_lists_match_manifest`

### `tests/hermes_cli/test_path_completion.py`

- `tests/hermes_cli/test_path_completion.py::TestIntegration::test_absolute_path_triggers_completion`
- `tests/hermes_cli/test_path_completion.py::TestPathCompletions::test_home_expansion`

### `tests/hermes_cli/test_plugins_cmd.py`

- `tests/hermes_cli/test_plugins_cmd.py::TestCursesRadiolist::test_keyboard_interrupt_returns_cancel_value`

### `tests/hermes_cli/test_relaunch.py`

- `tests/hermes_cli/test_relaunch.py::TestRelaunch::test_calls_execvp`

### `tests/hermes_cli/test_service_manager.py`

- `tests/hermes_cli/test_service_manager.py::test_s6_register_creates_service_dir_and_triggers_scan`
- `tests/hermes_cli/test_service_manager.py::test_s6_register_extra_env_is_quoted`
- `tests/hermes_cli/test_service_manager.py::test_s6_register_rolls_back_on_svscanctl_failure`
- `tests/hermes_cli/test_service_manager.py::test_s6_running_true_when_comm_and_basedir_match`
- `tests/hermes_cli/test_service_manager.py::test_seed_supervise_skeleton_creates_expected_layout`
- `tests/hermes_cli/test_service_manager.py::test_seed_supervise_skeleton_handles_log_subservice`
- `tests/hermes_cli/test_service_manager.py::test_seed_supervise_skeleton_is_idempotent`
- `tests/hermes_cli/test_service_manager.py::test_seed_supervise_skeleton_skips_when_no_log_subservice`

### `tests/hermes_cli/test_session_browse.py`

- `tests/hermes_cli/test_session_browse.py::TestCursesBrowse::test_backspace_removes_filter_char`
- `tests/hermes_cli/test_session_browse.py::TestCursesBrowse::test_down_down_enter_selects_third`
- `tests/hermes_cli/test_session_browse.py::TestCursesBrowse::test_down_then_enter_selects_second`
- `tests/hermes_cli/test_session_browse.py::TestCursesBrowse::test_enter_selects_first_session`
- `tests/hermes_cli/test_session_browse.py::TestCursesBrowse::test_escape_cancels`
- `tests/hermes_cli/test_session_browse.py::TestCursesBrowse::test_escape_clears_filter_first`
- `tests/hermes_cli/test_session_browse.py::TestCursesBrowse::test_filter_matches_preview`
- `tests/hermes_cli/test_session_browse.py::TestCursesBrowse::test_filter_matches_source`
- `tests/hermes_cli/test_session_browse.py::TestCursesBrowse::test_filter_no_match_enter_does_nothing`
- `tests/hermes_cli/test_session_browse.py::TestCursesBrowse::test_q_cancels`
- `tests/hermes_cli/test_session_browse.py::TestCursesBrowse::test_q_quits_when_no_filter_active`
- `tests/hermes_cli/test_session_browse.py::TestCursesBrowse::test_q_types_into_filter_when_filter_active`
- `tests/hermes_cli/test_session_browse.py::TestCursesBrowse::test_type_to_filter_then_enter`
- `tests/hermes_cli/test_session_browse.py::TestCursesBrowse::test_up_wraps_to_last`

### `tests/hermes_cli/test_setup.py`

- `tests/hermes_cli/test_setup.py::test_setup_gateway_in_container_shows_docker_guidance`
- `tests/hermes_cli/test_setup.py::test_setup_gateway_skips_service_install_when_systemctl_missing`

### `tests/hermes_cli/test_setup_openclaw_migration.py`

- `tests/hermes_cli/test_setup_openclaw_migration.py::TestGetSectionConfigSummary::test_gateway_matches_platform_registry`

### `tests/hermes_cli/test_tools_config.py`

- `tests/hermes_cli/test_tools_config.py::test_apply_toolset_change_can_enable_default_off_toolset_from_default`
- `tests/hermes_cli/test_tools_config.py::test_apply_toolset_change_from_default_does_not_enable_default_off_toolsets`
- `tests/hermes_cli/test_tools_config.py::test_get_platform_tools_default_telegram_includes_messaging`
- `tests/hermes_cli/test_tools_config.py::test_get_platform_tools_default_whatsapp_includes_web`
- `tests/hermes_cli/test_tools_config.py::test_get_platform_tools_expands_composite_when_mixed_with_configurable`
- `tests/hermes_cli/test_tools_config.py::test_get_platform_tools_feishu_includes_doc_and_drive`
- `tests/hermes_cli/test_tools_config.py::test_get_platform_tools_homeassistant_platform_keeps_homeassistant_toolset`
- `tests/hermes_cli/test_tools_config.py::test_get_platform_tools_homeassistant_toolset_enabled_for_cron_when_hass_token_set`
- `tests/hermes_cli/test_tools_config.py::test_get_platform_tools_includes_enabled_mcp_servers_by_default`
- `tests/hermes_cli/test_tools_config.py::test_get_platform_tools_mixed_does_not_resurrect_default_off`
- `tests/hermes_cli/test_tools_config.py::test_get_platform_tools_no_mcp_sentinel_does_not_affect_other_platforms`
- `tests/hermes_cli/test_tools_config.py::test_get_platform_tools_recovers_non_configurable_toolsets_from_composite`
- `tests/hermes_cli/test_tools_config.py::test_get_platform_tools_x_search_auto_enabled_when_xai_api_key_present`
- `tests/hermes_cli/test_tools_config.py::test_get_platform_tools_x_search_auto_enabled_when_xai_oauth_present`
- `tests/hermes_cli/test_tools_config.py::test_get_platform_tools_x_search_respects_explicit_config`

### `tests/hermes_cli/test_update_post_pull_syntax_guard.py`

- `tests/hermes_cli/test_update_post_pull_syntax_guard.py::test_validate_critical_files_syntax_detects_break_in_main_py`
- `tests/hermes_cli/test_update_post_pull_syntax_guard.py::test_validate_critical_files_syntax_detects_conflict_markers`

### `tests/hermes_cli/test_update_stale_dashboard.py`

- `tests/hermes_cli/test_update_stale_dashboard.py::TestFindStaleDashboardPids::test_grep_lines_ignored`
- `tests/hermes_cli/test_update_stale_dashboard.py::TestFindStaleDashboardPids::test_invalid_pid_lines_skipped`
- `tests/hermes_cli/test_update_stale_dashboard.py::TestFindStaleDashboardPids::test_matches_running_dashboard`
- `tests/hermes_cli/test_update_stale_dashboard.py::TestFindStaleDashboardPids::test_multiple_matches`
- `tests/hermes_cli/test_update_stale_dashboard.py::TestFindStaleDashboardPids::test_self_pid_excluded`
- `tests/hermes_cli/test_update_stale_dashboard.py::TestFindStaleDashboardPids::test_unrelated_process_containing_word_dashboard_not_matched`

### `tests/hermes_cli/test_web_server_oauth_write.py`

- `tests/hermes_cli/test_web_server_oauth_write.py::test_dashboard_oauth_write_uses_owner_only_permissions`

### `tests/plugins/image_gen/test_openai_provider.py`

- `tests/plugins/image_gen/test_openai_provider.py::TestGenerate::test_url_response_is_cached_locally`

### `tests/plugins/image_gen/test_xai_provider.py`

- `tests/plugins/image_gen/test_xai_provider.py::TestGenerate::test_successful_url_response`

### `tests/plugins/memory/test_hindsight_provider.py`

- `tests/plugins/memory/test_hindsight_provider.py::TestPostSetup::test_local_embedded_setup_materializes_profile_env`
- `tests/plugins/memory/test_hindsight_provider.py::TestPostSetup::test_local_embedded_setup_preserves_existing_key_when_input_left_blank`
- `tests/plugins/memory/test_hindsight_provider.py::TestPostSetup::test_local_embedded_setup_respects_existing_profile_name`

### `tests/plugins/test_disk_cleanup_plugin.py`

- `tests/plugins/test_disk_cleanup_plugin.py::TestPostToolCallHook::test_terminal_command_picks_up_paths`

### `tests/plugins/test_teams_pipeline_plugin.py`

- `tests/plugins/test_teams_pipeline_plugin.py::TestTeamsMeetingPipeline::test_missing_transcript_and_recording_schedules_retry[trio]`
- `tests/plugins/test_teams_pipeline_plugin.py::TestTeamsMeetingPipeline::test_recording_fallback_uses_stt_and_updates_sink_records[trio]`

### `tests/product/test_product_positioning.py`

- `tests/product/test_product_positioning.py::test_readme_uses_the_canonical_product_promise_and_segments`

### `tests/run_agent/test_860_dedup.py`

- `tests/run_agent/test_860_dedup.py::TestFlushDeduplication::test_flush_reset_after_compression`
- `tests/run_agent/test_860_dedup.py::TestFlushDeduplication::test_flush_writes_incrementally`
- `tests/run_agent/test_860_dedup.py::TestFlushDeduplication::test_flush_writes_only_new_messages`
- `tests/run_agent/test_860_dedup.py::TestFlushDeduplication::test_persist_session_multiple_calls_no_duplication`

### `tests/run_agent/test_compression_boundary_hook.py`

- `tests/run_agent/test_compression_boundary_hook.py::TestCompressionBoundaryHook::test_hook_failure_does_not_break_compression`
- `tests/run_agent/test_compression_boundary_hook.py::TestCompressionBoundaryHook::test_on_session_start_called_with_compression_boundary`

### `tests/run_agent/test_compression_persistence.py`

- `tests/run_agent/test_compression_persistence.py::TestFlushAfterCompression::test_flush_after_compression_with_long_history`
- `tests/run_agent/test_compression_persistence.py::TestFlushAfterCompression::test_flush_with_stale_history_loses_messages`

### `tests/run_agent/test_real_interrupt_subagent.py`

- `tests/run_agent/test_real_interrupt_subagent.py::TestRealSubagentInterrupt::test_interrupt_child_during_api_call`

### `tests/skills/test_google_oauth_setup.py`

- `tests/skills/test_google_oauth_setup.py::TestHermesConstantsFallback::test_fallback_display_hermes_home_custom_path`
- `tests/skills/test_google_oauth_setup.py::TestHermesConstantsFallback::test_fallback_display_hermes_home_profile_path`

### `tests/skills/test_openclaw_migration.py`

- `tests/skills/test_openclaw_migration.py::test_cron_store_is_archived_without_config_cron_section`
- `tests/skills/test_openclaw_migration.py::test_migrator_can_overwrite_conflicting_imported_skill_with_backup`
- `tests/skills/test_openclaw_migration.py::test_migrator_can_rename_conflicting_imported_skill`

### `tests/test_bitwarden_secrets.py`

- `tests/test_bitwarden_secrets.py::test_disk_cache_written_after_first_fetch`
- `tests/test_bitwarden_secrets.py::test_install_bws_happy_path`

### `tests/test_hermes_logging.py`

- `tests/test_hermes_logging.py::TestAddRotatingHandler::test_managed_mode_initial_open_sets_group_writable`
- `tests/test_hermes_logging.py::TestAddRotatingHandler::test_managed_mode_rollover_sets_group_writable`

### `tests/test_install_sh_symlink_stomp.py`

- `tests/test_install_sh_symlink_stomp.py::test_re_running_setup_path_block_preserves_pip_entry_point`

### `tests/test_live_system_guard_self_test.py`

- `tests/test_live_system_guard_self_test.py::test_kill_own_subtree_passes_through`
- `tests/test_live_system_guard_self_test.py::test_os_kill_blocks_foreign_pid`
- `tests/test_live_system_guard_self_test.py::test_pty_spawn_systemctl_blocked`
- `tests/test_live_system_guard_self_test.py::test_systemctl_list_units_passes_through`
- `tests/test_live_system_guard_self_test.py::test_systemctl_show_passes_through`
- `tests/test_live_system_guard_self_test.py::test_systemctl_status_passes_through`
- `tests/test_live_system_guard_self_test.py::test_systemctl_unrelated_unit_passes_through`

### `tests/test_model_tools.py`

- `tests/test_model_tools.py::TestHandleFunctionCall::test_exception_returns_json_error`
- `tests/test_model_tools.py::TestHandleFunctionCall::test_tool_hooks_receive_session_and_tool_call_ids`

### `tests/test_subprocess_home_isolation.py`

- `tests/test_subprocess_home_isolation.py::TestGetSubprocessHome::test_two_profiles_get_different_homes`

### `tests/test_toolsets.py`

- `tests/test_toolsets.py::TestGetToolset::test_merges_registry_tools_into_builtin_toolset`
- `tests/test_toolsets.py::TestGetToolsetInfo::test_leaf`
- `tests/test_toolsets.py::TestResolveToolset::test_leaf_toolset`

### `tests/test_transform_tool_result_hook.py`

- `tests/test_transform_tool_result_hook.py::test_hook_receives_expected_kwargs`

### `tests/tools/test_browser_homebrew_paths.py`

- `tests/tools/test_browser_homebrew_paths.py::TestDiscoverHomebrewNodeDirs::test_finds_versioned_node_dirs`
- `tests/tools/test_browser_homebrew_paths.py::TestRunBrowserCommandPathConstruction::test_subprocess_path_includes_homebrew_node_dirs`
- `tests/tools/test_browser_homebrew_paths.py::TestRunBrowserCommandPathConstruction::test_subprocess_path_includes_sane_path_homebrew`
- `tests/tools/test_browser_homebrew_paths.py::TestRunBrowserCommandPathConstruction::test_subprocess_path_includes_termux_fallback_dirs`

### `tests/tools/test_checkpoint_manager.py`

- `tests/tools/test_checkpoint_manager.py::TestClearFunctions::test_clear_all_wipes_base`
- `tests/tools/test_checkpoint_manager.py::TestGitEnvIsolation::test_sets_index_file_when_provided`
- `tests/tools/test_checkpoint_manager.py::TestWorkingDirResolution::test_falls_back_to_parent`

### `tests/tools/test_credential_files.py`

- `tests/tools/test_credential_files.py::TestIterCacheFiles::test_nested_files`
- `tests/tools/test_credential_files.py::TestIterSkillsFiles::test_returns_files_skipping_symlinks`

### `tests/tools/test_docker_find.py`

- `tests/tools/test_docker_find.py::TestFindDocker::test_env_var_override_ignored_if_not_executable`

### `tests/tools/test_file_operations.py`

- `tests/tools/test_file_operations.py::TestSearchFilesFallbackHiddenPaths::test_hidden_root_with_hidden_ancestor_includes_files`
- `tests/tools/test_file_operations.py::TestSearchFilesFallbackHiddenPaths::test_normal_root_still_excludes_hidden_descendants`

### `tests/tools/test_file_tools_live.py`

- `tests/tools/test_file_tools_live.py::TestExpandPath::test_bare_tilde`
- `tests/tools/test_file_tools_live.py::TestExpandPath::test_tilde_exact`
- `tests/tools/test_file_tools_live.py::TestLocalEnvironmentExecute::test_cat_deterministic_content`
- `tests/tools/test_file_tools_live.py::TestLocalEnvironmentExecute::test_cwd_respected`
- `tests/tools/test_file_tools_live.py::TestLocalEnvironmentExecute::test_env_var_home`
- `tests/tools/test_file_tools_live.py::TestTerminalOutputCleanliness::test_cat`
- `tests/tools/test_file_tools_live.py::TestTerminalOutputCleanliness::test_env_var_expansion`
- `tests/tools/test_file_tools_live.py::TestTerminalOutputCleanliness::test_head`
- `tests/tools/test_file_tools_live.py::TestTerminalOutputCleanliness::test_ls`
- `tests/tools/test_file_tools_live.py::TestTerminalOutputCleanliness::test_wc`

### `tests/tools/test_file_write_safety.py`

- `tests/tools/test_file_write_safety.py::TestCheckSensitivePathMacOSBypass::test_boot_still_blocked`
- `tests/tools/test_file_write_safety.py::TestCheckSensitivePathMacOSBypass::test_etc_hosts_blocked`
- `tests/tools/test_file_write_safety.py::TestCheckSensitivePathMacOSBypass::test_private_etc_hosts_blocked`
- `tests/tools/test_file_write_safety.py::TestCheckSensitivePathMacOSBypass::test_private_etc_ssh_config_blocked`
- `tests/tools/test_file_write_safety.py::TestCheckSensitivePathMacOSBypass::test_private_var_blocked`

### `tests/tools/test_kanban_codex_lane_skill.py`

- `tests/tools/test_kanban_codex_lane_skill.py::test_kanban_codex_lane_skill_is_discoverable_with_template`

### `tests/tools/test_local_background_child_hang.py`

- `tests/tools/test_local_background_child_hang.py::TestBackgroundChildDoesNotHang::test_invalid_utf8_uses_replacement_not_fallback`
- `tests/tools/test_local_background_child_hang.py::TestBackgroundChildDoesNotHang::test_timeout_path_still_works`
- `tests/tools/test_local_background_child_hang.py::TestBackgroundChildDoesNotHang::test_utf8_multibyte_across_read_boundary`

### `tests/tools/test_local_env_blocklist.py`

- `tests/tools/test_local_env_blocklist.py::TestSanePathIncludesHomebrew::test_make_run_env_appends_homebrew_on_minimal_path`

### `tests/tools/test_local_env_cwd_recovery.py`

- `tests/tools/test_local_env_cwd_recovery.py::TestResolveSafeCwd::test_returns_root_when_only_root_exists`

### `tests/tools/test_local_interrupt_cleanup.py`

- `tests/tools/test_local_interrupt_cleanup.py::test_kill_process_uses_cached_pgid_if_wrapper_already_exited`
- `tests/tools/test_local_interrupt_cleanup.py::test_wait_for_process_kills_subprocess_on_keyboardinterrupt`

### `tests/tools/test_local_shell_init.py`

- `tests/tools/test_local_shell_init.py::TestResolveShellInitFiles::test_auto_sources_bash_profile_when_present`
- `tests/tools/test_local_shell_init.py::TestResolveShellInitFiles::test_auto_sources_bashrc_when_present`
- `tests/tools/test_local_shell_init.py::TestResolveShellInitFiles::test_auto_sources_profile_before_bashrc`
- `tests/tools/test_local_shell_init.py::TestResolveShellInitFiles::test_auto_sources_profile_when_present`
- `tests/tools/test_local_shell_init.py::TestResolveShellInitFiles::test_expands_home_and_env_vars`

### `tests/tools/test_local_tempdir.py`

- `tests/tools/test_local_tempdir.py::TestLocalTempDir::test_falls_back_to_tempfile_when_tmp_missing`
- `tests/tools/test_local_tempdir.py::TestLocalTempDir::test_prefers_backend_env_tmpdir_override`
- `tests/tools/test_local_tempdir.py::TestLocalTempDir::test_uses_os_tmpdir_for_session_artifacts`

### `tests/tools/test_microsoft_graph_auth.py`

- `tests/tools/test_microsoft_graph_auth.py::TestMicrosoftGraphTokenProvider::test_concurrent_calls_share_one_token_fetch[trio]`

### `tests/tools/test_modal_bulk_upload.py`

- `tests/tools/test_modal_bulk_upload.py::TestModalBulkUpload::test_mkdir_includes_all_parents`

### `tests/tools/test_modal_sandbox_fixes.py`

- `tests/tools/test_modal_sandbox_fixes.py::TestCwdHandling::test_docker_default_cwd_maps_current_directory_when_enabled`
- `tests/tools/test_modal_sandbox_fixes.py::TestCwdHandling::test_users_path_maps_to_workspace_for_docker_when_enabled`

### `tests/tools/test_pr_6656_regressions.py`

- `tests/tools/test_pr_6656_regressions.py::TestBundleHashFilenameSensitivity::test_bundle_and_disk_hash_match`

### `tests/tools/test_process_registry.py`

- `tests/tools/test_process_registry.py::TestKillProcess::test_kill_detached_session_uses_host_pid`
- `tests/tools/test_process_registry.py::TestStdinHelpers::test_close_stdin_allows_eof_driven_process_to_finish`

### `tests/tools/test_skills_hub.py`

- `tests/tools/test_skills_hub.py::TestCheckForSkillUpdates::test_bundle_content_hash_matches_installed_content_hash`
- `tests/tools/test_skills_hub.py::TestCheckForSkillUpdates::test_bundle_content_hash_mixed_matches_on_disk`
- `tests/tools/test_skills_hub.py::TestOptionalSkillSourceBinaryAssets::test_fetch_preserves_binary_assets`

### `tests/tools/test_skills_tool.py`

- `tests/tools/test_skills_tool.py::TestSkillViewCollisionDetection::test_nested_local_collides_with_top_level_external`

### `tests/tools/test_ssh_bulk_upload.py`

- `tests/tools/test_ssh_bulk_upload.py::TestSSHBulkUpload::test_mkdir_batched_into_single_call`
- `tests/tools/test_ssh_bulk_upload.py::TestSSHBulkUpload::test_parent_dirs_deduplicated`
- `tests/tools/test_ssh_bulk_upload.py::TestSSHBulkUpload::test_staging_symlinks_mirror_remote_layout`
- `tests/tools/test_ssh_bulk_upload.py::TestSharedHelpers::test_unique_parent_dirs_deduplicates`
- `tests/tools/test_ssh_bulk_upload.py::TestSharedHelpers::test_unique_parent_dirs_sorted`

### `tests/tools/test_tirith_security.py`

- `tests/tools/test_tirith_security.py::TestAppTldSuppression::test_block_verdict_never_suppressed`
- `tests/tools/test_tirith_security.py::TestAppTldSuppression::test_mixed_findings_preserve_warn`
- `tests/tools/test_tirith_security.py::TestAppTldSuppression::test_non_app_lookalike_tld_preserved`
- `tests/tools/test_tirith_security.py::TestBackgroundInstall::test_ensure_installed_non_blocking`
- `tests/tools/test_tirith_security.py::TestBackgroundInstall::test_ensure_installed_skips_on_disk_marker`
- `tests/tools/test_tirith_security.py::TestCaps::test_findings_capped_at_50`
- `tests/tools/test_tirith_security.py::TestCaps::test_summary_capped_at_500`
- `tests/tools/test_tirith_security.py::TestDiskFailureMarker::test_cosign_missing_disk_marker_allows_retry`
- `tests/tools/test_tirith_security.py::TestDiskFailureMarker::test_disk_marker_reason_preserved_in_memory`
- `tests/tools/test_tirith_security.py::TestDiskFailureMarker::test_in_memory_cosign_missing_retries_when_cosign_appears`
- `tests/tools/test_tirith_security.py::TestDiskFailureMarker::test_install_failed_recovers_from_hermes_bin`
- `tests/tools/test_tirith_security.py::TestDiskFailureMarker::test_install_failed_still_checks_local_paths`
- `tests/tools/test_tirith_security.py::TestDiskFailureMarker::test_sync_resolve_clears_marker_on_success`
- `tests/tools/test_tirith_security.py::TestDiskFailureMarker::test_sync_resolve_persists_failure`
- `tests/tools/test_tirith_security.py::TestDiskFailureMarker::test_sync_resolve_skips_install_on_disk_marker`
- `tests/tools/test_tirith_security.py::TestEnsureInstalled::test_found_on_path_returns_immediately`
- `tests/tools/test_tirith_security.py::TestEnsureInstalled::test_not_found_returns_none`
- `tests/tools/test_tirith_security.py::TestEnsureInstalled::test_startup_prefetch_can_suppress_install_failure_logs`
- `tests/tools/test_tirith_security.py::TestExitCodeMapping::test_exit_1_block_with_findings`
- `tests/tools/test_tirith_security.py::TestExitCodeMapping::test_exit_2_warn_with_findings`
- `tests/tools/test_tirith_security.py::TestExplicitPathNoAutoDownload::test_default_path_does_auto_download`
- `tests/tools/test_tirith_security.py::TestFailedDownloadCaching::test_failed_install_cached_no_retry`
- `tests/tools/test_tirith_security.py::TestFailedDownloadCaching::test_failed_install_scan_uses_fail_open`
- `tests/tools/test_tirith_security.py::TestHermesHomeIsolation::test_failure_marker_respects_hermes_home`
- `tests/tools/test_tirith_security.py::TestHermesHomeIsolation::test_get_hermes_home_fallback`
- `tests/tools/test_tirith_security.py::TestJsonParseFailure::test_exit_1_invalid_json_still_blocks`
- `tests/tools/test_tirith_security.py::TestJsonParseFailure::test_exit_2_invalid_json_still_warns`
- `tests/tools/test_tirith_security.py::TestOSErrorFailOpen::test_file_not_found_fail_open`
- `tests/tools/test_tirith_security.py::TestOSErrorFailOpen::test_os_error_fail_closed`
- `tests/tools/test_tirith_security.py::TestOSErrorFailOpen::test_permission_error_fail_open`
- `tests/tools/test_tirith_security.py::TestProgrammingErrors::test_attribute_error_propagates`
- `tests/tools/test_tirith_security.py::TestProgrammingErrors::test_type_error_propagates`
- `tests/tools/test_tirith_security.py::TestSpawnWarningDedup::test_distinct_exception_types_each_log_once`
- `tests/tools/test_tirith_security.py::TestSpawnWarningDedup::test_path_none_logs_once`
- `tests/tools/test_tirith_security.py::TestSpawnWarningDedup::test_repeated_spawn_failure_logs_once`
- `tests/tools/test_tirith_security.py::TestSpawnWarningDedup::test_repeated_timeout_logs_once`
- `tests/tools/test_tirith_security.py::TestTimeoutFailOpen::test_timeout_fail_closed`
- `tests/tools/test_tirith_security.py::TestTimeoutFailOpen::test_timeout_fail_open`
- `tests/tools/test_tirith_security.py::TestUnknownExitCode::test_unknown_exit_code_fail_closed`
- `tests/tools/test_tirith_security.py::TestUnknownExitCode::test_unknown_exit_code_fail_open`

### `tests/tools/test_vercel_sandbox_environment.py`

- `tests/tools/test_vercel_sandbox_environment.py::TestFileSync::test_cleanup_syncs_back_snapshots_closes_and_is_idempotent`

### `tests/tools/test_vision_tools.py`

- `tests/tools/test_vision_tools.py::TestTildeExpansion::test_tilde_path_expanded_to_local_file`

### `tests/tools/test_web_providers.py`

- `tests/tools/test_web_providers.py::TestUnconfiguredErrorEnvelopeParity::test_unconfigured_crawl_emits_top_level_error`
- `tests/tools/test_web_providers.py::TestUnconfiguredErrorEnvelopeParity::test_unconfigured_search_emits_top_level_error`

### `tests/tools/test_web_providers_searxng.py`

- `tests/tools/test_web_providers_searxng.py::TestCheckWebApiKey::test_no_credentials_fails`

### `tests/tools/test_web_tools_config.py`

- `tests/tools/test_web_tools_config.py::TestBackendSelection::test_fallback_no_keys_defaults_to_firecrawl`
- `tests/tools/test_web_tools_config.py::TestCheckWebApiKey::test_no_keys_returns_false`

### `tests/tools/test_windows_native_support.py`

- `tests/tools/test_windows_native_support.py::TestConfigureWindowsStdio::test_no_op_on_posix`
- `tests/tools/test_windows_native_support.py::TestReadmeNoLongerSaysWindowsUnsupported::test_readme_mentions_powershell_installer`
- `tests/tools/test_windows_native_support.py::TestSigkillFallback::test_getattr_fallback_prefers_sigkill_when_present`

### `tests/tools/test_zombie_process_cleanup.py`

- `tests/tools/test_zombie_process_cleanup.py::TestZombieReproduction::test_orphaned_processes_survive_without_cleanup`
