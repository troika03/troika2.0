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

## Audited inherited plan files

The following files were checked during the 2026-09-27 context cleanup. They are inherited Hermes references, not Troika 1.0 work queues:

| File | Classification | Rule |
|---|---|---|
| `../.plans/openai-api-server.md` | Historical Hermes API design | The gateway/API implementation now exists; do not use this as current product scope. |
| `../.plans/streaming-support.md` | Historical Hermes streaming design | Streaming is an implementation reference only; verify current code before reusing details. |
| `../plans/gemini-oauth-provider.md` | Provider-specific Hermes plan | Not part of Troika 1.0 product requirements. Use only for explicit provider work. |
| `plans/2026-05-02-telegram-dm-user-managed-multisession-topics.md` | Old Hermes Telegram feature plan | Outside normal Troika 1.0 scope. |
| `plans/2026-05-07-s6-overlay-dynamic-subagent-gateways.md` | Shipped Hermes infrastructure reference | Already marked shipped; implementation/history belongs in code and Git history, not startup context. |
| `plans/2026-05-15-acp-zed-edit-approval-diffs.md` | Old Hermes ACP/Zed plan | Developer-tooling feature, not Troika 1.0 product scope. |

These files are candidates for removal after checking that no unique operational instruction is still referenced by active code/docs. Git history remains the archive.

## Historical / inherited plan locations

These locations are not startup context and are not authoritative for Troika 1.0 unless a current task explicitly references them:

- `../.plans/` — inherited Hermes implementation plans.
- `../plans/` — inherited provider-specific plans.
- `plans/` — older dated Hermes feature plans.
- `../PROJECT_MEMORY.md` — historical project-memory compatibility stub. Current state belongs in `CURRENT.md`; old content remains available in Git history.
- Any old monetization, offline-beta, PC-agent, Kali, self-improvement or similar draft discovered in the repository.

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
