import 'package:shared_preferences/shared_preferences.dart';

/// Настройки подключения к Hermes API Server (на сервере)
class HermesConfig {
  static const String _keyServerUrl = 'hermes_server_url';
  static const String _keyApiKey = 'hermes_api_key';
  static const String _keyGroqKey = 'hermes_groq_key';
  static const String _keyModel = 'hermes_model';
  static const String _keyVoiceEnabled = 'hermes_voice_enabled';
  static const String _keyWakeWordEnabled = 'hermes_wake_word_enabled';

  // Дефолтные значения
  // Пусто — новичок вводит адрес своего сервера в настройках при первом запуске
  // (вид: http://1.2.3.4:8642 или http://my-domain.com:8642)
  static const String defaultServerUrl = '';
  static const String defaultApiKey = 'hermes-2024';
  static const String defaultModel = ''; // пустая строка = использует модель из конфига на PC

  static late SharedPreferences _prefs;

  static Future<void> init() async {
    _prefs = await SharedPreferences.getInstance();
  }

  static String get serverUrl =>
      _prefs.getString(_keyServerUrl) ?? defaultServerUrl;

  static set serverUrl(String url) =>
      _prefs.setString(_keyServerUrl, url);

  static String get apiKey =>
      _prefs.getString(_keyApiKey) ?? defaultApiKey;

  static set apiKey(String key) =>
      _prefs.setString(_keyApiKey, key);

  static String get groqKey =>
      _prefs.getString(_keyGroqKey) ?? '';

  static set groqKey(String key) =>
      _prefs.setString(_keyGroqKey, key);

  static String get model =>
      _prefs.getString(_keyModel) ?? defaultModel;

  static set model(String m) =>
      _prefs.setString(_keyModel, m);

  static bool get voiceEnabled =>
      _prefs.getBool(_keyVoiceEnabled) ?? true;

  static set voiceEnabled(bool v) =>
      _prefs.setBool(_keyVoiceEnabled, v);

  static bool get wakeWordEnabled =>
      _prefs.getBool(_keyWakeWordEnabled) ?? true;

  static set wakeWordEnabled(bool v) =>
      _prefs.setBool(_keyWakeWordEnabled, v);

  /// URL для WebSocket канала команд (управление телефоном)
  static String get phoneCommandsWsUrl =>
      '${serverUrl.replaceFirst('http', 'ws')}/v1/phone/commands';

  /// URL для Chat Completions API
  static String get chatCompletionsUrl =>
      '$serverUrl/v1/chat/completions';

  /// Headers для запросов к Hermes
  static Map<String, String> get headers {
    final key = apiKey;
    return {
      'Content-Type': 'application/json',
      if (key.isNotEmpty) 'Authorization': 'Bearer $key',
    };
  }
}
