# Troika 1.0 execution tracker

Primary authority: `Troika_1.0_Launch_Plan_Final_Updated.docx`.

## Execution rule

Work through the Word plan from top to bottom. Complete and verify each item
before starting the next one. Existing code can satisfy an item only after its
behavior and Definition of Done are checked. The final P0/P1 backlog in section
20 is a release summary, not a replacement for sections 1–19.

Status: `[ ]` not reached, `[-]` active/partial, `[x]` verified.

## Current position

### 1. Vision Troika 1.0

- [x] Troika is voice-first, not a chat window. Android/Windows shared Flutter
  home now uses a central voice orb, short state text, up to three current
  cards, and a small Text button. Widget tests and APK build pass; the latest
  APK is installed and the home screen is visually verified on Samsung A22.
- [-] Action-first results: prefer completed action, file, task, or saved result
  over a long text answer.
- [ ] One assistant: model, tool, research, and worker routing stay hidden from
  the normal user.
- [ ] Minimum settings: move rare technical controls to Advanced/Developer.
- [ ] Short truthful statuses: listening, understanding, acting, ready. Do not
  expose private chain-of-thought.
- [ ] User-controlled memory: inspect, edit, and delete saved memory.

### 2. What we sell and to whom

- [ ] Validate product promise and primary scenarios for students, beginning
  specialists, developers/power users, and ordinary users.

### 3. Boundaries of the first version

- [ ] Verify every mandatory Troika 1.0 area: account, voice, AI, memory, web,
  documents, tasks, devices, subscription, and production.
- [ ] Put non-blocking experimental capabilities behind feature flags and
  remove them from normal UI and marketing.

### 4. New voice-first design

- [ ] Apply the visual direction, main UX flow, and every voice-orb state from
  the Word plan.

### 5. Android client

- [ ] Implement and verify Android information architecture, main screen,
  simplified settings, and background voice P0.

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
