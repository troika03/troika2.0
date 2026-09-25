# Troika 1.0 execution tracker

Primary authority: `Troika_1.0_Launch_Plan_Final_Updated.docx`.

## Execution rule

Work through the Word plan from top to bottom by complete section blocks, not
isolated lines. Read the whole section and its tables first; treat its bullets
as one coherent acceptance set. Preserve existing capabilities internally,
hide out-of-scope features behind flags or Advanced UI, and delete only when a
later plan section explicitly requires migration. Existing code satisfies an
item only after behavior and Definition of Done are checked. The final P0/P1
backlog in section 20 is a release summary, not a replacement for sections
1–19.

Status: `[ ]` not reached, `[-]` active/partial, `[x]` verified.

## Current position

### 1. Vision Troika 1.0

- [x] Troika is voice-first, not a chat window. Android/Windows shared Flutter
  home now uses a central voice orb, short state text, up to three current
  cards, and a small Text button. Widget tests and APK build pass; the latest
  APK is installed and the home screen is visually verified on Samsung A22.
- [x] Action-first results: successful product tools now return only sanitized
  file/task/reminder metadata to the client. Home prioritizes a short completed
  result card, opens the relevant files/tasks surface, and restores the last
  concrete result after restart. Raw output from other tools is never streamed.
- [x] One assistant: modes, model, provider, tool, research, worker routing and
  private reasoning stay hidden from the normal UI and product stream. Existing
  diagnostics remain available only in an explicit developer build.
- [x] Minimum settings: normal UI contains Voice, Memory, Permissions, Account
  and Advanced. Permissions and Account open focused views; technical server,
  BYOK and diagnostic controls remain preserved in Advanced.
- [x] Short truthful statuses: listening, understanding, acting, speaking and
  ready. Product streams suppress reasoning, tool names, previews and raw
  backend errors.
- [x] User-controlled memory: normal settings links directly to the existing
  owner-scoped list, edit and delete screen.
- [x] Safe actions: product approvals expose only a clear description and
  one-time allow/deny choices. Internal command/pattern fields stay server-side;
  unavailable approval channels fail closed.

### 2. What we sell and to whom

- [x] Public product entry points now use the canonical promise: tell Troika
  what to do; it understands, chooses tools, completes the work, saves the
  result, and remembers context. README, Android entry/onboarding, banner and
  runtime docs describe concrete scenarios for students, beginning
  specialists, developers/power users and ordinary users.
- [x] Normal product copy no longer sells tool counts, an agent fork, internal
  reasoning, DAEMON/GROUND, Kali, self-improvement or 24/7 availability.
  Contributor/runtime documentation is explicitly separated from the product
  promise and upstream attribution is preserved.

### 3. Boundaries of the first version

- [x] Audited every mandatory Troika 1.0 area against code and tests. Account,
  voice, devices, subscription and production remain honestly partial; their
  missing acceptance criteria stay assigned to later detailed sections. The
  evidence matrix is `docs/TROIKA_1_0_SECTION_3_AUDIT.md`.
- [x] Added one default-off product feature policy for GROUND, legacy DAEMON,
  live screen/CameraX, full Accessibility control, Kali, self-improvement,
  video generation, exotic messengers, rare Hermes tools and autonomous PC.
  Normal hosted tool routing cannot inherit them. Closed-beta screen snapshot
  also disappeared from ordinary Android builds and requires explicit server
  and build flags. Existing implementation code remains preserved.
- [x] Added the connected subscription-status baseline: authenticated owners
  can read their plan and daily usage without billing data, and Android shows
  the current plan and limit state. Checkout, webhooks and cancellation remain
  explicitly in section 8.

### 4. New voice-first design

- [x] Applied the shared visual direction: graphite base, one amber accent,
  restrained typography, outline icons, generous spacing, and a matching light
  palette ready for later client theme selection.
- [x] The main flow stays voice-first: central orb, one changing prompt, text
  as secondary input, at most three current cards, and one primary action on a
  completed result.
