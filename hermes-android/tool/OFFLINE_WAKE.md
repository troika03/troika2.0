# Offline wake build assets

The Android application bundles Vosk Android 0.3.75, JNA 5.18.1 and the small
Russian Vosk model 0.22. Background wake detection uses local audio and requires
no runtime model download, account, API key or network connection.

Before building a fresh checkout, run from the repository root:

```powershell
python hermes-android/tool/prepare_offline_wake.py
```

The script downloads only the three pinned official artifacts in
`offline-wake.lock.json`. It checks their exact lengths and SHA-256 digests before
installing them. Use `--cache PATH --offline` to provision from an existing
verified cache, or `--project PATH` to prepare another existing Flutter project.

Generated AARs are placed under `android/app/wake-dependencies`. The 91 MB
uncompressed model and its generated per-file integrity manifest are placed
under `android/app/src/main/assets/model-wake-ru`. These generated directories and
the default download cache are excluded from Git. They are included in the APK.
Existing generated files must match the lock; the script refuses to overwrite
unknown, changed or linked files. It does not clean application data or a device.

The official model archive has no published SHA-256 in its model catalog. The
lock records the digest of the exact archive obtained over HTTPS from the
official catalog URL. Its per-file manifest is also pinned. The Vosk AAR digest
was checked against the publisher's Maven Central SHA-256; the JNA AAR was checked
against Maven Central SHA-1 in addition to the SHA-256 recorded here.

Vosk and this Russian model use Apache 2.0. JNA offers Apache 2.0 or LGPL 2.1 or
later; this application selects Apache 2.0. Notices and license texts are bundled
in `android/app/src/main/assets/wake-licenses`, and the original model README is
retained. Official sources:

- https://github.com/alphacep/vosk-android-demo/blob/master/app/build.gradle
- https://alphacephei.com/vosk/models
- https://github.com/alphacep/vosk-api/blob/master/COPYING
- https://github.com/java-native-access/jna/blob/5.18.1/LICENSE

Model and recorder memory usage, wake accuracy, standby behavior and physical
microphone sounds must be tested on the target device. A successful build alone
does not establish these properties.
