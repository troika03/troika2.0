# Troika 1.0 Section 6 Evidence Audit

Baseline: commit `243278d` (2026-09-26). Scope: the complete Word-plan section
“6. Windows-клиент”. Statuses describe the code before section 6 implementation.

This is a historical baseline. Current implementation and remaining gaps are
recorded in the [execution tracker](TROIKA_1_0_EXECUTION_TRACKER.md) and
[functional audit](TROIKA_FUNCTIONAL_AUDIT.md); “Missing” below is not today's status.

| Requirement | Baseline status | Evidence |
|---|---|---|
| Windows is not a stretched mobile layout | Partial | `lib/screens/home_screen.dart` uses a desktop sidebar and right rail at widths of 900 px or more, but there is no Windows-specific window shell or mode model. `test/home_screen_test.dart` covers only the wide responsive layout. |
| Compact Assistant and Command Center | Partial | The wide home resembles an early Command Center. Compact Assistant, native resize, pinning, hiding and mode switching are absent from Dart and `windows/runner`. |
| Configurable global hotkey | Missing | `windows/runner/flutter_window.cpp` handles only font changes. No `RegisterHotKey`, platform channel or stored Windows shortcut exists. |
| Hotkey starts recording | Missing | Recording is available through `AssistantService.startManualRecording()`, but no Windows hotkey invokes it. |
| Large microphone button and live transcript | Implemented | `StatusOrb`, `_OrbButton`, `AssistantService.liveTranscript` and the listening widget test provide the shared voice surface. |
| Current task and short result only in Compact | Missing | `_CurrentCards` already limits the home to three cards, but there is no compact window state with a stricter one-task layout. |
| File actions: Open / Show in folder | Partial | Artifact and local-document screens can open/save files. The home result card opens the files hub; no trusted Windows “show in folder” bridge is exposed. |
| Compact approval card | Implemented in shared UI | `_ApprovalCard` provides cancel and one-time approval, and `home_screen_test.dart` verifies it. It is not yet hosted in a Compact window. |
| Esc closes; repeated hotkey stops or interrupts | Missing | `AssistantService.interrupt()` exists. No desktop key binding or hotkey state machine calls it. |
| Command Center: tasks, files, history, memory, devices, plan and settings | Partial | Screens exist for assistant tasks, files, history, memory and profile/settings. Desktop navigation exposes only Today, Commands, Documents, Voice and Settings. |
| Open app, folder, file, system settings and links | Partial | `LocalCommandService._executeWindows()` has an allowlisted app map, known folders, settings URIs and web search. Arbitrary user text is not passed to a shell. Trusted result-file open/show actions are not connected to the home result. |
| Create and open a Troika result | Implemented | Local DOCX/PPTX creation, artifact screens and result routing exist and are covered by Flutter tests. |
| Basic media/system actions | Implemented | Allowlisted volume/media keys, desktop toggle, lock, battery and active-window close exist in `local_command_service.dart`. No free-form command execution is used. |
| Explicit screenshot sent to Vision with permission | Partial | An explicit screenshot phrase only opens `ms-screenclip:`. No one-time confirmation, captured image bridge or Vision request exists. Normal product builds keep legacy autonomous screen control disabled. |
| No uncontrolled autonomous GUI agent | Implemented policy | Product feature policy keeps autonomous PC control default-off; the Windows local command layer is an allowlist and does not expose arbitrary shell text. |

## Connected implementation target

Implement one Windows shell with two modes, a native configurable global
hotkey, Compact keyboard behavior, expanded Command Center navigation, trusted
file/window actions and a one-time-confirmed screenshot-to-Vision path. Preserve
the existing allowlist boundary and keep autonomous GUI control unavailable.

## Post-implementation result

| Requirement | Final status | Evidence |
|---|---|---|
| Windows is not a stretched mobile layout | Implemented | `lib/screens/home_screen.dart` provides a Windows-specific Command Center and Compact Assistant; `windows/runner/flutter_window.cpp` applies native 1280×800 and 420×560 window modes. |
| Compact Assistant and Command Center | Implemented | Compact has one orb, current status/result, pin, expand and close. Command Center keeps full work navigation. `test/home_screen_test.dart` verifies switching between both surfaces. |
| Configurable global hotkey | Implemented | `windows_shell_service.dart`, `troika_config.dart`, `interface_settings_screen.dart` and `flutter_window.cpp` persist one of three presets and register it with `RegisterHotKey(..., MOD_NOREPEAT)`. Failed changes restore the previous working shortcut. |
| Hotkey starts, stops and interrupts | Implemented | `_handleWindowsHotkey()` opens Compact and calls `startManualRecording()`, then calls `stopRecordingAndProcess()` while recording or `interrupt()` while another response is active. |
| Large microphone and live transcript | Implemented | Compact reuses `StatusOrb`, `_OrbButton`, `AssistantService.liveTranscript` and the tested shared voice state model. |
| Current task and short result in Compact | Implemented | `_CompactAssistant` renders the shared bounded current-card surface without the Command Center rails. |
| File actions: Open / Show in folder | Implemented | `LocalDocumentService.lastSavedPath`, `LocalDocumentsScreen` and the native `openPath` / `showInFolder` channel expose actions only for an existing absolute result file. |
| Compact approval and keyboard behavior | Implemented | The shared one-time `_ApprovalCard` is available in Compact; `CallbackShortcuts` maps Escape to hide and the repeated native hotkey stops or interrupts. |
| Command Center work areas | Implemented | Desktop navigation exposes Home, Tasks, Files, History and Memory; devices, account/plan and settings remain in the settings hub. |
| Promised local Windows actions | Implemented | `local_command_service.dart` retains the strict allowlist for applications, known folders, settings/links and media/system controls. Local DOCX/PPTX creation and opening remain available without arbitrary shell execution. |
| Explicit screenshot to Vision | Implemented | The screenshot phrase emits `capture_screen_for_vision`; the UI requires one-time approval, the native bridge captures and bounds a PNG of the virtual desktop, and `AssistantService.sendTextQuery()` sends the approved image to the configured AI path. |
| No uncontrolled autonomous GUI agent | Implemented | No arbitrary click/type/shell path is exposed. Legacy autonomous control remains default-off outside the normal product UI. |

## Verification

- Flutter tests: `36 passed`.
- Flutter analyze: completed with `21` existing info diagnostics and no errors.
- Windows debug build: passed; the built application launched and remained
  responsive.
- Android debug APK: built successfully after the shared Dart changes.
- Product/security Python: `129 passed, 34 deselected`.
- Website typecheck and localized production build: passed with existing
  broken-link/prebuild warnings.
- Web dashboard production build: passed with the existing bundle-size warning.
