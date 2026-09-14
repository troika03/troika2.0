import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:file_picker/file_picker.dart';
import 'package:http/http.dart' as http;
import '../config/hermes_config.dart';

/// Тип шага в «потоке мыслей» Тройки (что она делает перед ответом).
enum ThoughtKind {
  thinking, // размышление (reasoning.available)
  toolStart, // начала вызывать инструмент
  toolDone, // инструмент отработал
}

/// Один шаг внутренней работы Тройки — для ленты «как она думает».
class ThoughtStep {
  final ThoughtKind kind;
  final String text; // текст мысли / имя инструмента / результат
  final bool isError; // для toolDone — отработал с ошибкой
  final DateTime time;

  ThoughtStep(this.kind, this.text, {this.isError = false, DateTime? time})
      : time = time ?? DateTime.now();
}

/// One server-requested confirmation for an action on the paired phone.
/// The server has already bound the run to this installation's device token.
class RunApprovalRequest {
  final String action;
  final String description;
  final List<String> choices;

  const RunApprovalRequest({
    required this.action,
    required this.description,
    required this.choices,
  });
}

/// Одно сообщение в чате (общая модель для голоса и текста).
/// Может нести текст и/или вложенные картинки (base64 data-url).
class ChatMessage {
  final String role; // 'user' | 'assistant'
  String text;
  final List<String>
      imageDataUrls; // data:image/...;base64,... (для отрисовки и отправки)
  final bool fromVoice;
  final DateTime time;
  bool pending; // ждём ответ сервера (для индикатора «печатает»)

  // «Поток мыслей» Тройки: размышления и вызовы инструментов в реальном
  // времени. Пусто для пользовательских сообщений и старой истории.
  final List<ThoughtStep> thoughts;

  ChatMessage({
    required this.role,
    this.text = '',
    List<String>? imageDataUrls,
    this.fromVoice = false,
    DateTime? time,
    this.pending = false,
    List<ThoughtStep>? thoughts,
  })  : imageDataUrls = imageDataUrls ?? [],
        thoughts = thoughts ?? [],
        time = time ?? DateTime.now();

  bool get isUser => role == 'user';
  bool get hasImages => imageDataUrls.isNotEmpty;
  bool get hasThoughts => thoughts.isNotEmpty;

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
/// конкретной установки приложения — той же, что голосовой путь (Kotlin).
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

  /// Download a complete owner-scoped ZIP and save it through the system picker.
  Future<bool> exportAccountData() async {
    if (!HermesConfig.apiKey.startsWith('trk_live_')) {
      throw HermesApiException(
          'Экспорт данных доступен после подключения Тройки.');
    }
    try {
      final response = await http
          .get(
            Uri.parse(HermesConfig.accountExportUrl),
            headers: HermesConfig.headers,
          )
          .timeout(const Duration(seconds: 90));
      if (response.statusCode != 200) {
        throw HermesApiException(
          'Сервер не создал экспорт (${response.statusCode}): '
          '${_short(response.body)}',
        );
      }
      final now = DateTime.now().toUtc();
      final date = '${now.year.toString().padLeft(4, '0')}-'
          '${now.month.toString().padLeft(2, '0')}-'
          '${now.day.toString().padLeft(2, '0')}';
      final isMobile = Platform.isAndroid || Platform.isIOS;
      final target = await FilePicker.platform.saveFile(
        dialogTitle: 'Сохранить данные Тройки',
        fileName: 'troika-data-export-$date.zip',
        type: FileType.custom,
        allowedExtensions: const ['zip'],
        bytes: isMobile ? response.bodyBytes : null,
      );
      if (target == null) return false;
      if (!isMobile) {
        await File(target).writeAsBytes(response.bodyBytes, flush: true);
      }
      return true;
    } on SocketException {
      throw HermesApiException('Нет соединения с сервером. Экспорт не создан.');
    } on TimeoutException {
      throw HermesApiException(
          'Сервер не успел создать экспорт. Повтори позже.');
    }
  }

