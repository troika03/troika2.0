import 'dart:convert';
import 'dart:io' show Platform;
import 'dart:math';
import 'package:flutter/services.dart' show MethodChannel;
import 'package:shared_preferences/shared_preferences.dart';

/// Настройки подключения к Hermes API Server (на сервере)
class HermesConfig {
  static const String _keyServerUrl = 'hermes_server_url';
  static const String _keyApiKey = 'hermes_api_key';
  static const String _keyGroqKey = 'hermes_groq_key';
  static const String _keyModel = 'hermes_model';
  static const String _keyVoiceEnabled = 'hermes_voice_enabled';
  static const String _keyWakeWordEnabled = 'hermes_wake_word_enabled';
  static const String _keyOnboardingDone = 'hermes_onboarding_done';
  static const String _keySessionKey = 'hermes_session_key';
  static const String _keySessionId = 'hermes_session_id';
  static const String _keyLocationContextEnabled =
      'hermes_location_context_enabled';

  // Дефолтные значения.
  // Мобильный клиент не содержит адрес общего production-сервера. Его задаёт
  // пользователь после подключения аккаунта; для закрытой разработки адрес
  // можно передать при сборке через --dart-define=TROIKA_SERVER_URL=...
  // Десктоп (Windows/Linux/macOS) — LOCAL-FIRST: локальный gateway на этой же
  // машине (127.0.0.1:8642), где живут PC-инструменты (зрение экрана, управление
  // ПК). Пользователь может сменить адрес в Настройках — сохранённое значение
  // перекрывает дефолт (см. геттер serverUrl). См. docs/TROIKA_PC_AGENT_PLAN.md.
  static const String _mobileServerUrl = String.fromEnvironment(
    'TROIKA_SERVER_URL',
    defaultValue: '',
  );
  static String get defaultServerUrl => (Platform.isAndroid || Platform.isIOS)
      ? _mobileServerUrl
      : 'http://127.0.0.1:8642';
  static const String defaultApiKey = '';
  static const String defaultModel =
      ''; // пустая строка = использует модель из конфига на PC

  static late SharedPreferences _prefs;
  static late String _sessionKey;
  static late String _sessionId;

  static Future<void> init() async {
    _prefs = await SharedPreferences.getInstance();
    _sessionKey = _prefs.getString(_keySessionKey)?.trim() ?? '';
    if (_sessionKey.isEmpty) {
      _sessionKey = 'mobile-${_newOpaqueId()}';
      await _prefs.setString(_keySessionKey, _sessionKey);
    }
    _sessionId = _prefs.getString(_keySessionId)?.trim() ?? '';
    if (_sessionId.isEmpty) {
      // Mobile keeps one continuous private conversation per installation, so
      // the transcript and memory scopes deliberately use the same opaque ID.
      _sessionId = _sessionKey;
      await _prefs.setString(_keySessionId, _sessionId);
    }
  }

  static String _newOpaqueId() {
    final random = Random.secure();
    final bytes = List<int>.generate(24, (_) => random.nextInt(256));
    return base64UrlEncode(bytes).replaceAll('=', '');
  }

  static String get serverUrl =>
      _prefs.getString(_keyServerUrl) ?? defaultServerUrl;

  static set serverUrl(String url) => _prefs.setString(_keyServerUrl, url);

  static String get apiKey => _prefs.getString(_keyApiKey) ?? defaultApiKey;

  static set apiKey(String key) => _prefs.setString(_keyApiKey, key);

  static String get groqKey => _prefs.getString(_keyGroqKey) ?? '';

  static set groqKey(String key) => _prefs.setString(_keyGroqKey, key);

  static String get model => _prefs.getString(_keyModel) ?? defaultModel;

  static set model(String m) => _prefs.setString(_keyModel, m);

  static bool get voiceEnabled => _prefs.getBool(_keyVoiceEnabled) ?? true;

  static set voiceEnabled(bool v) => _prefs.setBool(_keyVoiceEnabled, v);

  static bool get wakeWordEnabled =>
      _prefs.getBool(_keyWakeWordEnabled) ?? true;

  static set wakeWordEnabled(bool v) => _prefs.setBool(_keyWakeWordEnabled, v);

  /// Пройден ли экран первичной настройки (онбординг разрешений).
  static bool get onboardingDone => _prefs.getBool(_keyOnboardingDone) ?? false;

  static set onboardingDone(bool v) => _prefs.setBool(_keyOnboardingDone, v);

  /// Explicit user consent for sending GPS/Wi-Fi/Bluetooth context to server.
  /// System location permission alone never enables data transfer.
  static bool get locationContextEnabled =>
      _prefs.getBool(_keyLocationContextEnabled) ?? false;

  static Future<void> setLocationContextEnabled(bool value) async {
    await _prefs.setBool(_keyLocationContextEnabled, value);
  }

  /// URL для WebSocket канала команд (управление телефоном)
  static String get phoneCommandsWsUrl =>
      '${serverUrl.replaceFirst('http', 'ws')}/v1/phone/commands';

  /// URL для Chat Completions API
  static String get chatCompletionsUrl => '$serverUrl/v1/chat/completions';

  /// URL structured runs (стриминг мыслей и вызовов через SSE)
  static String get runsUrl => serverUrl + '/v1/runs';

  /// URL файлового браузера (документы Тройки на сервере)
  static String get filesUrl => serverUrl + '/v1/files';

  /// Единая сессия для голоса и текста конкретной установки приложения.
  /// Идентификаторы генерируются случайно один раз и не разделяются между людьми.
  static String get sessionId => _sessionId;
  static String get sessionKey => _sessionKey;

  /// Headers для запросов к Hermes
  static Map<String, String> get headers {
    final key = apiKey;
    return {
      'Content-Type': 'application/json',
      if (key.isNotEmpty) 'Authorization': 'Bearer $key',
    };
  }

  /// Headers для чата — те же + привязка к общей сессии (голос+текст).
  ///
  /// НЕ включает X-Hermes-Device-Context — он собирается асинхронно через
  /// Kotlin MethodChannel (см. [chatHeadersAsync]). Для не-Android платформ
  /// (Windows/Linux/macOS) device context недоступен — там просто эти headers.
  static Map<String, String> get chatHeaders {
    return {
      ...headers,
      'X-Hermes-Session-Key': sessionKey,
      'X-Hermes-Session-Id': sessionId,
    };
  }

  /// Полные headers для chat-запросов, включая контекст устройства, если он
  /// доступен и разрешён на стороне Android.
  ///
  /// На не-Android — фаллбэк на [chatHeaders].
  static Future<Map<String, String>> chatHeadersAsync() async {
    final base = chatHeaders;
    if (!Platform.isAndroid) return base;
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
