# Troika — current state

Last reconciled: 2026-09-27.

This is the **only startup status file**. Keep it short, current and verified.
It is a snapshot, not a changelog. Git history stores old states.

## Canonical position

Troika 1.0 is being implemented strictly against
`Troika_1.0_Launch_Plan_Final_Updated.docx`, top-to-bottom by complete sections.
The execution tracker is the canonical progress checklist.

Current tracker position:

- Sections **1–6: verified complete**.
  - product vision and promise;
  - product boundaries;
  - voice-first design;
  - Android client;
  - Windows client.
- Section **7: next incomplete canonical block** — sales site and account.
- Sections **8–15: not yet complete** — plans/billing/credits, backend target
  architecture, voice/memory/agent tasks, files/documents, security/privacy,
  infrastructure/production, analytics, support/legal.
- Section **16: partial** — compatible rebrand work exists, but the ordered
  rebrand checkpoint is later in the plan.
- Sections **17–20: not yet complete** — CI/release gates, closed beta, public
  launch and final Definition of Done.

Unless the product owner explicitly asks for a side task, continue from section 7.

## What is already implemented and useful

These are implementation facts, not permission to skip later canonical gates:

### Product/security foundation

- owner/device-scoped product auth and revocable device tokens;
- session/run ownership checks;
- entitlement/usage ledger baseline and beta caps;
- privacy-safe audit events;
- reviewed hosted-product tool boundary;
- explicit device-context consent and retention;
- owner-scoped account export and deletion from current local stores;
- retention worker for current local SQLite/filesystem stores.

Production object-storage lifecycle, backup deletion/restore scrub and recovery
rehearsal are still launch gates, not completed features.

### Personal memory

- owner-scoped memory CRUD exists;
- Android can list/create/edit/delete memory;
- memory can be injected into product context with limits;
- export/account deletion cover current memory storage.

Do not claim production backup/object-storage deletion for memory until those
systems exist and are verified.

### Notifications / proactivity

- owner-scoped notification preferences and quiet-hours evaluation exist;
- automatic proactive delivery, queue/inbox delivery worker and full user flow
  are not complete just because preferences exist.

### Android

Canonical section 5 is verified. Current client includes the voice-first home,
local/on-device wake path, explicit background-wake opt-in/status, safe product
navigation/settings and local/offline command work. Recent work also touched
wake-flow/offline greeting behavior.

### Windows

Canonical section 6 is verified. Current client has Compact Assistant and
Command Center modes, configurable global hotkey, safe allowlisted Windows
operations, local document creation/opening and one-time approved screen
analysis. Arbitrary autonomous GUI control is not part of normal product mode.

## Context cleanup status

- `AGENTS.md` is now a short startup guide instead of the inherited Hermes handbook.
- `PROJECT_MEMORY.md` is historical only; normal sessions do not load it.
- `PLAN_INDEX.md` classifies current Troika docs separately from inherited Hermes plans.
- `.plans/`, `plans/` and `docs/plans/` contain inherited Hermes implementation plans and are not normal startup context.
- Do not delete an inherited plan solely because it is old; first check whether any current build, doc or workflow still references it. Git history remains the archive after deletion.

## Immediate next work — section 7

Build and verify the canonical sales/account surface from the launch plan:

- landing;
- features;
- pricing;
- downloads;
- account;
- help/status;
- privacy/terms/refunds;
- activation funnel.

Before implementing section 7, read the full section in the DOCX plus the
section-7 tracker acceptance block. Do not substitute requirements from older
monetization or offline-beta drafts.

## Known boundaries / do not accidentally regress

- No shared product API secret or static personal session identity.
- No cross-user memory/files/runs/actions.
- No hidden camera/screen/mic access.
- External-effect actions require explicit approval and audit.
- PC control is not part of the default hosted cloud toolset.
- No arbitrary terminal/shell execution from user text in normal product mode.
- Historical Hermes capability may remain in code behind flags; existence in
  the repo does not mean it belongs in Troika 1.0 UI or marketing.

## Handoff discipline

After a meaningful task, update only the facts that changed here:

1. current canonical section;
2. completed change;
3. verification actually run;
4. blockers/known failures;
5. exact next safe step.

If details need more than a few lines, put them in a task-specific audit/runbook
and link it instead of expanding this file.
