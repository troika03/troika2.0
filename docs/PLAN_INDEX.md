# Troika — plan and document index

Purpose: stop old plans from silently becoming product requirements or startup context.
Read this file only when you need to decide which plan/spec is authoritative.

## Authority

Use documents in this order when they disagree:

1. New explicit product-owner decision.
2. `Troika_1.0_Launch_Plan_Final_Updated.docx` — canonical 1.0 scope, UX, pricing, release order and Definition of Done.
3. `TROIKA_1_0_EXECUTION_TRACKER.md` — ordered progress against the canonical plan.
4. `CURRENT.md` — compact verified current state and next step.
5. `ARCHITECTURE.md` — stable component and trust-boundary map.
6. Task-specific audit, policy, migration or runbook.
7. Historical plans and inherited Hermes documents.

A lower item never overrides a higher one unless the product owner explicitly changes the decision.

## Active / read on demand

- `../PRODUCTIZATION_PLAN.md` — implementation reference. Useful for product/security architecture detail, but not a replacement for the canonical DOCX.
- `TROIKA_CAPABILITY_RESTORATION_PLAN.md` — capability restoration detail when that work is explicitly in scope.
- `TROIKA_CLOSED_BETA_SETUP.md` — closed-beta provisioning/deployment runbook.
- `DATA_RETENTION_AND_DELETION_POLICY.md` — retention/deletion policy and launch gates.
- `SCREEN_SNAPSHOT_THREAT_MODEL.md` — security boundary for one-frame screen analysis.
- `TROIKA_NATIVE_REBRAND_MIGRATION.md` — compatibility-safe rebrand migration.
- `TROIKA_1_0_SECTION_*_AUDIT.md` — evidence for completed/checked canonical sections. These are evidence, not new product plans.

## Historical / inherited plan locations

These locations are not startup context and are not authoritative for Troika 1.0 unless a current task explicitly references them:

- `../.plans/` — inherited Hermes plans for the OpenAI-compatible API server and legacy streaming architecture.
- `../plans/` — inherited provider-specific Hermes plans such as Gemini OAuth.
- `plans/` — older dated Hermes feature plans (Telegram topics, s6 per-profile gateways, ACP/Zed approval diffs).
- `../PROJECT_MEMORY.md` — historical project-memory file. Current state belongs in `CURRENT.md`; old content remains available in Git history.
- Any old monetization, offline-beta, PC-agent, Kali, self-improvement or similar draft discovered in the repository.

### Audited inherited files

The following six files were inspected during the 2026-09-27 context cleanup and are classified as historical Hermes implementation material, not Troika 1.0 requirements:

- `../.plans/openai-api-server.md` — legacy Hermes API-server proposal; current Troika gateway/product API is the source of truth.
- `../.plans/streaming-support.md` — legacy Hermes streaming proposal with old config/provider assumptions.
- `../plans/gemini-oauth-provider.md` — provider-specific Hermes OAuth implementation plan, unrelated to current ordered Troika 1.0 work.
- `plans/2026-05-02-telegram-dm-user-managed-multisession-topics.md` — Telegram/Hermes feature plan outside Troika 1.0 startup scope.
- `plans/2026-05-07-s6-overlay-dynamic-subagent-gateways.md` — already shipped upstream Hermes work retained only as implementation history.
- `plans/2026-05-15-acp-zed-edit-approval-diffs.md` — editor/ACP Hermes plan outside current Troika product scope.

Do not load these six files in a normal Codex session. If a future task genuinely needs one of those subsystems, inspect the current implementation and tests first; use the old plan only as historical context.

## Rule for reusing an old plan

Before implementing from a historical plan:

1. Check the canonical 1.0 DOCX and execution tracker first.
2. Verify the relevant code/tests because old status text can be stale.
3. Copy only still-valid requirements/decisions into the current task-specific spec or tracker.
4. Do not restore obsolete pricing, architecture, unsafe tool access, personal identifiers or old release assumptions.
5. If nothing unique remains, delete the duplicate plan in a dedicated cleanup change; Git history is the archive.

## Startup rule

A normal new coding session should load only:

- root `AGENTS.md`;
- `docs/CURRENT.md`.

Everything else is read on demand.
