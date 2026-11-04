import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;
import 'dart:math';
import 'package:flutter/services.dart' show MethodChannel;
import 'package:flutter/foundation.dart' show ValueListenable, ValueNotifier;
import 'package:shared_preferences/shared_preferences.dart';
import '../services/reminder_delivery_service.dart';

/// Настройки подключения к Troika API Server.
class TroikaConfig {
  /// Internal diagnostics remain available for explicit developer builds, but
  /// are never part of the normal Troika product UI.
  static const bool developerDiagnosticsEnabled = bool.fromEnvironment(
    'TROIKA_DEVELOPER_DIAGNOSTICS',
    defaultValue: false,
  );

  /// Closed-beta screen snapshot stays absent from normal product builds.
  static const bool screenSnapshotBetaEnabled = bool.fromEnvironment(
    'TROIKA_SCREEN_SNAPSHOT_BETA',
    defaultValue: false,
  );

  static const String _keyServerUrl = 'troika_server_url';
  static const String _legacyKeyServerUrl = 'hermes_server_url';
  static const String _keyApiKey = 'troika_api_key';
  static const String _keyAccessTokenExpiresAt =
      'troika_access_token_expires_at';
  static const String _keyNativeIdentityRevision =
      'troika_native_identity_revision';
  static const String _legacyKeyApiKey = 'hermes_api_key';
  static const String _keyAccountEmail = 'troika_account_email';
  static const String _keyGroqKey = 'troika_groq_key';
  static const String _legacyKeyGroqKey = 'hermes_groq_key';
  static const String _keyModel = 'troika_model';
  static const String _legacyKeyModel = 'hermes_model';
  static const String _keyVoiceEnabled = 'troika_voice_enabled';
  static const String _legacyKeyVoiceEnabled = 'hermes_voice_enabled';
  static const String _keyWakeWordEnabled = 'troika_wake_word_enabled';
  static const String _legacyKeyWakeWordEnabled = 'hermes_wake_word_enabled';
  static const String _keyThemeMode = 'troika_theme_mode';
  static const String _keyInterfaceAccent = 'troika_interface_accent';
  static const String _keyTextScale = 'troika_text_scale';
  static const String _keyLanguage = 'troika_language';
  static const String _keyWindowsHotkey = 'troika_windows_hotkey';
  static const String _keyWindowsAlwaysOnTop = 'troika_windows_always_on_top';
  static const String _keyOnboardingDone = 'troika_onboarding_done';
  static const String _legacyKeyOnboardingDone = 'hermes_onboarding_done';
  static const String _keySessionKey = 'troika_session_key';
  static const String _legacyKeySessionKey = 'hermes_session_key';
  static const String _keySessionId = 'troika_session_id';
  static const String _legacyKeySessionId = 'hermes_session_id';
  static const String _keyLocationContextEnabled =
      'troika_location_context_enabled';
  static const String _legacyKeyLocationContextEnabled =
      'hermes_location_context_enabled';
  static const String _keyPhoneControlEnabled = 'troika_phone_control_enabled';
  static const String _legacyKeyPhoneControlEnabled =
      'hermes_phone_control_enabled';
  static const String _keyBrandMigrationVersion =
      'troika_brand_migration_version';
  static const int _brandMigrationVersion = 1;
  static const String _keyHostedEndpointMigrationVersion =
      'troika_hosted_endpoint_migration_version';
  static const int _hostedEndpointMigrationVersion = 2;

  // Дефолтные значения.
  // Product builds receive the shared account API through TROIKA_SERVER_URL on
  // every platform. Developer desktop builds without that define keep the local
  // gateway default for PC tools. A saved explicit URL still wins.
  static const String _packagedServerUrl = String.fromEnvironment(
    'TROIKA_SERVER_URL',
    defaultValue: '',
  );
  static String get defaultServerUrl {
    final packagedEndpoint = _packagedServerUrl.trim();
    if (packagedEndpoint.isNotEmpty) return packagedEndpoint;
    return (Platform.isAndroid || Platform.isIOS)
        ? ''
        : 'http://127.0.0.1:8642';
  }

