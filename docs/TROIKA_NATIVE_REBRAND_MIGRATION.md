# Troika-native rebrand migration

This migration implements the P0 repository and rebrand block from
`Troika_1.0_Launch_Plan_Final_Updated.docx`. The target is zero obsolete
product branding in UI, package names, commands, environment variables, paths,
documentation, and runtime identifiers. LICENSE, NOTICE, upstream attribution,
and explicit compatibility notes remain intact.

## Rules

- Ship small, tested slices. Do not run a repository-wide blind replacement.
- Preserve user data, tokens, consents, device identity, and notification
  settings during every migration.
- Add the Troika identifier first, read the legacy identifier as fallback, copy
  the value once, and remove the fallback only after the supported migration
  window.
- Keep protocol compatibility until server and every supported client accept
  the Troika form.
- Keep Android `applicationId` stable until a signed distribution and data
  migration decision is approved. Changing it creates a separate Android app
  and cannot read the current app sandbox.

## Completed slice: Flutter identity

- Dart package: `hermes_assistant` to `troika_assistant`.
- `HermesConfig` to `TroikaConfig` and `hermes_config.dart` to
  `troika_config.dart`.
- `HermesApiService`/`HermesApiException` to
  `TroikaApiService`/`TroikaApiException`; service file renamed accordingly.
- Root widget and conversation state use Troika names.
- User-visible native Android permission/errors and new screenshot directory
  use Troika.
- SharedPreferences now use canonical `troika_*` keys. Versioned migration
  copies installed `hermes_*` values once and temporarily dual-writes both
  forms so the current native Android service keeps working during migration.

## Temporary compatibility allowlist

These identifiers remain intentionally. Removing them without a migration can
break installed clients or erase access to existing state.

- Android `applicationId`, namespace, Kotlin package, service class names, and
  manifest component paths under `com.troika.hermes_assistant`.
- SharedPreferences keys beginning with `hermes_` or `flutter.hermes_`.
- MethodChannel `com.troika.hermes/background`.
- HTTP headers `X-Hermes-Session-Key`, `X-Hermes-Session-Id`, and
  `X-Hermes-Device-Context`.
- Existing Android notification channel IDs, intent actions, wake locks, and
  service restart targets.
- Repository directories and upstream Python modules whose rename still needs
  compatibility shims and entry-point migration.

## Next slices

1. Migrate native Android preference reads to canonical `flutter.troika_*`
   keys with legacy fallback, then retire dual-write after the supported update
   window.
2. Add Troika protocol headers server-side with legacy dual-read, then switch
   Android and retire old headers after the migration window.
3. Rename MethodChannel and native Android classes atomically. Keep manifest and
   notification compatibility aliases while supported installations migrate.
4. Migrate CLI command/package names, `TROIKA_HOME`, and `/opt/troika` with
   explicit legacy launch shims.
5. Rename web/TUI product surfaces to Troika Control Center, then clean docs and
   test fixtures. Re-run the repository inventory after every slice.
6. Decide Android package distribution migration separately. Do not change the
   current `applicationId` as a normal code rename.
