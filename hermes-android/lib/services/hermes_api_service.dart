import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import '../config/hermes_config.dart';

/// Одно сообщение в чате (общая модель для голоса и текста).
/// Может нести текст и/или вложенные картинки (base64 data-url).
class ChatMessage {
  final String role; // 'user' | 'assistant'
  String text;
  final List<String> imageDataUrls; // data:image/...;base64,... (для отрисовки и отправки)
  final bool fromVoice;
  final DateTime time;
  bool pending; // ждём ответ сервера (для индикатора «печатает»)

  ChatMessage({
    required this.role,
    this.text = '',
    List<String>? imageDataUrls,
    this.fromVoice = false,
    DateTime? time,
    this.pending = false,
  })  : imageDataUrls = imageDataUrls ?? [],
        time = time ?? DateTime.now();

  bool get isUser => role == 'user';
  bool get hasImages => imageDataUrls.isNotEmpty;

  /// Превратить в OpenAI-совместимый message для отправки.
  /// Если есть картинки — content становится списком частей (multimodal).
  Map<String, dynamic> toApiMessage() {
    if (imageDataUrls.isEmpty) {
      return {'role': role, 'content': text};
    }
    final parts = <Map<String, dynamic>>[];
    if (text.trim().isNotEmpty) {
      parts.add({'type': 'text', 'text': text});
    }
    for (final url in imageDataUrls) {
      parts.add({
        'type': 'image_url',
        'image_url': {'url': url},
      });
    }
    return {'role': role, 'content': parts};
  }
}

/// Сервис для общения с Hermes API Server.
/// Использует OpenAI-совместимый Chat Completions API в общей сессии
/// phone-misha-main — той же, что голосовой путь (Kotlin).
class HermesApiService {
  static const Duration _timeout = Duration(seconds: 90);

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

  /// Отправить сообщение (текст + опционально картинки) в общую сессию.
  ///
  /// История на сервере (state.db) ведётся по session-id, поэтому мы НЕ
  /// тащим всю историю в запросе — шлём только новое сообщение, сервер сам
  /// подмешивает контекст сессии (как для голоса). [recent] — несколько
  /// последних реплик для немедленного контекста, если сервер этого ждёт.
  Future<String> sendMessage(
    ChatMessage message, {
    List<ChatMessage> recent = const [],
  }) async {
    final messages = <Map<String, dynamic>>[
      for (final m in recent) m.toApiMessage(),
      message.toApiMessage(),
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
          .post(uri,
              headers: HermesConfig.chatHeaders, body: json.encode(bodyMap))
          .timeout(_timeout);

      if (response.statusCode != 200) {
        throw HermesApiException(
            'API error ${response.statusCode}: ${_short(response.body)}');
      }

      final data = json.decode(utf8.decode(response.bodyBytes));
      final assistantMessage =
          data['choices'][0]['message']['content'] as String? ?? '';
      return assistantMessage;
    } on SocketException {
      throw HermesApiException(
          'Нет соединения с сервером. Проверь что сервер включён.');
    } on TimeoutException {
      throw HermesApiException('Сервер не ответил вовремя. Попробуй ещё раз.');
    }
  }

  static String _short(String s) => s.length > 200 ? '${s.substring(0, 200)}…' : s;

  /// Загрузить историю общей сессии с сервера (для отрисовки ленты при входе).
  /// Возвращает сообщения по порядку (старые → новые).
  Future<List<ChatMessage>> loadSessionHistory({int limit = 60}) async {
    final encoded = Uri.encodeComponent(HermesConfig.sessionId);
    final uri = Uri.parse(
        '${HermesConfig.serverUrl}/v1/sessions/$encoded/messages?limit=$limit');
    try {
      final response = await http
          .get(uri, headers: HermesConfig.headers)
          .timeout(const Duration(seconds: 15));
      if (response.statusCode == 404) {
        return []; // сессии ещё нет — пустой чат
      }
      if (response.statusCode != 200) {
        throw HermesApiException('История недоступна (${response.statusCode}).');
      }
      final data = json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      final raw = (data['messages'] as List?) ?? const [];
      final out = <ChatMessage>[];
      for (final m in raw.whereType<Map<String, dynamic>>()) {
        final role = (m['role'] ?? 'user').toString();
        if (role != 'user' && role != 'assistant') continue;
        final content = _extractText(m['content']);
        if (content.trim().isEmpty) continue;
        out.add(ChatMessage(
          role: role,
          text: _stripDatePrefix(content),
          time: _toTime(m['timestamp']),
        ));
      }
      return out;
    } on SocketException {
      throw HermesApiException('Нет соединения с сервером — историю взять негде.');
    } on TimeoutException {
      throw HermesApiException('Сервер не ответил вовремя.');
    }
  }

  /// content может быть строкой или списком частей — достаём текст.
  static String _extractText(dynamic content) {
    if (content is String) return content;
    if (content is List) {
      final buf = StringBuffer();
      for (final part in content) {
        if (part is Map && part['type'] == 'text') {
          buf.write(part['text'] ?? '');
        }
      }
      return buf.toString();
    }
    return content?.toString() ?? '';
  }

  /// Убрать служебный префикс «[сейчас 16 июня 2026, вторник, 15:30] » из
  /// пользовательских сообщений — он нужен модели, но в UI лишний.
  static String _stripDatePrefix(String s) {
    final re = RegExp(r'^\[сейчас [^\]]*\]\s*');
    return s.replaceFirst(re, '');
  }

  static DateTime _toTime(dynamic ts) {
    if (ts is num) {
      return DateTime.fromMillisecondsSinceEpoch((ts * 1000).round());
    }
    return DateTime.now();
  }

  // ── Список всех сессий (экран истории) ───────────────────────────────────
  Future<List<SessionSummary>> listSessions({int limit = 50, int offset = 0}) async {
    final uri = Uri.parse(
      '${HermesConfig.serverUrl}/v1/sessions?limit=$limit&offset=$offset',
    );
    try {
      final response = await http
          .get(uri, headers: HermesConfig.headers)
          .timeout(const Duration(seconds: 15));
      if (response.statusCode != 200) {
        throw HermesApiException('История недоступна (${response.statusCode}).');
      }
      final data = json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      final raw = (data['sessions'] as List?) ?? const [];
      return raw
          .whereType<Map<String, dynamic>>()
          .map(SessionSummary.fromJson)
          .toList();
    } on SocketException {
      throw HermesApiException('Нет соединения с сервером — историю взять негде.');
    } on TimeoutException {
      throw HermesApiException('Сервер не ответил вовремя.');
    }
  }

  Future<List<SessionMessage>> getSessionMessages(String sessionId) async {
    final encoded = Uri.encodeComponent(sessionId);
    final uri = Uri.parse('${HermesConfig.serverUrl}/v1/sessions/$encoded/messages');
    try {
      final response = await http
          .get(uri, headers: HermesConfig.headers)
          .timeout(const Duration(seconds: 15));
      if (response.statusCode != 200) {
        throw HermesApiException('Сессия недоступна (${response.statusCode}).');
      }
      final data = json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      final raw = (data['messages'] as List?) ?? const [];
      return raw
          .whereType<Map<String, dynamic>>()
          .map(SessionMessage.fromJson)
          .toList();
    } on SocketException {
      throw HermesApiException('Нет соединения с сервером — транскрипт взять негде.');
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