  static const String defaultApiKey = '';
  static const String defaultModel =
      ''; // пустая строка = использует модель из конфига на PC

  static late SharedPreferences _prefs;
  static late String _sessionKey;
  static late String _sessionId;

  static final _voiceRevision = ValueNotifier<int>(0);
  static bool _voiceSessionChanging = false;
  static int _voiceIdentityOperation = 0;
  static ValueListenable<int> get voiceIdentityChanges => _voiceRevision;
  static int get voiceIdentityRevision => _voiceRevision.value;
  static bool get voiceSessionAvailable => signedIn && !_voiceSessionChanging;

  static int _beginVoiceIdentityChange() {
    _voiceSessionChanging = true;
    final operation = ++_voiceIdentityOperation;
    _voiceRevision.value++;
    return operation;
  }

  static void _finishVoiceIdentityChange(int operation) {
    if (operation != _voiceIdentityOperation) return;
    _voiceSessionChanging = false;
    _voiceRevision.value++;
  }

  static Future<void> _setVoiceServerUrl(String url) async {
    final operation = _beginVoiceIdentityChange();
    try {
      if (Platform.isAndroid) {
        await _setNativeConnection('setAccountServerUrl', url);
      } else {
        await _setStringCompat(_keyServerUrl, _legacyKeyServerUrl, url);
      }
      _finishVoiceIdentityChange(operation);
    } catch (_) {
      // A failed identity change cannot resume audio authorized for the old one.
    }
  }

  static Future<void> _setVoiceApiKey(String key) async {
    final operation = _beginVoiceIdentityChange();
    try {
      if (Platform.isAndroid) {
        await _setNativeConnection('setAccountApiKey', key);
      } else {
        await _setStringCompat(_keyApiKey, _legacyKeyApiKey, key);
      }
      _finishVoiceIdentityChange(operation);
    } catch (_) {
      // Settings replacement is a new credential, unlike same-owner refresh.
    }
  }

  static Future<void> _setNativeConnection(String method, String value) async {
    final saved = await const MethodChannel(
      'com.troika.hermes/background',
    ).invokeMethod<bool>(method, {'value': value});
    if (saved != true) throw StateError('Не удалось сохранить подключение.');
    await reloadAccountSession();
  }

  static Future<void> init() async {
    _prefs = await SharedPreferences.getInstance();
    await _migrateLegacyPreferences();
    await _migrateHostedEndpoint();
    _sessionKey = _prefs.getString(_keySessionKey)?.trim() ?? '';
    if (_sessionKey.isEmpty) {
      _sessionKey = 'mobile-${_newOpaqueId()}';
      await _setStringCompat(_keySessionKey, _legacyKeySessionKey, _sessionKey);
    }
    _sessionId = _prefs.getString(_keySessionId)?.trim() ?? '';
    if (_sessionId.isEmpty) {
      // Mobile keeps one continuous private conversation per installation, so
      // the transcript and memory scopes deliberately use the same opaque ID.
      _sessionId = _sessionKey;
      await _setStringCompat(_keySessionId, _legacyKeySessionId, _sessionId);
    }
    _voiceSessionChanging = false;
    _voiceRevision.value++;
  }

  static Future<void> _migrateLegacyPreferences() async {
    if ((_prefs.getInt(_keyBrandMigrationVersion) ?? 0) >=
        _brandMigrationVersion) {
      return;
    }
    await _copyString(_keyServerUrl, _legacyKeyServerUrl);
    await _copyString(_keyApiKey, _legacyKeyApiKey);
    await _copyString(_keyGroqKey, _legacyKeyGroqKey);
    await _copyString(_keyModel, _legacyKeyModel);
    await _copyString(_keySessionKey, _legacyKeySessionKey);
    await _copyString(_keySessionId, _legacyKeySessionId);
    await _copyBool(_keyVoiceEnabled, _legacyKeyVoiceEnabled);
    await _copyBool(_keyWakeWordEnabled, _legacyKeyWakeWordEnabled);
    await _copyBool(_keyOnboardingDone, _legacyKeyOnboardingDone);
    await _copyBool(
      _keyLocationContextEnabled,
      _legacyKeyLocationContextEnabled,
    );
    await _copyBool(_keyPhoneControlEnabled, _legacyKeyPhoneControlEnabled);
    await _prefs.setInt(_keyBrandMigrationVersion, _brandMigrationVersion);
  }

