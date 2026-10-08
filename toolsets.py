#!/usr/bin/env python3
"""
Toolsets Module

This module provides a flexible system for defining and managing tool aliases/toolsets.
Toolsets allow you to group tools together for specific scenarios and can be composed
from individual tools or other toolsets.

Features:
- Define custom toolsets with specific tools
- Compose toolsets from other toolsets
- Built-in common toolsets for typical use cases
- Easy extension for new toolsets
- Support for dynamic toolset resolution

Usage:
    from toolsets import get_toolset, resolve_toolset, get_all_toolsets
    
    # Get tools for a specific toolset
    tools = get_toolset("research")
    
    # Resolve a toolset to get all tool names (including from composed toolsets)
    all_tools = resolve_toolset("full_stack")
"""

from typing import List, Dict, Any, Set, Optional


# Shared tool list for CLI and all messaging platform toolsets.
# Edit this once to update all platforms simultaneously.
_HERMES_CORE_TOOLS = [
    # Web
    "web_search", "web_extract", "web_research",
    # Terminal + process management
    "terminal", "process",
    # File manipulation
    "read_file", "write_file", "patch", "search_files",
    # Vision + image generation
    "vision_analyze", "image_generate",
    # Skills
    "skills_list", "skill_view", "skill_manage",
    # Browser automation
    "browser_navigate", "browser_snapshot", "browser_click",
    "browser_type", "browser_scroll", "browser_back",
    "browser_press", "browser_get_images",
    "browser_vision", "browser_console", "browser_cdp", "browser_dialog",
    # Text-to-speech
    "text_to_speech",
    # Planning & memory
    "todo", "memory",
    # Session history search
    "session_search",
    # Clarifying questions
    "clarify",
    # Code execution + delegation
    "execute_code", "delegate_task",
    # Cronjob management
    "cronjob",
    # Cross-platform messaging (gated on gateway running via check_fn)
    "send_message",
    # Отправка Мише в его личный Telegram (текст/файл) — «отправь мне в тг»
    "telegram_send",
    # Home Assistant smart home control (gated on HASS_TOKEN via check_fn)
    "ha_list_entities", "ha_get_state", "ha_list_services", "ha_call_service",
    # Android phone control (gated on phone WebSocket connection via check_fn)
    "android_open_app", "android_call", "android_send_sms",
    "android_set_alarm", "android_set_timer",
    "android_navigate", "android_web_search",
    "android_volume", "android_brightness",
    "android_tap", "android_type_text", "android_swipe",
    "android_press_back", "android_press_home",
    "android_read_screen", "android_status",
    "android_file_list", "android_file_read", "android_file_write",
    "android_file_delete", "android_file_move", "android_file_info",
    "android_request_all_files_access",
    # Phone system / hardware
    "android_clipboard_get", "android_clipboard_set",
    "android_torch", "android_battery", "android_network",
    "android_camera_photo", "android_screenshot",
    # Phone calendar (CalendarContract on Android)
    "android_calendar_list_calendars", "android_calendar_list_events",
    "android_calendar_create_event", "android_calendar_update_event",
    "android_calendar_delete_event", "android_calendar_check_permissions",
    # PC control (local-first, Windows; gated on os.name=='nt' via check_fn)
    "pc_open_app", "pc_open_file", "pc_gui_control", "pc_run", "pc_see_screen",
    # Document generation on PC, delivered to phone (PDF/PPTX/DOCX/XLSX/CSV/JSON/ZIP).
    # phone_create_pptx убран — LLM игнорировал и beautiful, и системный промпт.
    "phone_create_pdf", "phone_create_docx",
    "phone_create_xlsx", "phone_markdown_to_pdf",
    "phone_create_csv", "phone_create_json", "phone_create_zip",
    # Beautiful documents with themes + auto-illustrations
    "phone_create_beautiful_pptx", "phone_create_beautiful_pdf",
    "phone_create_infographic",
    # Image generation (Pollinations, free)
    "image_pollinations_url", "phone_create_image",
    # HF Spaces (free, no API key): FLUX (фото) + LTX-Video (видео, async)
    "image_hf_flux", "phone_create_video",
    # Skills hub — лёгкие полезные tools
    "skill_weather", "skill_wikipedia", "skill_translate",
    "skill_currency_rate", "skill_crypto_price", "skill_hackernews",
    "skill_qr_code", "skill_calculator", "skill_unit_convert",
    "skill_world_time", "skill_url_shorten", "skill_random_value",
    "skill_date_math", "skill_youtube_search", "skill_joke", "skill_fact",
    # Obsidian vault notes (also linked to Claude memory)
    "obsidian_note",
    # Voice journal + reminders для Тройки
    "journal_today", "reminder",
    # Server-initiated push (Тройка сама заговаривает с Мишей)
    "push_to_user",
    # Контекст «где я» — fingerprint Wi-Fi/Bluetooth → дом/работа/машина
    "location",
    # Voice fingerprint — отличить Мишу от чужих голосов через Resemblyzer
    "speaker_id",
    # Фоновые задачи через kanban: "запусти research, через час расскажешь"
    "bg_task",
    # RAG-поиск по Obsidian vault (BGE-M3 + sqlite)
    "notes",
    # Учёт расходов/доходов голосом
    "finance",
    # Мета-router: find_tool(query) → schema редкого инструмента
    "find_tool",
    # Делегирование кодинг-задач CLI-кодерам на PC (вход по аккаунту/подписке)
    "gemini_code",   # Gemini CLI (Google OAuth)
    "claude_code",   # Claude Code (подписка Claude) — лучший кодер
    # "qwen_code",   # Qwen Code — СПЯЩИЙ: требует API-ключ Alibaba ModelStudio (не
    #                  чистый OAuth). Код готов в coder_tool.py; раскомментить когда
    #                  будет ключ (~/.qwen/oauth_creds.json или QWEN API key).
    # Статус фоновых задач (job_runner)
    "task_status",
    # Управление проектами (vision/SRS/архитектура/код)
    "project",
    # Self-improvement: Тройка предлагает правки в свой код, Миша одобряет
    "self_improve_propose", "self_improve_list", "self_improve_show",
    "self_improve_approve", "self_improve_reject", "self_improve_revert",
    "code_review",
    # «Нет тула для задачи» → сама пишет tool и возвращается к задаче
    "ensure_capability",
    # Поиск по vault'у памяти + дневник
    "memory_search", "diary_add", "diary_read",
    # SOMA — память о пользователе с эмоц-весом и confidence
    "soma_remember", "soma_recall", "soma_forget",
    # GROUND — фоновый наблюдатель экрана; DAEMON — автономный проактивный ум
    "ground_start", "ground_stop", "ground_status",
    "daemon_start", "daemon_stop", "daemon_status",
    # WORKSPACE — второй «рабочий стол» (Kali) для security/пентеста своих систем.
    # Переключает терминал в изолированный контейнер per-session. Гейт авторизации
    # раз-в-сессию (workspace_confirm). См. skill security-methodology.
    "workspace_enter", "workspace_exit", "workspace_status", "workspace_confirm",
    # Kanban multi-agent coordination — only in schema when the agent is
    # spawned as a kanban worker (HERMES_KANBAN_TASK env set) or the current
    # profile explicitly enables the kanban toolset. Gated via check_fn in
    # tools/kanban_tools.py.
    "kanban_show", "kanban_list",
    "kanban_complete", "kanban_block", "kanban_heartbeat",
    "kanban_comment", "kanban_create", "kanban_link",
    "kanban_unblock",
    # Computer use (macOS, gated on cua-driver being installed via check_fn)
    "computer_use",
]

