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
- Section **7: next incomplete canonical block** — sales site and account.
- Sections **8–15: not yet complete**.
- Section **16: partial** — compatible rebrand work exists.
- Sections **17–20: not yet complete**.

Unless the product owner explicitly asks for a side task, continue from section 7.

## Context cleanup status

- `AGENTS.md` is now a short startup guide instead of the inherited Hermes handbook.
- `PROJECT_MEMORY.md` is historical only; normal sessions do not load it.
- `PLAN_INDEX.md` separates current Troika documents from inherited Hermes plans.
- `.plans/`, `plans/` and `docs/plans/` contain inherited Hermes implementation plans and are not normal startup context.
- Six inherited plans were audited and classified as historical material: legacy OpenAI API server, legacy streaming, Gemini OAuth, Telegram topics, s6 per-profile gateways, and ACP/Zed approval diffs.
- Before deleting inherited plans, verify no current build, doc, or workflow still references them. Git history remains the archive after deletion.

## Immediate next work — section 7

Build and verify the canonical sales/account surface from the launch plan:
landing, features, pricing, downloads, account, help/status, privacy/terms/refunds, and activation funnel.

## Known boundaries

- No cross-user memory/files/runs/actions.
- No hidden camera/screen/mic access.
- External-effect actions require explicit approval and audit.
- PC control is not part of the default hosted cloud toolset.
- Historical Hermes capability may remain in code behind flags; existence in the repo does not mean it belongs in Troika 1.0 UI or marketing.

## Handoff discipline

After a meaningful task, update only the facts that changed here: current canonical section, completed change, verification actually run, blockers/known failures, and exact next safe step.
