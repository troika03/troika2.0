# Troika — current state

Last reconciled: 2026-09-27.

This is the **only startup status file**. Keep it short, current and verified. It is a snapshot, not a changelog; Git history stores old states.

## Canonical position

Troika 1.0 is implemented against `Troika_1.0_Launch_Plan_Final_Updated.docx`, top-to-bottom by complete sections. The execution tracker is the canonical progress checklist.

- Sections **1–6: verified complete**.
- Section **7: next incomplete canonical block** — sales site and account.
- Sections **8–15: not yet complete**.
- Section **16: partial** — compatibility-safe rebrand work exists.
- Sections **17–20: not yet complete**.

Unless the product owner explicitly asks for a side task, continue from section 7.

## Verified implementation snapshot

### Product/security foundation

- owner/device-scoped product auth and revocable device tokens;
- owner checks for runs, account data, memories, artifacts and assistant data;
- entitlement/usage ledger baseline plus owner-visible `GET /v1/subscription`;
- privacy-safe audit events and reviewed hosted-product tool boundary;
- account export/deletion and retention for current local SQLite/filesystem stores;
- production object-storage lifecycle, backup deletion/restore scrub and recovery rehearsal are still open launch gates.

### Files and memory

- private artifact store and DOCX/PDF/PPTX generation are connected to the product API/client flow;
- owner-scoped memory CRUD exists and Android can view/create/edit/delete memory;
- current export/deletion paths include these local product stores.

### Tasks / proactivity

- owner-scoped projects, tasks, notes and inbox exist;
- gateway runs a background deterministic event engine for due/follow-up in-app events;
- notification preferences and quiet hours gate delivery;
- Android Assistant Hub reads the inbox, tasks/projects and preferences and can mark inbox messages read;
- external push/background delivery outside the in-app inbox is not a completed production path.

### Clients

- Android canonical section 5 is verified; recent work includes local/offline commands and wake-flow handling.
- Windows canonical section 6 is verified with Compact Assistant, Command Center, global hotkey, allowlisted local actions, file actions and one-time approved screen analysis.
- arbitrary autonomous GUI/shell control is not part of normal hosted product mode.

## Context cleanup status

- `AGENTS.md` is a short startup guide instead of the inherited Hermes handbook.
- `PROJECT_MEMORY.md` is a small historical pointer; normal sessions do not load the old long-form memory.
- `PLAN_INDEX.md` defines authority and read-on-demand documents.
- six inherited Hermes plan files were removed after reference checks.
- five conflicting/stale Troika drafts were removed: old monetization, offline-beta, PC-agent, improvement and Kali workspace plans.
- removed material remains available in Git history; it is not startup context.

## Immediate next canonical work — section 7

Verify/build the sales/account surface from the launch plan: landing, features, pricing, downloads, account, help/status, privacy/terms/refunds and activation funnel.

## Known boundaries

- No cross-user memory/files/runs/actions.
- No hidden camera/screen/mic access.
- External-effect actions require explicit approval and audit.
- PC control is not a default hosted cloud tool.
- Historical Hermes capability may remain in code behind flags; code presence does not make it a Troika 1.0 product promise.

## Handoff discipline

After meaningful work, update only: current canonical section, verified implementation change, checks actually run, blockers/known failures and exact next safe step.