# Webhook events may originate from untrusted third-party content (for example,
# public PR titles/comments). Keep the default webhook toolset intentionally
# constrained to avoid local file/system execution by prompt injection.
_HERMES_WEBHOOK_SAFE_TOOLS = [
    "web_search",
    "web_extract",
    "vision_analyze",
    "clarify",
]


# Core toolset definitions
# These can include individual tools or reference other toolsets
TOOLSETS = {
    # Basic toolsets - individual tool categories
    "web": {
        "description": "Web research and content extraction tools",
        "tools": ["web_search", "web_extract", "web_research"],
        "includes": []  # No other toolsets included
    },
    
    "search": {
        "description": "Web search only (no content extraction/scraping)",
        "tools": ["web_search"],
        "includes": []
    },

    "x_search": {
        "description": (
            "Search X (Twitter) posts and threads via xAI's built-in "
            "x_search Responses tool. Available when xAI credentials are "
            "configured (SuperGrok OAuth or XAI_API_KEY). Off by default; "
            "enable in `hermes tools` → X (Twitter) Search."
        ),
        "tools": ["x_search"],
        "includes": []
    },
    
    "vision": {
        "description": "Image analysis and vision tools",
        "tools": ["vision_analyze"],
        "includes": []
    },

    "video": {
        "description": "Video analysis and understanding tools (opt-in, not in default toolset)",
        "tools": ["video_analyze"],
        "includes": []
    },
    
    "image_gen": {
        "description": "Creative generation tools (images)",
        "tools": ["image_generate"],
        "includes": []
    },

    "video_gen": {
        "description": (
            "Video generation tools. Single ``video_generate`` tool covers "
            "text-to-video (prompt only) and image-to-video (prompt + "
            "image_url) — the active backend auto-routes. Configure via "
            "``hermes tools`` → Video Generation."
        ),
        "tools": ["video_generate"],
        "includes": []
    },

    "computer_use": {
        "description": (
            "Background macOS desktop control via cua-driver — screenshots, "
            "mouse, keyboard, scroll, drag. Does NOT steal the user's cursor "
            "or keyboard focus. Works with any tool-capable model."
        ),
        "tools": ["computer_use"],
        "includes": []
    },

    "terminal": {
        "description": "Terminal/command execution and process management tools",
        "tools": ["terminal", "process"],
        "includes": []
    },
    
    "moa": {
        "description": "Advanced reasoning and problem-solving tools",
        "tools": ["mixture_of_agents"],
        "includes": []
    },
    
    "skills": {
        "description": "Access, create, edit, and manage skill documents with specialized instructions and knowledge",
        "tools": ["skills_list", "skill_view", "skill_manage"],
        "includes": []
    },
    
    "browser": {
        "description": "Browser automation for web interaction (navigate, click, type, scroll, iframes, hold-click) with web search for finding URLs",
        "tools": [
            "browser_navigate", "browser_snapshot", "browser_click",
            "browser_type", "browser_scroll", "browser_back",
            "browser_press", "browser_get_images",
            "browser_vision", "browser_console", "browser_cdp",
            "browser_dialog", "web_search"
        ],
        "includes": []
    },
    
    "cronjob": {
        "description": "Cronjob management tool - create, list, update, pause, resume, remove, and trigger scheduled tasks",
        "tools": ["cronjob"],
        "includes": []
    },
    
    "messaging": {
        "description": "Cross-platform messaging: send messages to Telegram, Discord, Slack, SMS, etc.",
        "tools": ["send_message"],
        "includes": []
    },

    
    "file": {
        "description": "File manipulation tools: read, write, patch (with fuzzy matching), and search (content + files)",
        "tools": ["read_file", "write_file", "patch", "search_files"],
        "includes": []
    },
    
    "tts": {
        "description": "Text-to-speech: convert text to audio with Edge TTS (free), ElevenLabs, OpenAI, or xAI",
        "tools": ["text_to_speech"],
        "includes": []
    },
    
    "todo": {
        "description": "Task planning and tracking for multi-step work",
        "tools": ["todo"],
        "includes": []
    },
    
    "memory": {
        "description": "Persistent memory across sessions (personal notes + user profile)",
        "tools": ["memory"],
        "includes": []
    },
    
    "session_search": {
        "description": "Search and recall past conversations with summarization",
        "tools": ["session_search"],
        "includes": []
    },
    
    "clarify": {
        "description": "Ask the user clarifying questions (multiple-choice or open-ended)",
        "tools": ["clarify"],
        "includes": []
    },
    
    "code_execution": {
        "description": "Run Python scripts that call tools programmatically (reduces LLM round trips)",
        "tools": ["execute_code"],
        "includes": []
    },
    
    "delegation": {
        "description": "Spawn subagents with isolated context for complex subtasks",
        "tools": ["delegate_task"],
        "includes": []
    },

    # "honcho" toolset removed — Honcho is now a memory provider plugin.
    # Tools are injected via MemoryManager, not the toolset system.

    "homeassistant": {
        "description": "Home Assistant smart home control and monitoring",
        "tools": ["ha_list_entities", "ha_get_state", "ha_list_services", "ha_call_service"],
        "includes": []
    },

    "android": {
        "description": "Control connected Android phone — apps, calls, alarms, navigation, volume/brightness, UI taps via accessibility, file system ops, clipboard, torch, battery/network info, camera, screenshot with vision.",
        "tools": [
            "android_open_app", "android_call", "android_send_sms",
            "android_set_alarm", "android_set_timer",
            "android_navigate", "android_web_search",
            "android_volume", "android_brightness",
            "android_tap", "android_type_text", "android_swipe",
            "android_press_back", "android_press_home",
            "android_read_screen",
            "android_status",
            "android_file_list", "android_file_read", "android_file_write",
            "android_file_delete", "android_file_move", "android_file_info",
            "android_request_all_files_access",
            "android_clipboard_get", "android_clipboard_set",
            "android_torch", "android_battery", "android_network",
            "android_camera_photo", "android_screenshot",
            "android_calendar_list_calendars", "android_calendar_list_events",
            "android_calendar_create_event", "android_calendar_update_event",
            "android_calendar_delete_event", "android_calendar_check_permissions",
            "phone_create_pdf", "phone_create_docx",
            "phone_create_xlsx", "phone_markdown_to_pdf",
            "phone_create_csv", "phone_create_json", "phone_create_zip",
            # phone_create_pptx убран — LLM упорно выбирал его вместо beautiful.
            # Теперь единственный путь сделать презентацию — phone_create_beautiful_pptx.
            "phone_create_beautiful_pptx", "phone_create_beautiful_pdf",
            "phone_create_infographic",
            "image_pollinations_url", "phone_create_image",
            "skill_weather", "skill_wikipedia", "skill_translate",
            "skill_currency_rate", "skill_crypto_price", "skill_hackernews",
            "skill_qr_code", "skill_calculator", "skill_unit_convert",
            "skill_world_time", "skill_url_shorten", "skill_random_value",
            "skill_date_math", "skill_youtube_search", "skill_joke", "skill_fact",
            "obsidian_note",
            "journal_today", "reminder",
            "push_to_user",
            "location",
            "speaker_id",
            "bg_task",
            "notes",
            "finance",
        ],
        "includes": []
    },

    "ground": {
        "description": "GROUND — фоновый наблюдатель экрана телефона: Тройка периодически 'видит' чем занят пользователь (через vision), анализируя экран только при изменениях.",
        "tools": ["ground_start", "ground_stop", "ground_status"],
        "includes": []
    },

    "daemon": {
        "description": "DAEMON — автономный фоновый ум: Тройка раз в несколько минут осматривается и сама пишет первой, если есть стоящий повод (с анти-спамом: тихие часы, лимит/день, пауза).",
        "tools": ["daemon_start", "daemon_stop", "daemon_status"],
        "includes": []
    },

    "kanban": {
        "description": (
            "Kanban multi-agent coordination — only active when the agent "
            "is spawned by the kanban dispatcher (HERMES_KANBAN_TASK env "
            "set). The dispatcher runs inside the gateway by default; see "
            "`kanban.dispatch_in_gateway` in config.yaml. Lets workers mark "
            "tasks done with structured handoffs, block for human input, "
            "heartbeat during long ops, comment on threads, and (for "
            "orchestrators) list, unblock, and fan out tasks."
        ),
        "tools": [
            "kanban_show", "kanban_list", "kanban_complete", "kanban_block",
            "kanban_heartbeat", "kanban_comment",
            "kanban_create", "kanban_link",
            "kanban_unblock",
        ],
        "includes": [],
    },

    "discord": {
        "description": "Discord read and participate tools (fetch messages, search members, create threads)",
        "tools": ["discord"],
        "includes": [],
    },

    "discord_admin": {
        "description": "Discord server management (list channels/roles, pin messages, assign roles)",
        "tools": ["discord_admin"],
        "includes": [],
    },

    "yuanbao": {
        "description": "Yuanbao platform tools - group info, member queries, DM, stickers",
        "tools": [
            "yb_query_group_info",
            "yb_query_group_members",
            "yb_send_dm",
            "yb_search_sticker",
            "yb_send_sticker",
        ],
        "includes": []
    },

    "feishu_doc": {
        "description": "Read Feishu/Lark document content",
        "tools": ["feishu_doc_read"],
        "includes": []
    },

    "feishu_drive": {
        "description": "Feishu/Lark document comment operations (list, reply, add)",
        "tools": [
            "feishu_drive_list_comments", "feishu_drive_list_comment_replies",
            "feishu_drive_reply_comment", "feishu_drive_add_comment",
        ],
        "includes": []
    },

    "obsidian": {
        "description": "Obsidian vault — read, write, search, quick-capture notes in d:\\troikahermes-vault (also linked to Claude memory).",
        "tools": ["obsidian_note"],
        "includes": []
    },

    "journal": {
        "description": "Журнал того что Миша говорил Тройке за день/неделю/месяц (читает state.db).",
        "tools": ["journal_today"],
        "includes": []
    },

    "reminder": {
        "description": "Голосовые напоминания через one-shot cron — push на телефон в указанное время.",
        "tools": ["reminder"],
        "includes": []
    },

    "push": {
        "description": "Server-initiated push: Тройка сама говорит с Мишей через notification + TTS на телефон.",
        "tools": ["push_to_user"],
        "includes": []
    },

    "location": {
        "description": (
            "Контекст «где я»: маппинг fingerprint'а телефона (Wi-Fi BSSID, "
            "Bluetooth-устройства, тип сети) → именованное место (дом/работа/машина). "
            "Тройка подстраивает длину и стиль ответов под место."
        ),
        "tools": ["location"],
        "includes": []
    },

    "speaker_id": {
        "description": (
            "Voice fingerprint через Resemblyzer — отличить Мишу от других "
            "голосов. enroll/verify/list/forget. Требует resemblyzer + soundfile."
        ),
        "tools": ["speaker_id"],
        "includes": []
    },

    "bg_task": {
        "description": (
            "Фоновые задачи через Kanban: 'запусти research, через час расскажешь'. "
            "Тонкая обёртка над kanban_create — добавляет инструкцию пушнуть "
            "результат через push_to_user когда worker закончит."
        ),
        "tools": ["bg_task"],
        "includes": []
    },

    "notes": {
        "description": (
            "RAG-поиск по Obsidian vault (d:\\troikahermes-vault). BGE-M3 "
            "embeddings + sqlite. operations: index/search/stats. Требует "
            "sentence-transformers (~600MB модель скачается при первом index)."
        ),
        "tools": ["notes"],
        "includes": []
    },

    "finance": {
        "description": (
            "Голосовой учёт расходов/доходов. sqlite в ~/.troika/finance.db. "
            "operations: add/list/summary/delete. Без API банков — только то "
            "что Миша надиктовал."
        ),
        "tools": ["finance"],
        "includes": []
    },

    "spotify": {
        "description": "Native Spotify playback, search, playlist, album, and library tools",
        "tools": [
            "spotify_playback", "spotify_devices", "spotify_queue", "spotify_search",
            "spotify_playlists", "spotify_albums", "spotify_library",
        ],
        "includes": []
    },


    # Scenario-specific toolsets
    
    "debugging": {
        "description": "Debugging and troubleshooting toolkit",
        "tools": ["terminal", "process"],
        "includes": ["web", "file"]  # For searching error messages and solutions, and file operations
    },
    
    "safe": {
        "description": "Safe toolkit without terminal access",
        "tools": [],
        "includes": ["web", "vision", "image_gen"]
    },

    "troika-screen-snapshot": {
        "description": "Opt-in, consent-bound Troika Android screen snapshot",
        "tools": ["troika_screen_snapshot"],
        "includes": [],
    },

    "troika-product": {
        "description": "Hosted Troika toolkit with private files and paired-phone controls.",
        # Keep the reviewed media names explicit. The legacy `safe` composite
        # expands every registered image_gen tool, including global-phone
        # delivery and experimental video tools without product ownership.
        "tools": ["troika_assistant", "troika_reminder", "web_search",
                  "web_extract", "web_research", "vision_analyze",
                  "image_generate", "image_pollinations_url"],
        "includes": ["troika-phone", "troika-documents", "troika-workspace"],
    },

    "troika-workspace": {
        "description": "Private user-owned files, search, and bounded terminal commands.",
        "tools": [
            "troika_files",
            "troika_file_search",
            "troika_terminal",
        ],
        "includes": [],
    },

    "troika-documents": {
        "description": "Private user-owned Word, PDF, and PowerPoint creation.",
        "tools": [
            "troika_create_docx",
            "troika_create_pdf",
            "troika_create_pptx",
            "troika_create_project",
        ],
        "includes": [],
    },

    "troika-phone": {
        "description": "Paired phone controls with per-action confirmation.",
        "tools": [
            # Device-owned read-only information.
            "android_status", "android_battery", "android_network",
            # Low-scope phone actions. ProductPhoneBridge rejects every
            # other Android action and these require one-time confirmation.
            "android_open_app", "android_web_search",
            "android_set_alarm", "android_set_timer", "android_navigate",
            "android_volume", "android_brightness", "android_torch",
            "android_camera_photo",
        ],
        "includes": [],
    },
    
    # ==========================================================================
    # Full Hermes toolsets (CLI + messaging platforms)
    #
    # All platforms share the same core tools (including send_message,
    # which is gated on gateway running via its check_fn).
    # ==========================================================================

    "hermes-acp": {
        "description": "Editor integration (VS Code, Zed, JetBrains) — coding-focused tools without messaging, audio, or clarify UI",
        "tools": [
            "web_search", "web_extract",
            "terminal", "process",
            "read_file", "write_file", "patch", "search_files",
            "vision_analyze",
            "skills_list", "skill_view", "skill_manage",
            "browser_navigate", "browser_snapshot", "browser_click",
            "browser_type", "browser_scroll", "browser_back",
            "browser_press", "browser_get_images",
            "browser_vision", "browser_console", "browser_cdp", "browser_dialog",
            "todo", "memory",
            "session_search",
            "execute_code", "delegate_task",
        ],
        "includes": []
    },

    "hermes-api-server": {
        # 29 мая 2026: УРЕЗАН до набора troika-voice ради низкой латентности
        # голосовой Тройки. Был ~110 tools (~30k system prompt → 7-14s LLM),
        # стал 40 tools (~6k → 2-4s). Редкие tools доступны через find_tool.
        # Если когда-то понадобится полный набор для какого-то API-клиента —
        # сделать отдельный composite-toolset и поменять PLATFORMS.api_server.
        "description": "OpenAI-compatible API server — slim voice toolset. Rare tools accessible via find_tool router.",
        # 15 июня 2026: УРЕЗАН с 53 до ~28 tools. На телефоне payload разбух до
        # ~21k токенов (deepseek на бесплатном пуле OpenRouter ловил 429 и мозг
        # «не мог»). Редкие tools (календарь update/delete, torch/network/battery/
        # brightness/clipboard/timer/camera, finance/notes/journal/speaker_id,
        # phone_create_video, gemini_code, delegate_task, skill_calculator/
        # world_time/currency, *_status) доступны через find_tool-роутер.
        # 13.08.2026 (round 3): ТОЛЬКО критически горячие + find_tool. Все
        # остальные 150+ tools ДОСТУПНЫ через find_tool — они не пропали,
        # они не заняли слот в schema. Экономия: 6100→~2500 tok/запрос.
        # Правило чтобы попасть сюда: (а) реально частый на голосе И
        # (б) find_tool router даёт +1 сетевой round-trip который здесь недопустим.
        "tools": [
            # Meta-triad: три инструмента-скелета, дающие доступ к ВСЕМ 180+ tools
            # без раздутого schema. find_tool находит по запросу, run_tool
            # исполняет найденное по имени, what_can_i_do — самосправка
            # категорий (чтобы не отказывать «не умею» когда умеет).
            "find_tool",
            "run_tool",
            "what_can_i_do",
            # Голос Тройки (её собственные каналы)
            "push_to_user",       # проактивно заговорить с Мишей
            "telegram_send",      # «в тг / в избранное / отправь мне»
            "reminder",           # «напомни через час»
            # Место — почти каждый запрос его использует через system prompt
            "location",
            # Память — часто, недопустим лишний вызов
            "soma_recall",        # «что ты помнишь о …»
            # Телефон — самое-самое
            "android_open_app",   # «открой youtube»
            "android_calendar_create_event",  # «запиши на 15:00»
            "vision_analyze",     # «посмотри на фото/скрин»
            # Web — почти каждый второй вопрос
            "web_search",
            # Кодинг «сделай приложение / сайт»
            "claude_code",
            # Skill_view чтобы читать skills-документы (voice-task-routing и др.)
            # — быстрая маршрутизация без лишнего round-trip.
            "skill_view",
            # WORKSPACE — «перейди в кали / вернись» должно срабатывать с первого
            # раза, без find_tool round-trip. Остальные три (exit/status/confirm)
            # мозг подтянет через find_tool когда понадобится.
            "workspace_enter",
            # «Нет тула для задачи» — критично на голосе, где Миша даёт запросы
            # с широким спектром действий. Без hot-path Тройка через find_tool
            # не догадается, что можно САМА написать недостающее.
            "ensure_capability",
        ],
        "includes": []
    },

    "hermes-cli": {
        "description": "Full interactive CLI toolset - all default tools plus cronjob management",
        "tools": _HERMES_CORE_TOOLS,
        "includes": []
    },

    "troika-cli": {
        # Алиас "troika-cli" — используется в ~/.troika/config.yaml как имя toolset
        # для phone-assistant Тройки. Полный набор включая mixture_of_agents
        # и delegate_task — чтобы голосовой помощник умел делегировать сложные
        # задачи sub-agent'ам и привлекать несколько моделей параллельно.
        "description": "Troika voice assistant toolset - full hermes-api-server tools",
        "tools": [],
        "includes": ["hermes-api-server", "moa"]
    },

    "troika-voice": {
        # Голосовой набор Тройки — hot path для низкой латентности.
        # ~25 самых частых tools + find_tool. Документы/презентации/перевод
        # оставлены в hot path: они частые на голосе и Gemini Lite плохо
        # справляется с двухшаговым find_tool routing для них.
        # Spotify/computer_use/mcp_*/exotic skill_* — через find_tool.
        # Цель: system prompt 36k → ~15-18k токенов, latency 30s → 10-13s.
        # 13.08.2026 round 3: ужат с 38→13 tools. Все остальные 150+ tools
        # ДОСТУПНЫ через find_tool (registry на 161 tool). Экономия ~4700
        # tokens/запрос. Правило чтобы попасть сюда — как в hermes-api-server.
        "description": "Troika voice — минимум hot-path + find_tool router. 150+ редких tools через find_tool.",
        "tools": [
            "find_tool",
            "push_to_user",
            "telegram_send",
            "reminder",
            "location",
            "soma_recall",
            "android_open_app",
            "android_calendar_create_event",
            "vision_analyze",
            "web_search",
            "claude_code",
            "skill_view",
            "obsidian_note",
            # «Нет тула → сама пишу и продолжаю». Обязательно на голосе.
            "ensure_capability",
        ],
        "includes": []
    },

    "pc": {
        # Управление своим ПК (Windows, local-first). См.
        # docs/TROIKA_PC_AGENT_PLAN.md. Хендлеры in-process, без моста;
        # показываются только когда gateway на Windows (check_fn os.name=='nt').
        "description": "PC control (Windows): launch apps, open files, live GUI control, system actions.",
        "tools": [
            "pc_open_app", "pc_open_file", "pc_gui_control", "pc_run", "pc_see_screen",
        ],
        "includes": []
    },

    "hermes-cron": {
        # Mirrors hermes-cli so cron's "default" toolset is the same set of
        # core tools users see interactively — then `hermes tools` filters
        # them down per the platform config. _DEFAULT_OFF_TOOLSETS (moa,
        # homeassistant) are excluded by _get_platform_tools() unless
        # the user explicitly enables them.
        "description": "Default cron toolset - same core tools as hermes-cli; gated by `hermes tools`",
        "tools": _HERMES_CORE_TOOLS,
        "includes": []
    },

    "hermes-telegram": {
        "description": "Telegram bot toolset - full access for personal use (terminal has safety checks)",
        "tools": _HERMES_CORE_TOOLS,
        "includes": []
    },
    
    "hermes-discord": {
        "description": "Discord bot toolset - full access (terminal has safety checks via dangerous command approval)",
        "tools": _HERMES_CORE_TOOLS + [
            "discord",
            "discord_admin",
        ],
        "includes": []
    },
    
    "hermes-whatsapp": {
        "description": "WhatsApp bot toolset - similar to Telegram (personal messaging, more trusted)",
        "tools": _HERMES_CORE_TOOLS,
        "includes": []
    },
    
    "hermes-slack": {
        "description": "Slack bot toolset - full access for workspace use (terminal has safety checks)",
        "tools": _HERMES_CORE_TOOLS,
        "includes": []
    },
    
    "hermes-signal": {
        "description": "Signal bot toolset - encrypted messaging platform (full access)",
        "tools": _HERMES_CORE_TOOLS,
        "includes": []
    },

    "hermes-bluebubbles": {
        "description": "BlueBubbles iMessage bot toolset - Apple iMessage via local BlueBubbles server",
        "tools": _HERMES_CORE_TOOLS,
        "includes": []
    },

    "hermes-homeassistant": {
        "description": "Home Assistant bot toolset - smart home event monitoring and control",
        "tools": _HERMES_CORE_TOOLS,
        "includes": []
    },

    "hermes-email": {
        "description": "Email bot toolset - interact with Hermes via email (IMAP/SMTP)",
        "tools": _HERMES_CORE_TOOLS,
        "includes": []
    },

    "hermes-mattermost": {
        "description": "Mattermost bot toolset - self-hosted team messaging (full access)",
        "tools": _HERMES_CORE_TOOLS,
        "includes": []
    },

    "hermes-matrix": {
        "description": "Matrix bot toolset - decentralized encrypted messaging (full access)",
        "tools": _HERMES_CORE_TOOLS,
        "includes": []
    },

    "hermes-dingtalk": {
        "description": "DingTalk bot toolset - enterprise messaging platform (full access)",
        "tools": _HERMES_CORE_TOOLS,
        "includes": []
    },

    "hermes-feishu": {
        "description": "Feishu/Lark bot toolset - enterprise messaging via Feishu/Lark (full access)",
        "tools": _HERMES_CORE_TOOLS + [
            "feishu_doc_read",
            "feishu_drive_list_comments",
            "feishu_drive_list_comment_replies",
            "feishu_drive_reply_comment",
            "feishu_drive_add_comment",
        ],
        "includes": []
    },

    "hermes-weixin": {
        "description": "Weixin bot toolset - personal WeChat messaging via iLink (full access)",
        "tools": _HERMES_CORE_TOOLS,
        "includes": []
    },

    "hermes-qqbot": {
        "description": "QQBot toolset - QQ messaging via Official Bot API v2 (full access)",
        "tools": _HERMES_CORE_TOOLS,
        "includes": []
    },

    "hermes-wecom": {
        "description": "WeCom bot toolset - enterprise WeChat messaging (full access)",
        "tools": _HERMES_CORE_TOOLS,
        "includes": []
    },

    "hermes-wecom-callback": {
        "description": "WeCom callback toolset - enterprise self-built app messaging (full access)",
        "tools": _HERMES_CORE_TOOLS,
        "includes": []
    },

    "hermes-yuanbao": {
        "description": "Yuanbao Bot 元宝消息平台工具集 - 群信息、成员查询、私聊、贴纸表情",
        "tools": _HERMES_CORE_TOOLS + [
            "yb_query_group_info",
            "yb_query_group_members",
            "yb_send_dm",
            "yb_search_sticker",
            "yb_send_sticker",
        ],
        "module": "tools.yuanbao_tools",
        "includes": []
    },

    "hermes-sms": {
        "description": "SMS bot toolset - interact with Hermes via SMS (Twilio)",
        "tools": _HERMES_CORE_TOOLS,
        "includes": []
    },

    "hermes-webhook": {
        "description": "Webhook toolset - receive and process external webhook events",
        "tools": _HERMES_WEBHOOK_SAFE_TOOLS,
        "includes": []
    },

    "hermes-gateway": {
        "description": "Gateway toolset - union of all messaging platform tools",
        "tools": [],
        "includes": ["hermes-telegram", "hermes-discord", "hermes-whatsapp", "hermes-slack", "hermes-signal", "hermes-bluebubbles", "hermes-homeassistant", "hermes-email", "hermes-sms", "hermes-mattermost", "hermes-matrix", "hermes-dingtalk", "hermes-feishu", "hermes-wecom", "hermes-wecom-callback", "hermes-weixin", "hermes-qqbot", "hermes-webhook", "hermes-yuanbao"]
    }
}



