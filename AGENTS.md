# Troika — lean agent guide

This is the only mandatory repository guide for a new coding session. Keep it short.

## 1. Session startup

1. Work only in `D:\troika-product` for Troika product changes. `D:\troikahermes` is read-only legacy/reference material.
2. Read `docs/CURRENT.md`.
3. Read other documents only when the task needs them; use the map below.
4. Inspect actual code/tests before trusting old status text.

Do **not** preload the launch DOCX, all plans, `PROJECT_MEMORY.md`, or the inherited Hermes handbook on every session.

Repository: `https://github.com/troika03/troika2.0.git`.

## 2. Authority order

When documents disagree:

1. Explicit new decision from the product owner.
2. `docs/Troika_1.0_Launch_Plan_Final_Updated.docx` — canonical 1.0 scope, UX, pricing, release order and Definition of Done.
3. `docs/TROIKA_1_0_EXECUTION_TRACKER.md` — ordered progress against the DOCX.
4. `docs/CURRENT.md` — compact current implementation truth and next step.
5. `docs/ARCHITECTURE.md` — stable component/boundary map.
6. Task-specific policies, audits, migrations and runbooks.
7. Git history / removed drafts — historical evidence only.

Never let historical material silently override a higher source.

## 3. Product invariants

- Troika 1.0 is a Russian voice-first personal AI assistant for Android and Windows; chat is secondary.
- Normal users see one Troika, not model/provider/tool/worker choices.
- Hosted subscription is the canonical 1.0 direction. BYOK stays Advanced.
- Canonical target plans are Free, Plus 790 RUB/month and Pro 1,490 RUB/month; local commands do not consume AI credits.
- One owner-scoped Run may use up to three specialist workers internally. Do not expose separate product runtimes for delegate/MoA/Kanban/job_runner.
- Actions with external effects require clear one-time approval and audit.
- Multi-tenancy/privacy are P0: no shared secrets, shared personal memory, personal hard-coded product identities or public plaintext HTTP in production.
- PC control is a local Troika Companion capability, not a default cloud tool.
- User history, memory, tasks, settings and artifact index are local encrypted account data; cross-device continuation is E2EE and the server should keep only opaque ciphertext plus minimal routing metadata.
- Do not invent production hosts, credentials or infrastructure facts.
- Never commit secrets, access tokens, passwords or private user content.

## 4. Execution rule

The 1.0 plan is executed top-to-bottom by complete sections. Continue from the first incomplete canonical section unless the owner explicitly asks for a side task.

Before marking an item complete:

- read the relevant DOCX/tracker acceptance block;
- inspect the implementation;
- run the narrowest meaningful tests/builds;
- record only what was actually verified;
- update `docs/CURRENT.md` and, when canonical progress changes, `docs/TROIKA_1_0_EXECUTION_TRACKER.md`.

`docs/CURRENT.md` is a snapshot, not a diary. Replace stale facts instead of appending history.

## 5. Read-on-demand map

| Need | Read |
|---|---|
| Current task / handoff | `docs/CURRENT.md` |
| Component boundaries / data flow | `docs/ARCHITECTURE.md` |
| Decide 1.0 scope, UX, price or release acceptance | launch DOCX + relevant tracker section |
| Check ordered 1.0 progress | `docs/TROIKA_1_0_EXECUTION_TRACKER.md` |
| Product/security implementation detail | `PRODUCTIZATION_PLAN.md` |
| Restore voice/device/vision/proactive capabilities | `docs/TROIKA_CAPABILITY_RESTORATION_PLAN.md` |
| Closed-beta provisioning/deployment | `docs/TROIKA_CLOSED_BETA_SETUP.md` |
| Retention/deletion | `docs/DATA_RETENTION_AND_DELETION_POLICY.md` |
| Screen snapshot security | `docs/SCREEN_SNAPSHOT_THREAT_MODEL.md` |
| Document authority / cleanup history | `docs/PLAN_INDEX.md` |

Removed historical plans stay in Git history and are not startup context.

## 6. Main code areas

- `troika_product/` — product auth, ownership, entitlements, usage and product data.
- `gateway/` — API, runs, events, approvals and client integration.
- `tools/` — internal capabilities; hosted product mode must use the reviewed allowlist.
- `hermes-android/` — shared Flutter Android/Windows client; legacy directory name.
- `docs/` — canonical plan, tracker, policies, audits and task-specific references.
- `run_agent.py`, `model_tools.py`, `toolsets.py` — inherited Hermes runtime internals.

## 7. Useful checks

Gateway dev entry:

```bash
python cli.py --gateway
python stt_proxy_server.py
curl http://localhost:8642/health
```

Android/Flutter:

```bash
cd hermes-android
flutter test
flutter analyze --no-fatal-infos
flutter build apk --debug
```

Run focused Python pytest/ruff/compile checks for the touched area first; broaden only when warranted.

## 8. End-of-task handoff

Keep `docs/CURRENT.md` small and sufficient for the next session:

- current canonical section;
- what changed;
- what was verified;
- blockers/known failures;
- exact next safe step.

Do not copy long logs, full plans, large code excerpts or generic Hermes docs into startup context.