  static Future<void> _migrateHostedEndpoint() async {
    final endpoint = _packagedServerUrl.trim();
    if (endpoint.isEmpty ||
        (_prefs.getInt(_keyHostedEndpointMigrationVersion) ?? 0) >=
            _hostedEndpointMigrationVersion) {
      return;
    }

    final currentUrl = _prefs.getString(_keyServerUrl)?.trim() ?? '';
    final accountEmail =
        _prefs.getString(_keyAccountEmail)?.trim().toLowerCase() ?? '';
    final legacyBetaAccount = accountEmail.endsWith('@beta.troika.local');
    final legacyLocalDesktop =
        !Platform.isAndroid &&
        !Platform.isIOS &&
        accountEmail.isEmpty &&
        (currentUrl == 'http://127.0.0.1:8642' ||
            currentUrl == 'http://localhost:8642');

    if (currentUrl.isEmpty || legacyBetaAccount || legacyLocalDesktop) {
      await _setStringCompat(_keyServerUrl, _legacyKeyServerUrl, endpoint);
    }
    if (legacyBetaAccount) {
      await _prefs.remove(_keyAccountEmail);
      await _removeCompat(_keyApiKey, _legacyKeyApiKey);
      await _setBoolCompat(
        _keyPhoneControlEnabled,
        _legacyKeyPhoneControlEnabled,
        false,
      );
      await _setBoolCompat(
        _keyLocationContextEnabled,
        _legacyKeyLocationContextEnabled,
        false,
      );
      await _setBoolCompat(
        _keyWakeWordEnabled,
        _legacyKeyWakeWordEnabled,
        false,
      );
      await _removeCompat(_keySessionKey, _legacyKeySessionKey);
      await _removeCompat(_keySessionId, _legacyKeySessionId);
    }
    await _prefs.setInt(
      _keyHostedEndpointMigrationVersion,
      _hostedEndpointMigrationVersion,
    );
  }

  static Future<void> _copyString(String key, String legacyKey) async {
    if (_prefs.containsKey(key)) return;
    final value = _prefs.getString(legacyKey);
    if (value != null) await _prefs.setString(key, value);
  }

  static Future<void> _copyBool(String key, String legacyKey) async {
    if (_prefs.containsKey(key)) return;
    final value = _prefs.getBool(legacyKey);
    if (value != null) await _prefs.setBool(key, value);
  }

  static Future<bool> _setStringCompat(
    String key,
    String legacyKey,
    String value,
  ) async {
    final stored = await _prefs.setString(key, value);
    await _prefs.setString(legacyKey, value);
    return stored;
  }

  static Future<bool> _setBoolCompat(
    String key,
    String legacyKey,
    bool value,
  ) async {
    final stored = await _prefs.setBool(key, value);
    await _prefs.setBool(legacyKey, value);
    return stored;
  }

  static Future<void> _removeCompat(String key, String legacyKey) async {
    await _prefs.remove(key);
    await _prefs.remove(legacyKey);
  }

  static String _newOpaqueId() {
    final random = Random.secure();
    final bytes = List<int>.generate(24, (_) => random.nextInt(256));
    return base64UrlEncode(bytes).replaceAll('=', '');
  }

  static String get serverUrl =>
      _prefs.getString(_keyServerUrl) ?? defaultServerUrl;

  static set serverUrl(String url) {
    if (url == serverUrl) {
      unawaited(_setStringCompat(_keyServerUrl, _legacyKeyServerUrl, url));
    } else {
      unawaited(_setVoiceServerUrl(url));
    }
  }

  static String get apiKey => _prefs.getString(_keyApiKey) ?? defaultApiKey;

  static set apiKey(String key) {
    if (key == apiKey) {
      unawaited(_setStringCompat(_keyApiKey, _legacyKeyApiKey, key));
    } else {
      unawaited(_setVoiceApiKey(key));
    }
  }

