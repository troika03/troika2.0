import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import '../config/hermes_config.dart';

/// Сервис для общения с Hermes API Server (на PC)
/// Использует OpenAI-совместимый Chat Completions API
class HermesApiService {
  static const Duration _timeout = Duration(seconds: 60);

  // История разговора (для памяти контекста)
  final List<Map<String, String>> _conversationHistory = [];

  // Системный промпт — личность ассистента
  static const String _systemPrompt = '''
Ты Тройка — персональный голосовой ассистент. Отвечай коротко и чётко, так как твои ответы будут проговорены голосом.
Ты помогаешь управлять телефоном, отвечаешь на вопросы, выполняешь задачи.
Общайся на русском языке, если пользователь говорит по-русски.
Не используй маркдаун и форматирование — только чистый текст для TTS.
''';

  /// Проверка подключения к Hermes
  Future<bool> checkConnection() async {
    try {
      final uri = Uri.parse('${HermesConfig.serverUrl}/health');
      final response = await http
          .get(uri, headers: HermesConfig.headers)
          .timeout(const Duration(seconds: 5));
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// Отправить текстовый запрос, получить текстовый ответ
  Future<String> sendMessage(String userMessage) async {
    // Добавить сообщение в историю
    _conversationHistory.add({
      'role': 'user',
      'content': userMessage,
    });

    final messages = [
      {'role': 'system', 'content': _systemPrompt},
      ..._conversationHistory,
    ];

    final bodyMap = <String, dynamic>{
      'messages': messages,
      'stream': false,
    };
    if (HermesConfig.model.isNotEmpty) {
      bodyMap['model'] = HermesConfig.model;
    }

    try {
      final uri = Uri.parse(HermesConfig.chatCompletionsUrl);
      final response = await http
          .post(uri, headers: HermesConfig.headers, body: json.encode(bodyMap))
          .timeout(_timeout);

      if (response.statusCode != 200) {
        throw HermesApiException(
            'API error ${response.statusCode}: ${response.body}');
      }

      final data = json.decode(response.body);
      final assistantMessage =
          data['choices'][0]['message']['content'] as String;

      // Сохранить ответ в историю
      _conversationHistory.add({
        'role': 'assistant',
        'content': assistantMessage,
      });

      // Ограничить историю последними 20 сообщениями
      if (_conversationHistory.length > 20) {
        _conversationHistory.removeRange(0, _conversationHistory.length - 20);
      }

      return assistantMessage;
    } on SocketException {
      throw HermesApiException(
          'Нет соединения с сервером. Проверь что PC включён и сервер запущен.');
    } on TimeoutException {
      throw HermesApiException('Сервер не ответил вовремя. Попробуй ещё раз.');
    }
  }

  /// Очистить историю разговора (начать новую сессию)
  void clearHistory() {
    _conversationHistory.clear();
  }

  /// Получить историю для отображения в UI
  List<Map<String, String>> get history =>
      List.unmodifiable(_conversationHistory);

  /// Список всех сессий из state.db на сервере (для экрана истории).
  ///
  /// Возвращает список сессий с превью первого сообщения и временем последнего
  /// сообщения. Сортировка — последнее активное вверху.
  Future<List<SessionSummary>> listSessions({int limit = 50, int offset = 0}) async {
    final uri = Uri.parse(
      '${HermesConfig.serverUrl}/v1/sessions?limit=$limit&offset=$offset',
    );
    try {
      final response = await http
          .get(uri, headers: HermesConfig.headers)
          .timeout(const Duration(seconds: 15));
      if (response.statusCode != 200) {
        throw HermesApiException(
            'История недоступна (${response.statusCode}).');
      }
      final data = json.decode(response.body) as Map<String, dynamic>;
      final raw = (data['sessions'] as List?) ?? const [];
      return raw
          .whereType<Map<String, dynamic>>()
          .map(SessionSummary.fromJson)
          .toList();
    } on SocketException {
      throw HermesApiException(
          'Нет соединения с сервером — историю взять негде.');
    } on TimeoutException {
      throw HermesApiException('Сервер не ответил вовремя.');
    }
  }

  /// Транскрипт одной сессии (user + assistant сообщения).
  Future<List<SessionMessage>> getSessionMessages(String sessionId) async {
    final encoded = Uri.encodeComponent(sessionId);
    final uri = Uri.parse('${HermesConfig.serverUrl}/v1/sessions/$encoded/messages');
    try {
      final response = await http
          .get(uri, headers: HermesConfig.headers)
          .timeout(const Duration(seconds: 15));
      if (response.statusCode != 200) {
        throw HermesApiException(
            'Сессия недоступна (${response.statusCode}).');
      }
      final data = json.decode(response.body) as Map<String, dynamic>;
      final raw = (data['messages'] as List?) ?? const [];
      return raw
          .whereType<Map<String, dynamic>>()
          .map(SessionMessage.fromJson)
          .toList();
    } on SocketException {
      throw HermesApiException(
          'Нет соединения с сервером — транскрипт взять негде.');
    } on TimeoutException {
      throw HermesApiException('Сервер не ответил вовремя.');
    }
  }
}

class SessionSummary {
  final String id;
  final String? source;
  final String? title;
  final String? preview;
  final int messageCount;
  final double? lastActive;

  SessionSummary({
    required this.id,
    required this.messageCount,
    this.source,
    this.title,
    this.preview,
    this.lastActive,
  });

  factory SessionSummary.fromJson(Map<String, dynamic> j) => SessionSummary(
        id: (j['id'] ?? '').toString(),
        source: j['source']?.toString(),
        title: j['title']?.toString(),
        preview: j['preview']?.toString(),
        messageCount: (j['message_count'] as num?)?.toInt() ?? 0,
        lastActive: (j['last_active'] as num?)?.toDouble(),
      );
}

class SessionMessage {
  final String role;
  final String content;
  final double? timestamp;

  SessionMessage({required this.role, required this.content, this.timestamp});

  factory SessionMessage.fromJson(Map<String, dynamic> j) => SessionMessage(
        role: (j['role'] ?? 'user').toString(),
        content: (j['content'] ?? '').toString(),
        timestamp: (j['timestamp'] as num?)?.toDouble(),
      );
}

class HermesApiException implements Exception {
  final String message;
  HermesApiException(this.message);

  @override
  String toString() => message;
}