- [x] Implemented and tested distinct idle, listening, thinking, acting,
  approval, speaking, and done orb states. Listening accepts a one-line live
  transcript; acting converts internal tool names into safe concrete statuses;
  speaking remains one-tap interruptible. Approval now uses one clear inline
  card instead of a duplicate modal plus card.

### 5. Android client

- [x] Android navigation now follows the plan: `Главная`, `Дела`, `Файлы`,
  `Профиль`. The voice-first home remains the primary surface; tasks/projects,
  documents/presentations/export and profile settings have dedicated hubs.
- [x] Profile settings are reduced to Account, Voice, Devices, Memory and
  privacy, and Interface. Server/BYOK/debug controls are absent from normal
  builds and remain behind the developer diagnostics build flag. Theme and
  text-size preferences persist; Russian is the supported 1.0 language.
- [x] Background wake is explicit opt-in and reports `Работает`, `Требуется
  разрешение`, `Отключено системой` or `Недоступно на устройстве`. Boot restore
  now checks the saved opt-in; foreground notification, lock-screen TTS,
  barge-in and automatic return to listening remain wired.
- [x] The always-on detector uses Android on-device Russian recognition on
  Android 12+; ambient wake audio is no longer uploaded to STT. Without a
  configured backend, the command after `Тройка` also uses on-device STT and
  the local command matcher. Hosted mode retains the authenticated
  STT/agent/TTS path. Bluetooth routing uses Android's active route.
- [x] Battery drain, wake matches and silent/abandoned activations are recorded
  locally for the release gate. Latest APK is installed on Samsung Galaxy A22;
  home/navigation/profile and screen-off wake-word acceptance are physically
  verified. Exact-token matching, a 12-second cooldown and accepted-wake-only
  metrics reduce false positives.
- [-] A synthetic PC-audio command did not reliably complete the on-device
  command match, so one live-voice wake → local command → TTS/barge-in smoke is
  still required. Bluetooth and an unplugged endurance/false-wake run also
  remain open; the phone was charging at about 10% during this check.

### 6. Windows client

- [ ] Implement and verify Compact Assistant, Command Center, and the promised
  Windows 1.0 actions.

### 7. Sales site and account

- [ ] Build and verify landing, features, pricing, download, account, help,
  status, privacy, terms, and refunds pages plus the activation funnel.

### 8. Plans, billing, and credits

- [ ] Implement Free/Plus/Pro, credits, Free limits, checkout lifecycle,
  idempotent webhooks, cancellation, and billing account UI.

### 9. Backend and architecture

- [ ] Verify the target request chain and complete every P0 backend correction
  in its listed order.

### 10. Voice, memory, and agent tasks

- [ ] Verify voice pipeline, memory, run UX, and one unified Agent Runtime with
  single/delegate/parallel/durable/verified modes.

### 11. Files and documents

- [ ] Verify creation, ownership, preview/open/save/export, version safety, and
  failure handling for the promised file types.

### 12. Security and privacy

- [ ] Verify every security requirement and cross-tenant/approval/deletion/
  export/rate-limit test.

### 13. Infrastructure and production

- [ ] Build production deployment, storage, backups/restore, monitoring,
  secrets, rate limits, and required dashboards.

### 14. Analytics and metrics

- [ ] Implement the operational and product metrics defined in the Word plan
  without collecting prohibited private content.

### 15. Support and legal pages

- [ ] Complete support flow and all required legal pages and policies.

### 16. Rebrand Hermes to Troika

- [-] First compatible Flutter/native Android slice completed. Continue only
  when sections 1–15 reach their ordered rebrand checkpoint; preserve license
  text and use the explicit migration allowlist.

### 17. CI, QA, and release checks

- [ ] Make every required pipeline and end-to-end release gate green.

### 18. Closed beta

- [ ] Run the closed beta checks and in-product feedback flow.

### 19. Public launch

- [ ] Execute the launch sequence and market only verified 1.0 capabilities.

### 20. Priority backlog and final Definition of Done

- [ ] Reconcile all completed work with the numbered P0/P1 queue.
- [ ] Pass the final end-to-end sale readiness statement from the Word plan.
- [ ] Keep post-1.0 capabilities out of release until their listed gates pass.