  static String get accountEmail =>
      _prefs.getString(_keyAccountEmail)?.trim() ?? '';

  static bool get signedIn =>
      accountEmail.isNotEmpty && apiKey.startsWith('trk_live_');

  static Future<void> saveAccount({
    required String email,
    required String token,
    String refreshToken = '',
    double accessExpiresAt = 0,
    String homeSessionId = '',
    bool replaceIdentity = false,
    int? expectedNativeRevision,
  }) async {
    final changesIdentity =
        replaceIdentity ||
        !signedIn ||
        _voiceSessionChanging ||
        email.trim().toLowerCase() != accountEmail ||
        (homeSessionId.trim().isNotEmpty && homeSessionId.trim() != _sessionId);
    final operation = changesIdentity ? _beginVoiceIdentityChange() : null;
    var saved = false;
    try {
      if (Platform.isAndroid) {
        final published =
            await const MethodChannel(
              'com.troika.hermes/background',
            ).invokeMethod<bool>('saveAccountSession', {
              'email': email.trim().toLowerCase(),
              'token': token.trim(),
              'refreshToken': refreshToken,
              'expiresAtMillis': (accessExpiresAt * 1000).round(),
              'sessionId': homeSessionId.trim(),
              'replaceIdentity': replaceIdentity,
              'expectedGeneration':
                  expectedNativeRevision ?? nativeIdentityRevision,
            });
        if (published != true) {
          throw StateError(
            'Не удалось безопасно сохранить вход. Повтори вход в аккаунт.',
          );
        }
        await reloadAccountSession();
        saved = true;
        return;
      }
      await _prefs.setString(_keyAccountEmail, email.trim().toLowerCase());
      await _setStringCompat(_keyApiKey, _legacyKeyApiKey, token.trim());
      if (accessExpiresAt > 0) {
        await _prefs.setInt(
          _keyAccessTokenExpiresAt,
          (accessExpiresAt * 1000).round(),
        );
      }
      if (refreshToken.isNotEmpty) await storeRefreshToken(refreshToken);
      final sharedSession = homeSessionId.trim();
      if (sharedSession.isNotEmpty) {
        _sessionKey = sharedSession;
        _sessionId = sharedSession;
        await _setStringCompat(
          _keySessionKey,
          _legacyKeySessionKey,
          sharedSession,
        );
        await _setStringCompat(
          _keySessionId,
          _legacyKeySessionId,
          sharedSession,
        );
      }

      saved = true;
    } finally {
      if (saved && operation != null) _finishVoiceIdentityChange(operation);
    }
  }

  static DateTime? get accessTokenExpiresAt {
    final milliseconds = _prefs.getInt(_keyAccessTokenExpiresAt);
    return milliseconds == null
        ? null
        : DateTime.fromMillisecondsSinceEpoch(milliseconds, isUtc: true);
  }

  /// Native background voice can rotate credentials without a Flutter engine.
  static Future<void> reloadAccountSession() async {
    final previousRevision = nativeIdentityRevision;
    await _prefs.reload();
    _sessionKey = _prefs.getString(_keySessionKey)?.trim() ?? '';
    _sessionId = _prefs.getString(_keySessionId)?.trim() ?? _sessionKey;
    if (nativeIdentityRevision != previousRevision) _voiceRevision.value++;
  }

  static int get nativeIdentityRevision =>
      _prefs.getInt(_keyNativeIdentityRevision) ?? 0;

  static Future<void> _clearNativeAccountSession(
    String mode,
    int operation,
  ) async {
    if (!Platform.isAndroid) return;
    ReminderDeliveryService.instance.invalidate();
    final cleared = await const MethodChannel('com.troika.hermes/background')
        .invokeMethod<bool>('clearAccountSession', {
          'mode': mode,
          'expectedGeneration': nativeIdentityRevision,
        });
    if (operation != _voiceIdentityOperation) return;
    if (cleared != true) throw StateError('Не удалось удалить данные входа.');
    await reloadAccountSession();
  }

