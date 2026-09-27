# Troika — architecture map

This file is a compact, stable map of the product. It is not a full code guide.
Read code in the touched area for implementation details.

## Product shape

```text
Android / Windows Flutter client
            |
         HTTPS/WSS
            |
       Troika gateway
            |
 auth + device + ownership + entitlement
            |
       owner-scoped Run
            |
 router + reviewed tools + approval
            |
 result / artifact / task / memory
```

Normal users interact with one Troika. Model names, provider routing, internal
tools, worker topology and hidden reasoning stay inside the runtime.

## Main areas

### `hermes-android/`
Shared Flutter client for Android and Windows. The directory name is historical.
Contains voice-first UI, account/profile/settings, tasks/files surfaces, local
platform integrations and product API client code.

### `gateway/`
Network/API edge and runtime integration: requests, streaming/events, runs,
approvals, product auth hooks, client/platform bridges and product-facing
execution paths.

### `troika_product/`
Product-domain state and policy: users, devices/tokens, ownership, entitlements,
usage, audit, retention and other owner-scoped application data.

### `tools/`
Runtime capabilities inherited from Hermes plus Troika-specific capabilities.
Code existing here does **not** imply hosted-product availability. Normal product
mode must use a reviewed allowlist and explicit approval where required.

### Runtime core

- `run_agent.py` — inherited agent loop/runtime.
- `model_tools.py` — tool discovery/dispatch glue.
- `toolsets.py` — capability grouping/visibility.
- `cli.py` — local/developer runtime entry path, including gateway startup.

These inherited files are large. Read only the relevant functions for the task;
do not preload generic Hermes internals into every session.

## Trust and ownership boundaries

### Identity

Server-side verified auth determines `user_id` and `device_id`. Client-supplied
IDs are not authorization. Session/run/file/memory access must remain scoped to
the authenticated owner.

### Device actions

A paired device is a separate trust boundary. An action that changes external
state requires a clear, one-time approval unless the canonical plan explicitly
classifies the exact local action as safe. Screen/camera observation and UI
control are separate capabilities.

### Hosted vs local capabilities

The hosted product must not inherit every Hermes/local tool. Terminal, arbitrary
server files, unrestricted computer control, self-modifying behavior and other
experimental capabilities remain excluded or gated unless a canonical section
explicitly restores them.

Windows PC control is a local companion/client capability rather than a default
cloud tool boundary.

## Data model principles

- Every personal entity is owner-scoped.
- No global personal memory or `phone-misha` identity in product mode.
- Secrets/tokens are never written to project docs, audit payloads or logs.
- Audit stores technical metadata, not prompts/message bodies/private content.
- Exact/transient device context has explicit consent and bounded retention.
- Raw screen/camera media is not a durable product record by default.

Current local retention/export/deletion support does not prove future production
object-storage or backup deletion; those require their own launch verification.

## Cross-device data direction

Canonical product decisions require local encrypted account data and E2EE sync
for continuation between Android and Windows. The sync service should handle
opaque ciphertext plus minimal routing metadata rather than plaintext personal
history. Cloud model context may exist transiently for execution but should not
become ordinary application logs/analytics/backups.

## Product run model

Troika presents one user task/run. Internally a run may route to a small number
of specialist workers, but separate Hermes concepts such as delegate/MoA/
Kanban/job_runner are not separate user-facing product runtimes for 1.0.

## Safe change checklist

When changing architecture or a boundary, check:

1. Which authenticated owner/device owns the data/action?
2. Does the change expose an inherited tool in hosted product mode?
3. Does it create an external effect requiring approval/audit?
4. Does it change what data leaves the device or how long data is retained?
5. Does it conflict with the canonical DOCX/tracker?
6. Are cross-tenant and denial/error paths tested?

For detailed productization/security choices, read `PRODUCTIZATION_PLAN.md` or a
specific policy/threat-model document only when the task requires it.
