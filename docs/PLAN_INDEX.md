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
7. Historical material in Git history.

A lower item never overrides a higher one unless the product owner explicitly changes the decision.

## Active / read on demand

- `../PRODUCTIZATION_PLAN.md` — implementation reference. Useful for product/security architecture detail, but not a replacement for the canonical DOCX.
- `TROIKA_CAPABILITY_RESTORATION_PLAN.md` — capability restoration detail when that work is explicitly in scope.
- `TROIKA_CLOSED_BETA_SETUP.md` — closed-beta provisioning/deployment runbook.
- `DATA_RETENTION_AND_DELETION_POLICY.md` — retention/deletion policy and launch gates.
- `SCREEN_SNAPSHOT_THREAT_MODEL.md` — security boundary for one-frame screen analysis.
- `TROIKA_NATIVE_REBRAND_MIGRATION.md` — compatibility-safe rebrand migration.
- `TROIKA_1_0_SECTION_*_AUDIT.md` — evidence for completed/checked canonical sections. These are evidence, not new product plans.

## Removed inherited plans

During the 2026-09-27 context cleanup, six inherited Hermes implementation plans were inspected, confirmed not to be current Troika 1.0 authority, and removed from the working tree:

- legacy OpenAI-compatible API-server proposal;
- legacy streaming proposal;
- Gemini OAuth provider plan;
- Telegram DM multi-session topics plan;
- shipped s6-overlay gateway plan;
- ACP/Zed pre-edit approval plan.

They remain available through Git history if a future maintenance task needs historical context. Do not recreate or preload them just to understand Troika 1.0.

## Historical product drafts

Old monetization, offline-beta, PC-agent, Kali, self-improvement or similar drafts do not override the canonical plan. If unique current requirements are found in one, move those requirements into a current spec or tracker entry and then remove the duplicate draft; Git history is the archive.

`../PROJECT_MEMORY.md` is historical only. Current state belongs in `CURRENT.md`; the old long-form content remains in Git history.

## Rule for reusing historical material

Before implementing from old material:

1. Check the canonical 1.0 DOCX and execution tracker first.
2. Verify the relevant code/tests because old status text can be stale.
3. Copy only still-valid requirements/decisions into the current task-specific spec or tracker.
4. Do not restore obsolete pricing, architecture, unsafe tool access, personal identifiers or old release assumptions.

## Startup rule

A normal new coding session should load only:

- root `AGENTS.md`;
- `docs/CURRENT.md`.

Everything else is read on demand.