  static Future<bool> storeRefreshToken(String token) async {
    if ((!Platform.isAndroid && !Platform.isWindows) || token.isEmpty) {
      return false;
    }
    try {
      const platform = MethodChannel('com.troika.hermes/background');
      return await platform.invokeMethod<bool>('storeRefreshToken', {
            'token': token,
          }) ??
          false;
    } catch (_) {
      return false;
    }
  }

  static Future<String> getRefreshToken() async {
    if (!Platform.isAndroid && !Platform.isWindows) return '';
    try {
      const platform = MethodChannel('com.troika.hermes/background');
      return (await platform.invokeMethod<String>('getRefreshToken')) ?? '';
    } catch (_) {
      return '';
    }
  }

  static Future<void> clearRefreshToken() async {
    await _prefs.remove(_keyAccessTokenExpiresAt);
    if (!Platform.isAndroid && !Platform.isWindows) return;
    try {
      const platform = MethodChannel('com.troika.hermes/background');
      await platform.invokeMethod<void>('clearRefreshToken');
    } catch (_) {}
  }

  static Future<void> signOut() async {
    final operation = _beginVoiceIdentityChange();
    if (Platform.isAndroid) {
      return _clearNativeAccountSession('signout', operation);
    }
    await ReminderDeliveryService.instance.clear();
    await setPhoneControlEnabled(false);
    await clearRefreshToken();
    await _prefs.remove(_keyAccountEmail);
    await _removeCompat(_keyApiKey, _legacyKeyApiKey);
  }

  static String get groqKey => _prefs.getString(_keyGroqKey) ?? '';

  static set groqKey(String key) =>
      _setStringCompat(_keyGroqKey, _legacyKeyGroqKey, key);

  static String get model => _prefs.getString(_keyModel) ?? defaultModel;

  static set model(String m) => _setStringCompat(_keyModel, _legacyKeyModel, m);

  static bool get voiceEnabled => _prefs.getBool(_keyVoiceEnabled) ?? true;

  static set voiceEnabled(bool v) =>
      _setBoolCompat(_keyVoiceEnabled, _legacyKeyVoiceEnabled, v);

  static bool get wakeWordEnabled =>
      _prefs.getBool(_keyWakeWordEnabled) ?? false;

  static set wakeWordEnabled(bool v) =>
      _setBoolCompat(_keyWakeWordEnabled, _legacyKeyWakeWordEnabled, v);

  static Future<void> saveWakeWordEnabled(bool value) async {
    await _setBoolCompat(_keyWakeWordEnabled, _legacyKeyWakeWordEnabled, value);
  }

  static String get themeMode => _prefs.getString(_keyThemeMode) ?? 'system';

  static Future<void> setThemeMode(String value) async {
    await _prefs.setString(_keyThemeMode, value);
  }

  static String get interfaceAccent =>
      _prefs.getString(_keyInterfaceAccent) ?? 'mint';

  static Future<void> setInterfaceAccent(String value) async {
    const choices = {'mint', 'amber', 'teal', 'blue', 'violet', 'rose', 'green'};
    if (choices.contains(value)) {
      await _prefs.setString(_keyInterfaceAccent, value);
    }
  }

  static double get textScale => _prefs.getDouble(_keyTextScale) ?? 1.0;

  static Future<void> setTextScale(double value) async {
    await _prefs.setDouble(_keyTextScale, value.clamp(0.9, 1.25));
  }

  static String get language => _prefs.getString(_keyLanguage) ?? 'ru';

  static Future<void> setLanguage(String value) async {
    await _prefs.setString(_keyLanguage, value);
  }

  static String get windowsHotkey =>
      _prefs.getString(_keyWindowsHotkey) ?? 'ctrlAltSpace';

  static Future<void> setWindowsHotkey(String value) async {
    await _prefs.setString(_keyWindowsHotkey, value);
  }

  static bool get windowsAlwaysOnTop =>
      _prefs.getBool(_keyWindowsAlwaysOnTop) ?? false;

  static Future<void> setWindowsAlwaysOnTop(bool value) async {
    await _prefs.setBool(_keyWindowsAlwaysOnTop, value);
  }

  /// Пройден ли экран первичной настройки (онбординг разрешений).
  static bool get onboardingDone => _prefs.getBool(_keyOnboardingDone) ?? false;