def get_toolset(name: str) -> Optional[Dict[str, Any]]:
    """
    Get a toolset definition by name.
    
    Args:
        name (str): Name of the toolset
        
    Returns:
        Dict: Toolset definition with description, tools, and includes
        None: If toolset not found
    """
    toolset = TOOLSETS.get(name)

    try:
        from tools.registry import registry
    except Exception:
        return toolset if toolset else None

    if toolset:
        merged_tools = sorted(
            set(toolset.get("tools", []))
            | set(registry.get_tool_names_for_toolset(name))
        )
        return {**toolset, "tools": merged_tools}

    registry_toolset = name
    description = f"Plugin toolset: {name}"
    alias_target = registry.get_toolset_alias_target(name)

    if name not in _get_plugin_toolset_names():
        registry_toolset = alias_target
        if not registry_toolset:
            return None
        description = f"MCP server '{name}' tools"
    else:
        reverse_aliases = {
            canonical: alias
            for alias, canonical in _get_registry_toolset_aliases().items()
            if alias not in TOOLSETS
        }
        alias = reverse_aliases.get(name)
        if alias:
            description = f"MCP server '{alias}' tools"

    return {
        "description": description,
        "tools": registry.get_tool_names_for_toolset(registry_toolset),
        "includes": [],
    }