  /// Irreversibly delete the authenticated product account on the server.
  /// A 202 means cleanup continues server-side, but the token is already revoked.
  Future<bool> deleteAccount() async {
    if (!HermesConfig.apiKey.startsWith('trk_live_')) {
      throw HermesApiException(
          'Удаление аккаунта доступно после подключения Тройки.');
    }
    try {
      final response = await http
          .delete(
            Uri.parse(HermesConfig.accountUrl),
            headers: HermesConfig.headers,
            body: json.encode({'confirmation': 'DELETE_MY_ACCOUNT'}),
          )
          .timeout(const Duration(seconds: 20));
      if (response.statusCode != 200 && response.statusCode != 202) {
        throw HermesApiException(
          'Сервер не завершил удаление (${response.statusCode}): '
          '${_short(response.body)}',
        );
      }
      return response.statusCode == 200;
    } on SocketException {
      throw HermesApiException('Нет соединения с сервером. Аккаунт не удалён.');
    } on TimeoutException {
      throw HermesApiException(
          'Сервер не подтвердил удаление. Попробуй ещё раз.');
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

    final bodyMap = <String, dynamic>{'messages': messages, 'stream': false};
    if (HermesConfig.model.isNotEmpty) {
      bodyMap['model'] = HermesConfig.model;
    }

    try {
      final uri = Uri.parse(HermesConfig.chatCompletionsUrl);
      // Async headers чтобы X-Hermes-Device-Context (GPS/wifi/bt) шёл с каждым
      // запросом. Иначе Тройка не знает координат Миши пока не пройдёт
      // wake-word диалог (Kotlin шлёт header только оттуда).
      final chatHdrs = await HermesConfig.chatHeadersAsync();
      final response = await http
          .post(uri, headers: chatHdrs, body: json.encode(bodyMap))
          .timeout(_timeout);

      if (response.statusCode != 200) {
        throw HermesApiException(
          'API error ${response.statusCode}: ${_short(response.body)}',
        );
      }

      final data = json.decode(utf8.decode(response.bodyBytes));
      final assistantMessage =
          data['choices'][0]['message']['content'] as String? ?? '';
      return assistantMessage;
    } on SocketException {
      throw HermesApiException(
        'Нет соединения с сервером. Проверь что сервер включён.',
      );
    } on TimeoutException {
      throw HermesApiException('Сервер не ответил вовремя. Попробуй ещё раз.');
    }
  }

  /// Отправить сообщение через structured runs и стримить «поток мыслей».
  ///
  /// Шлёт POST /v1/runs, затем читает SSE /v1/runs/{id}/events.
  /// Колбэки вызываются по мере поступления событий:
  ///  - [onThought]   — размышление Тройки (reasoning.available)
  ///  - [onToolStart] — начала вызывать инструмент
  ///  - [onToolDone]  — инструмент отработал (имя, была ли ошибка)
  ///  - [onDelta]     — кусочек финального текста ответа (message.delta)
  /// Возвращает полный текст ответа.
  Future<String> streamMessage(
    ChatMessage message, {
    List<ChatMessage> recent = const [],
    void Function(String thought)? onThought,
    void Function(String tool)? onToolStart,
    void Function(String tool, bool isError)? onToolDone,
    void Function(String delta)? onDelta,
    Future<String> Function(RunApprovalRequest request)? onApproval,
  }) async {
    // 1) Стартуем run. input = только новое сообщение; историю сервер берёт
    //    из общей сессии. recent шлём как conversation_history для надёжности.
    final history = <Map<String, dynamic>>[
      for (final m in recent) m.toApiMessage(),
    ];
    final inputContent = message.toApiMessage()['content'];
    final startBody = <String, dynamic>{
      'input': inputContent is String ? inputContent : [message.toApiMessage()],
      'session_id': HermesConfig.sessionId,
      if (history.isNotEmpty) 'conversation_history': history,
    };

    final client = http.Client();
    try {
      // Async headers — с device_context (GPS) для streaming-пути тоже.
      final chatHdrs = await HermesConfig.chatHeadersAsync();
      final startReq = http.Request('POST', Uri.parse(HermesConfig.runsUrl))
        ..headers.addAll(chatHdrs)
        ..body = json.encode(startBody);
      final startResp = await client.send(startReq).timeout(_timeout);
      final startBodyStr = await startResp.stream.bytesToString();
      // Сервер отдаёт 202 Accepted (run стартовал асинхронно), реже 200.
      if (startResp.statusCode != 200 && startResp.statusCode != 202) {
        throw HermesApiException(
          'API error ${startResp.statusCode}: ${_short(startBodyStr)}',
        );
      }
      final startData = json.decode(startBodyStr) as Map<String, dynamic>;
      final runId = (startData['run_id'] ?? startData['id'])?.toString();
      if (runId == null || runId.isEmpty) {
        throw HermesApiException('Сервер не вернул run_id.');
      }

      // 2) Слушаем поток событий.
      final evUri = Uri.parse('${HermesConfig.runsUrl}/$runId/events');
      final evReq = http.Request('GET', evUri)
        ..headers.addAll(HermesConfig.headers);
      final evResp = await client.send(evReq).timeout(_timeout);
      if (evResp.statusCode != 200) {
        throw HermesApiException(
          'Поток событий недоступен (${evResp.statusCode}).',
        );
      }

      final answer = StringBuffer();
      String lastThought = '';
      bool runFailed = false;
      await for (final raw in evResp.stream
          .transform(utf8.decoder)
          .transform(const LineSplitter())) {
        final line = raw.trim();
        if (line.isEmpty || !line.startsWith('data:')) continue;
        final payload = line.substring(5).trim();
        if (payload.isEmpty || payload == '[DONE]') continue;
        Map<String, dynamic> ev;
        try {
          ev = json.decode(payload) as Map<String, dynamic>;
        } catch (_) {
          continue;
        }
        switch (ev['event']) {
          case 'reasoning.available':
            final t = (ev['text'] ?? '').toString().trim();
            if (t.isNotEmpty && t != lastThought) {
              lastThought = t;
              onThought?.call(t);
            }
            break;
          case 'tool.started':
            onToolStart?.call((ev['tool'] ?? '').toString());
            break;
          case 'tool.completed':
            onToolDone?.call(
              (ev['tool'] ?? '').toString(),
              ev['error'] == true,
            );
            break;
          case 'message.delta':
            final d = (ev['delta'] ?? '').toString();
            if (d.isNotEmpty) {
              answer.write(d);
              onDelta?.call(d);
            }
            break;
          case 'approval.request':
            final rawChoices = ev['choices'];
            final choices = rawChoices is List
                ? rawChoices.map((choice) => choice.toString()).toList()
                : const <String>['once', 'deny'];
            final request = RunApprovalRequest(
              action: (ev['command'] ?? '').toString(),
              description:
                  (ev['description'] ?? 'Подтвердить действие?').toString(),
              choices: choices,
            );
            String choice = 'deny';
            if (onApproval != null) {
              try {
                choice = await onApproval(request);
              } catch (_) {
                choice = 'deny';
              }
            }
            if (!choices.contains(choice)) choice = 'deny';
            await _resolveRunApproval(client, runId, choice);
            break;
          case 'run.failed':
            runFailed = true;
            break;
          case 'run.completed':
            // Поток закроется сам; выходим из чтения.
            break;
        }
      }

      final full = answer.toString().trim();
      if (runFailed && full.isEmpty) {
        // Run упал на сервере — достаём причину из статуса, чтобы показать
        // понятную ошибку, а не пустой пузырь.
        final reason = await _fetchRunError(client, runId);
        throw HermesApiException(reason);
      }
      if (full.isEmpty) {
        // Финал не пришёл дельтами — добираем через статус run.
        final r = await _fetchRunResult(client, runId);
        if (r.isEmpty) {
          throw HermesApiException(await _fetchRunError(client, runId));
        }
        return r;
      }
      return full;
    } on SocketException {
      throw HermesApiException('Нет соединения с сервером.');
    } on TimeoutException {
      throw HermesApiException('Сервер не ответил вовремя.');
    } finally {
      client.close();
    }
  }

  Future<void> _resolveRunApproval(
    http.Client client,
    String runId,
    String choice,
  ) async {
    final uri = Uri.parse('${HermesConfig.runsUrl}/$runId/approval');
    final response = await client
        .post(uri,
            headers: HermesConfig.headers,
            body: json.encode({'choice': choice}))
        .timeout(const Duration(seconds: 20));
    if (response.statusCode != 200) {
      throw HermesApiException(
        'Не удалось подтвердить действие (${response.statusCode}).',
      );
    }
  }

  /// Достаёт человеко-понятную причину падения run из его статуса.
  Future<String> _fetchRunError(http.Client client, String runId) async {
    try {
      final uri = Uri.parse('${HermesConfig.runsUrl}/$runId');
      final req = http.Request('GET', uri)
        ..headers.addAll(HermesConfig.headers);
      final resp = await client.send(req).timeout(const Duration(seconds: 20));
      final body = await resp.stream.bytesToString();
      final data = json.decode(body) as Map<String, dynamic>;
      final err = (data['error'] ?? '').toString();
      if (err.contains('402') || err.toLowerCase().contains('credits')) {
        return 'У Тройки закончились кредиты OpenRouter — нужно пополнить баланс, '
            'чтобы она снова могла думать и отвечать.';
      }
      if (err.contains('429')) {
        return 'Модель временно перегружена (лимит запросов). Попробуй через минуту.';
      }
      if (err.isNotEmpty) return 'Тройка не смогла ответить: ${_short(err)}';
      return 'Тройка не смогла ответить (run завершился неудачно).';
    } catch (_) {
      return 'Тройка не смогла ответить (run завершился неудачно).';
    }
  }

  /// Запасной путь: если message.delta не пришли — берём готовый ответ run.
  Future<String> _fetchRunResult(http.Client client, String runId) async {
    try {
      final uri = Uri.parse('${HermesConfig.runsUrl}/$runId');
      final req = http.Request('GET', uri)
        ..headers.addAll(HermesConfig.headers);
      final resp = await client.send(req).timeout(const Duration(seconds: 30));
      final body = await resp.stream.bytesToString();
      if (resp.statusCode != 200) return '';
      final data = json.decode(body) as Map<String, dynamic>;
      final out = data['output'] ?? data['result'] ?? data['content'] ?? '';
      return _extractText(out).trim();
    } catch (_) {
      return '';
    }
  }

  static String _short(String s) =>
      s.length > 200 ? '${s.substring(0, 200)}…' : s;

  /// Загрузить историю общей сессии с сервера (для отрисовки ленты при входе).
  /// Возвращает сообщения по порядку (старые → новые).
  Future<List<ChatMessage>> loadSessionHistory({int limit = 60}) async {
    final encoded = Uri.encodeComponent(HermesConfig.sessionId);
    final uri = Uri.parse(
      '${HermesConfig.serverUrl}/v1/sessions/$encoded/messages?limit=$limit',
    );
    try {
      final response = await http
          .get(uri, headers: HermesConfig.headers)
          .timeout(const Duration(seconds: 15));
      if (response.statusCode == 404) {
        return []; // сессии ещё нет — пустой чат
      }
      if (response.statusCode != 200) {
        throw HermesApiException(
          'История недоступна (${response.statusCode}).',
        );
      }
      final data =
          json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      final raw = (data['messages'] as List?) ?? const [];
      final out = <ChatMessage>[];
      for (final m in raw.whereType<Map<String, dynamic>>()) {
        final role = (m['role'] ?? 'user').toString();
        if (role != 'user' && role != 'assistant') continue;
        final content = _extractText(m['content']);
        if (content.trim().isEmpty) continue;
        out.add(
          ChatMessage(
            role: role,
            text: _stripDatePrefix(content),
            time: _toTime(m['timestamp']),
          ),
        );
      }
      return out;
    } on SocketException {
      throw HermesApiException(
        'Нет соединения с сервером — историю взять негде.',
      );
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
  Future<List<TroikaProject>> listAssistantProjects() async {
    final response = await http
        .get(Uri.parse('${HermesConfig.serverUrl}/v1/assistant/projects'),
            headers: HermesConfig.headers)
        .timeout(const Duration(seconds: 15));
    _checkAssistantResponse(response, 'Проекты недоступны');
    final data =
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return ((data['projects'] as List?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(TroikaProject.fromJson)
        .toList();
  }

  Future<TroikaProject> createAssistantProject(String name,
      {String summary = ''}) async {
    final response = await http
        .post(Uri.parse('${HermesConfig.serverUrl}/v1/assistant/projects'),
            headers: HermesConfig.headers,
            body: json.encode({'name': name, 'summary': summary}))
        .timeout(const Duration(seconds: 15));
    _checkAssistantResponse(response, 'Проект не создан');
    return TroikaProject.fromJson((json.decode(utf8.decode(response.bodyBytes))
        as Map<String, dynamic>)['project'] as Map<String, dynamic>);
  }

  Future<void> activateAssistantProject(String projectId) async {
    final response = await http
        .put(
            Uri.parse('${HermesConfig.serverUrl}/v1/assistant/projects/'
                '${Uri.encodeComponent(projectId)}/active'),
            headers: HermesConfig.headers)
        .timeout(const Duration(seconds: 15));
    _checkAssistantResponse(response, 'Проект не выбран');
  }

  Future<List<TroikaTask>> listAssistantTasks(
      {String? projectId, bool includeClosed = false}) async {
    final query = <String, String>{'include_closed': includeClosed.toString()};
    if (projectId != null && projectId.isNotEmpty) {
      query['project_id'] = projectId;
    }
    final uri = Uri.parse('${HermesConfig.serverUrl}/v1/assistant/tasks')
        .replace(queryParameters: query);
    final response = await http
        .get(uri, headers: HermesConfig.headers)
        .timeout(const Duration(seconds: 15));
    _checkAssistantResponse(response, 'Задачи недоступны');
    final data =
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return ((data['tasks'] as List?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(TroikaTask.fromJson)
        .toList();
  }

  Future<TroikaTask> createAssistantTask(
      {required String title,
      String? projectId,
      String details = '',
      String? dueAt,
      String actionMode = 'remind',
      String actionSummary = ''}) async {
    final body = <String, dynamic>{
      'title': title,
      'details': details,
      'action_mode': actionMode,
      'action_summary': actionSummary
    };
    if (projectId != null && projectId.isNotEmpty) {
      body['project_id'] = projectId;
    }
    if (dueAt != null && dueAt.isNotEmpty) body['due_at'] = dueAt;
    final response = await http
        .post(Uri.parse('${HermesConfig.serverUrl}/v1/assistant/tasks'),
            headers: {
              ...HermesConfig.headers,
              'Idempotency-Key':
                  'android-${DateTime.now().microsecondsSinceEpoch}'
            },
            body: json.encode(body))
        .timeout(const Duration(seconds: 15));
    _checkAssistantResponse(response, 'Задача не создана');
    return TroikaTask.fromJson((json.decode(utf8.decode(response.bodyBytes))
        as Map<String, dynamic>)['task'] as Map<String, dynamic>);
  }

  Future<TroikaTask> updateAssistantTaskStatus(
      String taskId, String status) async {
    final response = await http
        .patch(
            Uri.parse('${HermesConfig.serverUrl}/v1/assistant/tasks/'
                '${Uri.encodeComponent(taskId)}'),
            headers: HermesConfig.headers,
            body: json.encode({'status': status}))
        .timeout(const Duration(seconds: 15));
    _checkAssistantResponse(response, 'Статус задачи не обновлён');
    return TroikaTask.fromJson((json.decode(utf8.decode(response.bodyBytes))
        as Map<String, dynamic>)['task'] as Map<String, dynamic>);
  }

  Future<List<TroikaInboxMessage>> listAssistantInbox(
      {bool unreadOnly = false}) async {
    final uri = Uri.parse('${HermesConfig.serverUrl}/v1/assistant/inbox')
        .replace(queryParameters: {'unread_only': unreadOnly.toString()});
    final response = await http
        .get(uri, headers: HermesConfig.headers)
        .timeout(const Duration(seconds: 15));
    _checkAssistantResponse(response, 'Входящие недоступны');
    final data =
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return ((data['messages'] as List?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(TroikaInboxMessage.fromJson)
        .toList();
  }

  Future<void> markAssistantMessageRead(String messageId) async {
    final response = await http
        .post(
            Uri.parse('${HermesConfig.serverUrl}/v1/assistant/inbox/'
                '${Uri.encodeComponent(messageId)}/read'),
            headers: HermesConfig.headers)
        .timeout(const Duration(seconds: 15));
    _checkAssistantResponse(response, 'Сообщение не обновлено');
  }

  Future<TroikaNotificationPreferences> getNotificationPreferences() async {
    final response = await http
        .get(Uri.parse('${HermesConfig.serverUrl}/v1/notification-preferences'),
            headers: HermesConfig.headers)
        .timeout(const Duration(seconds: 15));
    _checkAssistantResponse(response, 'Настройки уведомлений недоступны');
    return TroikaNotificationPreferences.fromJson(
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>);
  }

  Future<void> setNotificationPreferences(
      TroikaNotificationPreferences preferences) async {
    final response = await http
        .put(Uri.parse('${HermesConfig.serverUrl}/v1/notification-preferences'),
            headers: HermesConfig.headers,
            body: json.encode(preferences.toJson()))
        .timeout(const Duration(seconds: 15));
    _checkAssistantResponse(response, 'Настройки уведомлений не сохранены');
  }

  static void _checkAssistantResponse(http.Response response, String fallback) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw HermesApiException('$fallback (${response.statusCode}).');
    }
  }

  Future<List<SessionSummary>> listSessions({
    int limit = 50,
    int offset = 0,
  }) async {
    final uri = Uri.parse(
      '${HermesConfig.serverUrl}/v1/sessions?limit=$limit&offset=$offset',
    );
    try {
      final response = await http
          .get(uri, headers: HermesConfig.headers)
          .timeout(const Duration(seconds: 15));
      if (response.statusCode != 200) {
        throw HermesApiException(
          'История недоступна (${response.statusCode}).',
        );
      }
      final data =
          json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      final raw = (data['sessions'] as List?) ?? const [];
      return raw
          .whereType<Map<String, dynamic>>()
          .map(SessionSummary.fromJson)
          .toList();
    } on SocketException {
      throw HermesApiException(
        'Нет соединения с сервером — историю взять негде.',
      );
    } on TimeoutException {
      throw HermesApiException('Сервер не ответил вовремя.');
    }
  }

  Future<List<SessionMessage>> getSessionMessages(String sessionId) async {
    final encoded = Uri.encodeComponent(sessionId);
    final uri = Uri.parse(
      '${HermesConfig.serverUrl}/v1/sessions/$encoded/messages',
    );
    try {
      final response = await http
          .get(uri, headers: HermesConfig.headers)
          .timeout(const Duration(seconds: 15));
      if (response.statusCode != 200) {
        throw HermesApiException('Сессия недоступна (${response.statusCode}).');
      }
      final data =
          json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      final raw = (data['messages'] as List?) ?? const [];
      return raw
          .whereType<Map<String, dynamic>>()
          .map(SessionMessage.fromJson)
          .toList();
    } on SocketException {
      throw HermesApiException(
        'Нет соединения с сервером — транскрипт взять негде.',
      );
    } on TimeoutException {
      throw HermesApiException('Сервер не ответил вовремя.');
    }
  }
}

class TroikaProject {
  final String id, name, summary, status;
  final bool isActive;
  TroikaProject(
      {required this.id,
      required this.name,
      required this.summary,
      required this.status,
      required this.isActive});
  factory TroikaProject.fromJson(Map<String, dynamic> j) => TroikaProject(
      id: (j['id'] ?? '').toString(),
      name: (j['name'] ?? '').toString(),
      summary: (j['summary'] ?? '').toString(),
      status: (j['status'] ?? '').toString(),
      isActive: j['is_active'] == true);
}

class TroikaTask {
  final String id, projectId, title, details, status, actionMode, dueAt;
  final bool requiresApproval;
  TroikaTask(
      {required this.id,
      required this.projectId,
      required this.title,
      required this.details,
      required this.status,
      required this.actionMode,
      required this.dueAt,
      required this.requiresApproval});
  factory TroikaTask.fromJson(Map<String, dynamic> j) => TroikaTask(
      id: (j['id'] ?? '').toString(),
      projectId: (j['project_id'] ?? '').toString(),
      title: (j['title'] ?? '').toString(),
      details: (j['details'] ?? '').toString(),
      status: (j['status'] ?? '').toString(),
      actionMode: (j['action_mode'] ?? 'remind').toString(),
      dueAt: (j['due_at'] ?? '').toString(),
      requiresApproval: j['requires_approval'] == true);
}

class TroikaInboxMessage {
  final String id, kind, category, title, body, reason, availableAt;
  final bool requiresApproval;
  final bool isRead;
  TroikaInboxMessage(
      {required this.id,
      required this.kind,
      required this.category,
      required this.title,
      required this.body,
      required this.reason,
      required this.availableAt,
      required this.requiresApproval,
      required this.isRead});
  factory TroikaInboxMessage.fromJson(Map<String, dynamic> j) =>
      TroikaInboxMessage(
          id: (j['id'] ?? '').toString(),
          kind: (j['kind'] ?? '').toString(),
          category: (j['category'] ?? '').toString(),
          title: (j['title'] ?? '').toString(),
          body: (j['body'] ?? '').toString(),
          reason: (j['reason'] ?? '').toString(),
          availableAt: (j['available_at'] ?? '').toString(),
          requiresApproval: j['requires_approval'] == true,
          isRead: j['read_at'] != null);
}

class TroikaNotificationPreferences {
  final bool remindersEnabled, proactiveEnabled, quietHoursEnabled;
  final String timezone, quietStart, quietEnd;
  TroikaNotificationPreferences(
      {required this.remindersEnabled,
      required this.proactiveEnabled,
      required this.quietHoursEnabled,
      required this.timezone,
      required this.quietStart,
      required this.quietEnd});
  factory TroikaNotificationPreferences.fromJson(Map<String, dynamic> j) =>
      TroikaNotificationPreferences(
          remindersEnabled: j['reminders_enabled'] == true,
          proactiveEnabled: j['proactive_enabled'] == true,
          quietHoursEnabled: j['quiet_hours_enabled'] == true,
          timezone: (j['timezone'] ?? 'UTC').toString(),
          quietStart: (j['quiet_start'] ?? '22:00').toString(),
          quietEnd: (j['quiet_end'] ?? '08:00').toString());
  Map<String, dynamic> toJson() => {
        'reminders_enabled': remindersEnabled,
        'proactive_enabled': proactiveEnabled,
        'quiet_hours_enabled': quietHoursEnabled,
        'timezone': timezone,
        'quiet_start': quietStart,
        'quiet_end': quietEnd
      };
  TroikaNotificationPreferences copyWith(
          {bool? remindersEnabled,
          bool? proactiveEnabled,
          bool? quietHoursEnabled,
          String? timezone,
          String? quietStart,
          String? quietEnd}) =>
      TroikaNotificationPreferences(
          remindersEnabled: remindersEnabled ?? this.remindersEnabled,
          proactiveEnabled: proactiveEnabled ?? this.proactiveEnabled,
          quietHoursEnabled: quietHoursEnabled ?? this.quietHoursEnabled,
          timezone: timezone ?? this.timezone,
          quietStart: quietStart ?? this.quietStart,
          quietEnd: quietEnd ?? this.quietEnd);
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