  static set onboardingDone(bool v) =>
      _setBoolCompat(_keyOnboardingDone, _legacyKeyOnboardingDone, v);

  /// Explicit user consent for sending GPS/Wi-Fi/Bluetooth context to server.
  /// System location permission alone never enables data transfer.
  static bool get locationContextEnabled =>
      _prefs.getBool(_keyLocationContextEnabled) ?? false;

  static Future<void> setLocationContextEnabled(bool value) async {
    await _setBoolCompat(
      _keyLocationContextEnabled,
      _legacyKeyLocationContextEnabled,
      value,
    );
  }

  /// Explicit consent for opening the authenticated phone-command channel.
  /// It is disabled by default and can be revoked at any time.
  static bool get phoneControlEnabled =>
      _prefs.getBool(_keyPhoneControlEnabled) ?? false;

  static Future<void> setPhoneControlEnabled(bool value) async {
    await _setBoolCompat(
      _keyPhoneControlEnabled,
      _legacyKeyPhoneControlEnabled,
      value,
    );
    if (!Platform.isAndroid) return;
    try {
      const platform = MethodChannel('com.troika.hermes/background');
      await platform.invokeMethod<void>('refreshPhoneBridge');
    } catch (_) {}
  }

  /// URL для WebSocket канала команд (управление телефоном)
  static String get phoneCommandsWsUrl =>
      '${serverUrl.replaceFirst('http', 'ws')}/v1/phone/commands';

  /// URL для Chat Completions API
  static String get chatCompletionsUrl => '$serverUrl/v1/chat/completions';

  /// Product voice shares the authenticated API origin, including HTTPS/port.
  /// Legacy local installations keep their separate STT proxy.
  static Uri get transcriptionUri {
    final base = Uri.parse(serverUrl);
    final sttBase = apiKey.startsWith('trk_live_')
        ? base
        : base.replace(port: 8643);
    return sttBase.replace(
      path:
          '${base.path.replaceAll(RegExp(r'/+$'), '')}/v1/audio/transcriptions',
      query: null,
      fragment: null,
    );
  }

  /// URL structured runs (стриминг мыслей и вызовов через SSE)
  static String get runsUrl => '$serverUrl/v1/runs';

  /// Личные документы текущего аккаунта Тройки.
  static String get artifactsUrl => '$serverUrl/v1/artifacts';

  /// Подтверждаемое удаление product-аккаунта и серверных данных.
  static String get accountUrl => '$serverUrl/v1/account';

  static String get registrationUrl => '$serverUrl/v1/auth/register';

  static String get loginUrl => '$serverUrl/v1/auth/login';

  static String get refreshUrl => '$serverUrl/v1/auth/refresh';

  static String get upgradeTokenUrl => '$serverUrl/v1/auth/upgrade-token';

  static String get logoutAllUrl => '$serverUrl/v1/auth/logout-all';

  /// Архив всех переносимых данных текущего product-аккаунта.
  static String get accountExportUrl => '$serverUrl/v1/account/export';

  /// Устройства текущего product-аккаунта.
  static String get accountDevicesUrl => '$serverUrl/v1/account/devices';

  /// Текущий тариф и доступный дневной лимит владельца.
  static String get subscriptionUrl => '$serverUrl/v1/subscription';

  /// Remove credentials after this installation revokes its own device.
  /// Keep non-sensitive local preferences, clear account-bound consents, and
  /// rotate the conversation identity so a later sign-in cannot reuse the
  /// revoked device's server-linked session.
  static Future<void> clearRevokedDevice() async {
    final operation = _beginVoiceIdentityChange();
    if (Platform.isAndroid) {
      return _clearNativeAccountSession('revoke', operation);
    }
    await ReminderDeliveryService.instance.clear();
    await setPhoneControlEnabled(false);
    await clearRefreshToken();
    await _setBoolCompat(_keyWakeWordEnabled, _legacyKeyWakeWordEnabled, false);
    await _setBoolCompat(
      _keyLocationContextEnabled,
      _legacyKeyLocationContextEnabled,
      false,
    );
    await _removeCompat(_keyApiKey, _legacyKeyApiKey);
    await _prefs.remove(_keyAccountEmail);
    _sessionKey = 'mobile-${_newOpaqueId()}';
    _sessionId = _sessionKey;
    await _setStringCompat(_keySessionKey, _legacyKeySessionKey, _sessionKey);
    await _setStringCompat(_keySessionId, _legacyKeySessionId, _sessionId);
  }