def resolve_toolset(name: str, visited: Set[str] = None) -> List[str]:
    """
    Recursively resolve a toolset to get all tool names.
    
    This function handles toolset composition by recursively resolving
    included toolsets and combining all tools.
    
    Args:
        name (str): Name of the toolset to resolve
        visited (Set[str]): Set of already visited toolsets (for cycle detection)
        
    Returns:
        List[str]: List of all tool names in the toolset
    """
    if visited is None:
        visited = set()
    
    # Special aliases that represent all tools across every toolset
    # This ensures future toolsets are automatically included without changes.
    if name in {"all", "*"}:
        all_tools: Set[str] = set()
        for toolset_name in get_toolset_names():
            # Use a fresh visited set per branch to avoid cross-branch contamination
            resolved = resolve_toolset(toolset_name, visited.copy())
            all_tools.update(resolved)
        return sorted(all_tools)

    # Check for cycles / already-resolved (diamond deps).
    # Silently return [] — either this is a diamond (not a bug, tools already
    # collected via another path) or a genuine cycle (safe to skip).
    if name in visited:
        return []

    visited.add(name)

    # Get toolset definition
    toolset = get_toolset(name)
    if not toolset:
        # Auto-generate a toolset for plugin platforms (hermes-<name>).
        # Gives them _HERMES_CORE_TOOLS plus any tools the plugin registered
        # into a toolset matching the platform name.
        if name.startswith("hermes-"):
            platform_name = name[len("hermes-"):]
            try:
                from gateway.platform_registry import platform_registry
                if platform_registry.is_registered(platform_name):
                    plugin_tools = set(_HERMES_CORE_TOOLS)
                    try:
                        from tools.registry import registry
                        plugin_tools.update(
                            e.name for e in registry._tools.values()
                            if e.toolset == platform_name
                        )
                    except Exception:
                        pass
                    return list(plugin_tools)
            except Exception:
                pass

        return []

    # Collect direct tools
    tools = set(toolset.get("tools", []))

    # Recursively resolve included toolsets, sharing the visited set across
    # sibling includes so diamond dependencies are only resolved once and
    # cycle warnings don't fire multiple times for the same cycle.
    for included_name in toolset.get("includes", []):
        included_tools = resolve_toolset(included_name, visited)
        tools.update(included_tools)
    
    return sorted(tools)