  /// Remove credentials and server-linked state after deletion was accepted.
  static Future<void> clearDeletedAccount() async {
    final operation = _beginVoiceIdentityChange();
    if (Platform.isAndroid) {
      return _clearNativeAccountSession('delete', operation);
    }
    await ReminderDeliveryService.instance.clear();
    await setPhoneControlEnabled(false);
    await clearRefreshToken();
    await _setBoolCompat(_keyWakeWordEnabled, _legacyKeyWakeWordEnabled, false);
    await _setBoolCompat(
      _keyLocationContextEnabled,
      _legacyKeyLocationContextEnabled,
      false,
    );
    await _setBoolCompat(_keyOnboardingDone, _legacyKeyOnboardingDone, false);
    await _removeCompat(_keyApiKey, _legacyKeyApiKey);
    await _prefs.remove(_keyAccountEmail);
    await _removeCompat(_keySessionKey, _legacyKeySessionKey);
    await _removeCompat(_keySessionId, _legacyKeySessionId);
    _sessionKey = '';
    _sessionId = '';
  }

  /// Единая сессия для голоса и текста конкретной установки приложения.
  /// Идентификаторы генерируются случайно один раз и не разделяются между людьми.
  static String get sessionId => _sessionId;
  static String get sessionKey => _sessionKey;

  /// Headers для запросов к Troika.
  static Map<String, String> get headers {
    final key = apiKey;
    return {
      'Content-Type': 'application/json',
      if (key.isNotEmpty) 'Authorization': 'Bearer $key',
    };
  }

  /// Headers для чата — те же + привязка к общей сессии (голос+текст).
  ///
  /// НЕ включает legacy X-Hermes-Device-Context: он собирается асинхронно через
  /// Kotlin MethodChannel (см. [chatHeadersAsync]). Для не-Android платформ
  /// (Windows/Linux/macOS) device context недоступен — там просто эти headers.
  static Map<String, String> get chatHeaders {
    return {
      ...headers,
      'X-Hermes-Session-Key': sessionKey,
      'X-Hermes-Session-Id': sessionId,
    };
  }

  /// IANA time zone reported by Android, for example Europe/Moscow.
  static Future<String?> deviceTimeZone() async {
    if (!Platform.isAndroid) return null;
    try {
      const platform = MethodChannel('com.troika.hermes/background');
      final value = (await platform.invokeMethod<String>(
        'getTimeZoneId',
      ))?.trim();
      if (value == null || value.isEmpty || value.length > 100) return null;
      if (value != 'UTC' && !value.contains('/')) return null;
      return value;
    } catch (_) {
      return null;
    }
  }

  /// Полные headers для chat-запросов, включая контекст устройства, если он
  /// доступен и разрешён на стороне Android.
  ///
  /// На не-Android — фаллбэк на [chatHeaders].
  static Future<Map<String, String>> chatHeadersAsync() async {
    final base = chatHeaders;
    if (!Platform.isAndroid) return base;
    final timezone = await deviceTimeZone();
    if (timezone != null) base['X-Troika-Time-Zone'] = timezone;
    if (!locationContextEnabled) {
      // Server removes its transient cache on this signal in product mode.
      base['X-Troika-Device-Context-Consent'] = 'revoked';
      return base;
    }
    base['X-Troika-Device-Context-Consent'] = 'granted';
    try {
      const platform = MethodChannel('com.troika.hermes/background');
      final ctx = await platform.invokeMethod<String>('getDeviceContext');
      if (ctx != null && ctx.isNotEmpty && ctx.length <= 4096) {
        base['X-Hermes-Device-Context'] = ctx;
      }
    } catch (_) {}
    return base;
  }
}