def resolve_multiple_toolsets(toolset_names: List[str]) -> List[str]:
    """
    Resolve multiple toolsets and combine their tools.
    
    Args:
        toolset_names (List[str]): List of toolset names to resolve
        
    Returns:
        List[str]: Combined list of all tool names (deduplicated)
    """
    all_tools = set()
    
    for name in toolset_names:
        tools = resolve_toolset(name)
        all_tools.update(tools)
    
    return sorted(all_tools)


def _get_plugin_toolset_names() -> Set[str]:
    """Return toolset names registered by plugins (from the tool registry).

    These are toolsets that exist in the registry but not in the static
    ``TOOLSETS`` dict — i.e. they were added by plugins at load time.
    """
    try:
        from tools.registry import registry
        return {
            toolset_name
            for toolset_name in registry.get_registered_toolset_names()
            if toolset_name not in TOOLSETS
        }
    except Exception:
        return set()


def _get_registry_toolset_aliases() -> Dict[str, str]:
    """Return explicit toolset aliases registered in the live registry."""
    try:
        from tools.registry import registry
        return registry.get_registered_toolset_aliases()
    except Exception:
        return {}


def get_all_toolsets() -> Dict[str, Dict[str, Any]]:
    """
    Get all available toolsets with their definitions.

    Includes both statically-defined toolsets and plugin-registered ones.
    
    Returns:
        Dict: All toolset definitions
    """
    result = dict(TOOLSETS)
    aliases = _get_registry_toolset_aliases()
    for ts_name in _get_plugin_toolset_names():
        display_name = ts_name
        for alias, canonical in aliases.items():
            if canonical == ts_name and alias not in TOOLSETS:
                display_name = alias
                break
        if display_name in result:
            continue
        toolset = get_toolset(display_name)
        if toolset:
            result[display_name] = toolset
    return result


def get_toolset_names() -> List[str]:
    """
    Get names of all available toolsets (excluding aliases).

    Includes plugin-registered toolset names.
    
    Returns:
        List[str]: List of toolset names
    """
    names = set(TOOLSETS.keys())
    aliases = _get_registry_toolset_aliases()
    for ts_name in _get_plugin_toolset_names():
        for alias, canonical in aliases.items():
            if canonical == ts_name and alias not in TOOLSETS:
                names.add(alias)
                break
        else:
            names.add(ts_name)
    return sorted(names)




def validate_toolset(name: str) -> bool:
    """
    Check if a toolset name is valid.
    
    Args:
        name (str): Toolset name to validate
        
    Returns:
        bool: True if valid, False otherwise
    """
    # Accept special alias names for convenience
    if name in {"all", "*"}:
        return True
    if name in TOOLSETS:
        return True
    if name in _get_plugin_toolset_names():
        return True
    return name in _get_registry_toolset_aliases()


def create_custom_toolset(
    name: str,
    description: str,
    tools: List[str] = None,
    includes: List[str] = None
) -> None:
    """
    Create a custom toolset at runtime.
    
    Args:
        name (str): Name for the new toolset
        description (str): Description of the toolset
        tools (List[str]): Direct tools to include
        includes (List[str]): Other toolsets to include
    """
    TOOLSETS[name] = {
        "description": description,
        "tools": tools or [],
        "includes": includes or []
    }




def get_toolset_info(name: str) -> Dict[str, Any]:
    """
    Get detailed information about a toolset including resolved tools.
    
    Args:
        name (str): Toolset name
        
    Returns:
        Dict: Detailed toolset information
    """
    toolset = get_toolset(name)
    if not toolset:
        return None
    
    resolved_tools = resolve_toolset(name)
    
    return {
        "name": name,
        "description": toolset["description"],
        "direct_tools": toolset["tools"],
        "includes": toolset["includes"],
        "resolved_tools": resolved_tools,
        "tool_count": len(resolved_tools),
        "is_composite": bool(toolset["includes"])
    }




if __name__ == "__main__":
    print("Toolsets System Demo")
    print("=" * 60)
    
    print("\nAvailable Toolsets:")
    print("-" * 40)
    for name, toolset in get_all_toolsets().items():
        info = get_toolset_info(name)
        composite = "[composite]" if info["is_composite"] else "[leaf]"
        print(f"  {composite} {name:20} - {toolset['description']}")
        print(f"     Tools: {len(info['resolved_tools'])} total")
    
    print("\nToolset Resolution Examples:")
    print("-" * 40)
    for name in ["web", "terminal", "safe", "debugging"]:
        tools = resolve_toolset(name)
        print(f"\n  {name}:")
        print(f"    Resolved to {len(tools)} tools: {', '.join(sorted(tools))}")
    
    print("\nMultiple Toolset Resolution:")
    print("-" * 40)
    combined = resolve_multiple_toolsets(["web", "vision", "terminal"])
    print("  Combining ['web', 'vision', 'terminal']:")
    print(f"    Result: {', '.join(sorted(combined))}")
    
    print("\nCustom Toolset Creation:")
    print("-" * 40)
    create_custom_toolset(
        name="my_custom",
        description="My custom toolset for specific tasks",
        tools=["web_search"],
        includes=["terminal", "vision"]
    )
    custom_info = get_toolset_info("my_custom")
    print("  Created 'my_custom' toolset:")
    print(f"    Description: {custom_info['description']}")
    print(f"    Resolved tools: {', '.join(custom_info['resolved_tools'])}")
