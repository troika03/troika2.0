import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'audio_recorder_service.dart';
import 'assistant_result.dart';
import 'stt_service.dart';
import 'tts_service.dart';
import 'troika_api_service.dart';
import 'wake_word_service.dart';
import 'local_command_service.dart';
import '../config/troika_config.dart';
import 'account_service.dart';

enum AssistantState {
  idle,
  wakeDetected,
  recording,
  processing,
  speaking,
  error,
}

enum BackgroundVoiceState {
  off,
  working,
  permissionRequired,
  systemDisabled,
  unavailable,
}

class AssistantService extends ChangeNotifier {
  static const _lastResultKey = 'troika_last_action_result';
  final AudioRecorderService _recorder = AudioRecorderService();
  final SttService _stt = SttService();
  final TtsService _tts = TtsService();
  final TroikaApiService _troika = TroikaApiService();
  final WakeWordService _wakeWord = WakeWordService();
  final LocalCommandService _localCommands = LocalCommandService();

  AssistantState _state = AssistantState.idle;
  String _lastUserText = '';
  String _lastTroikaText = '';
  AssistantResult? _lastResult;
  String _errorMessage = '';
  String _debugHeard = '';
  String _activityStatus = '';
  bool _wakeWordEnabled = false;
  BackgroundVoiceState _backgroundVoiceState = BackgroundVoiceState.off;
  bool _actionInProgress = false;
  RunApprovalRequest? _pendingApproval;
  Completer<String>? _approvalCompleter;
  String? _pendingUiAction;
  String _pendingUiPrompt = '';

  // Единая лента диалога — голос и текст вперемешку, как в мессенджере.
  final List<ChatMessage> _messages = [];
  bool _historyLoaded = false;

  // Скрытый тег эмоции [emo:...] управляет интонацией голоса. В тексте чата и
  // в произношении локального TTS его быть не должно — вырезаем.
  static final RegExp _emoTag = RegExp(r'\[emo:\s*[A-Za-zА-Яа-яЁё_]+\s*\]');
  static String _stripEmoTag(String s) => s.replaceAll(_emoTag, '').trim();

  AssistantState get state => _state;
  String get lastUserText => _lastUserText;
  String get lastTroikaText => _lastTroikaText;
  AssistantResult? get lastResult => _lastResult;
  String get errorMessage => _errorMessage;
  String get debugHeard => _debugHeard;
  String get liveTranscript {
    if (_state == AssistantState.recording && _debugHeard.trim().isNotEmpty) {
      return _debugHeard.trim();
    }
    if (_state == AssistantState.processing &&
        _lastUserText.trim().isNotEmpty) {
      return _lastUserText.trim();
    }
    return '';
  }

  String get activityStatus =>
      _activityStatus.isEmpty ? 'Выполняю задачу' : _activityStatus;
  bool get wakeWordEnabled => _wakeWordEnabled;
  BackgroundVoiceState get backgroundVoiceState => _backgroundVoiceState;
  String get backgroundVoiceStatus => switch (_backgroundVoiceState) {
        BackgroundVoiceState.working => 'Работает',
        BackgroundVoiceState.permissionRequired => 'Требуется разрешение',
        BackgroundVoiceState.systemDisabled => 'Отключено системой',
        BackgroundVoiceState.unavailable => 'Недоступно на устройстве',
        BackgroundVoiceState.off => 'Выключено',
      };
  bool get isActing => _actionInProgress;
  RunApprovalRequest? get pendingApproval => _pendingApproval;
  List<ChatMessage> get messages => List.unmodifiable(_messages);
  bool get historyLoaded => _historyLoaded;

  ({String action, String prompt})? takePendingUiAction() {
    final action = _pendingUiAction;
    if (action == null) return null;
    final request = (action: action, prompt: _pendingUiPrompt);
    _pendingUiAction = null;
    _pendingUiPrompt = '';
    return request;
  }

  void _queueUiAction(LocalCommandResult result, String prompt) {
    if (result.uiAction.isEmpty) return;
    _pendingUiAction = result.uiAction;
    _pendingUiPrompt = prompt;
  }

  static const _platform = MethodChannel('com.troika.hermes/background');

  Future<void> init() async {
    await _restoreLastResult();
    await _tts.init();
    _wakeWordEnabled = TroikaConfig.wakeWordEnabled;

    _wakeWord.onWakeWordDetected = _onWakeWordConfirmed;
    _wakeWord.onStatusUpdate = (s) => debugPrint('[WakeWord] $s');
    _wakeWord.onDebugHeard = (text) {
      _debugHeard = text;
      notifyListeners();
    };
    // Голосовой диалог (нативный Kotlin) кладёт свои реплики в общую ленту.
    _wakeWord.onVoiceMessage = _onVoiceMessage;

    // Гарантируем что URL/key уже лежат в SharedPreferences с префиксом 'flutter.'
    // (нативный сервис их читает оттуда). Forсируем запись текущих значений.
    TroikaConfig.serverUrl = TroikaConfig.serverUrl;
    TroikaConfig.apiKey = TroikaConfig.apiKey;
    if (TroikaConfig.signedIn) {
      await AccountService().ensureFreshSession();
      unawaited(_troika.syncDeviceTimeZone());
    }

    if (_wakeWordEnabled) {
      await _startWakeWordListening();
    }
    await refreshBackgroundVoiceStatus();

    // Подтянуть историю общей сессии с сервера, чтобы чат открылся не пустым.
    unawaited(loadHistory());
  }

  /// Загрузить ленту общей сессии (голос+текст) с сервера.
  Future<void> loadHistory() async {
    try {
      final loaded = await _troika.loadSessionHistory();
      if (loaded.isNotEmpty) {
        _messages
          ..clear()
          ..addAll(loaded);
      }
      _historyLoaded = true;
      notifyListeners();
    } catch (e) {
      debugPrint('[Assistant] loadHistory failed: $e');
      _historyLoaded = true; // не блокируем UI
      notifyListeners();
    }
  }

  Future<void> setWakeWordEnabled(bool enabled) async {
    _wakeWordEnabled = enabled;
    await TroikaConfig.saveWakeWordEnabled(enabled);
    if (enabled) {
      final micStatus = await Permission.microphone.request();
      if (!micStatus.isGranted) {
        _wakeWordEnabled = false;
        await TroikaConfig.saveWakeWordEnabled(false);
        _setError('Нет доступа к микрофону.');
        return;
      }
      try {
        final ignored = await _platform.invokeMethod<bool>(
              'isBatteryOptimizationIgnored',
            ) ??
            false;
        if (!ignored) {
          await _platform.invokeMethod('requestBatteryOptimizationDisable');
        }
        if (await Permission.notification.isDenied) {
          await Permission.notification.request();
        }
      } catch (e) {
        debugPrint('[Assistant] wake-word setup failed: $e');
      }
      await _startWakeWordListening();
    } else {
      await _wakeWord.stopListening();
    }
    await refreshBackgroundVoiceStatus();
    notifyListeners();
  }

  Future<void> refreshBackgroundVoiceStatus() async {
    if (!_wakeWordEnabled) {
      _backgroundVoiceState = BackgroundVoiceState.off;
      notifyListeners();
      return;
    }
    if (!Platform.isAndroid) {
      _backgroundVoiceState = BackgroundVoiceState.unavailable;
      notifyListeners();
      return;
    }
    try {
      final value = await _platform.invokeMethod<String>(
            'getBackgroundVoiceStatus',
          ) ??
          'system_disabled';
      _backgroundVoiceState = switch (value) {
        'working' => BackgroundVoiceState.working,
        'permission_required' => BackgroundVoiceState.permissionRequired,
        'unavailable' => BackgroundVoiceState.unavailable,
        'off' => BackgroundVoiceState.off,
        _ => BackgroundVoiceState.systemDisabled,
      };
    } catch (_) {
      _backgroundVoiceState = BackgroundVoiceState.systemDisabled;
    }
    notifyListeners();
  }

  Future<void> openBackgroundVoiceRecovery() async {
    if (!Platform.isAndroid) return;
    await _platform.invokeMethod('requestBatteryOptimizationDisable');
    await refreshBackgroundVoiceStatus();
  }

  Future<void> _startWakeWordListening() async {
    if (!_wakeWordEnabled) return;
    await _wakeWord.startListening();
  }

  /// Реплика из нативного голосового диалога → в общую ленту чата.
  /// Dedup: если такое же сообщение только что добавлено (ручной путь или
  /// повтор от Kotlin), не дублируем.
  void _onVoiceMessage(String role, String content) {
    final text = content.trim();
    if (text.isEmpty) return;
    // снять pending-«печатает», если был
    if (role == 'assistant') {
      final idx = _messages.lastIndexWhere((m) => m.pending);
      if (idx >= 0) {
        _messages[idx]
          ..text = text
          ..pending = false;
        notifyListeners();
        return;
      }
    }
    final dup = _messages.isNotEmpty &&
        _messages.last.role == role &&
        _messages.last.text.trim() == text;
    if (dup) return;
    _messages.add(ChatMessage(role: role, text: text, fromVoice: true));
    if (role == 'assistant') {
      _lastTroikaText = text;
      _setLastResult(AssistantResult.forTurn(response: text));
    } else {
      _lastUserText = text;
    }
    notifyListeners();
  }

  /// Wake-word "Гермес" подтверждён Kotlin'ом → начинаем диалог
  Future<void> _onWakeWordConfirmed() async {
    if (_state != AssistantState.idle) return;
    debugPrint('[Assistant] Wake word!');

    _setState(AssistantState.wakeDetected);
    await _tts.speak('Слушаю');
    await Future.delayed(const Duration(milliseconds: 700));
    await startManualRecording();
  }

  Future<void> startManualRecording() async {
    if (_state == AssistantState.recording ||
        _state == AssistantState.processing ||
        _state == AssistantState.speaking) {
      return;
    }
    _debugHeard = '';

    // permission_handler не поддерживает микрофон на десктопе (Windows) —
    // там доступ к устройству проверяет сам record (в AudioRecorderService).
    // Гейт через permission_handler делаем только на мобилке.
    if (Platform.isAndroid || Platform.isIOS) {
      final micStatus = await Permission.microphone.status;
      if (!micStatus.isGranted) {
        final r = await Permission.microphone.request();
        if (!r.isGranted) {
          _setError('Нет доступа к микрофону.');
          return;
        }
      }
    }

    // Десктоп (Windows/Linux/macOS): нативного фонового сервиса нет —
    // ведём весь диалог на Dart-стороне (push-to-talk). Первое нажатие мик
    // начинает запись, повторное (кнопка stop) — останавливает и обрабатывает
    // через stopRecordingAndProcess (запись → STT-прокси :8643 → Troika → TTS).
    if (!Platform.isAndroid) {
      final ok = await _recorder.startRecording();
      if (!ok) {
        _setError('Не удалось начать запись с микрофона.');
        return;
      }
      _setState(AssistantState.recording);
      return;
    }

    // Android сначала распознаёт речь системным SpeechRecognizer и проверяет
    // локальные команды. Облачный запрос выполняется только для свободного
    // вопроса, поэтому команды продолжают работать без PC/API.
    await _recognizeLocalAndroidCommand();
  }

  Future<void> _recognizeLocalAndroidCommand() async {
    _setState(AssistantState.recording);
    try {
      final result = await _localCommands.recognizeAndExecute();
      final heard = result.heard.trim();
      if (heard.isEmpty) {
        _setState(AssistantState.idle);
        return;
      }
      if (!result.handled && TroikaConfig.serverUrl.trim().isNotEmpty) {
        _setState(AssistantState.idle);
        await sendTextQuery(heard, speak: true);
        return;
      }
      _lastUserText = heard;
      _queueUiAction(result, heard);
      _messages.add(ChatMessage(role: 'user', text: heard, fromVoice: true));
      final response = result.handled
          ? result.response
          : 'Эта локальная команда пока не поддерживается.';
      _lastTroikaText = response;
      _setLastResult(AssistantResult.forTurn(
        response: response,
        successfulTools: const ['local_action'],
      ));
      _messages.add(
        ChatMessage(role: 'assistant', text: response, fromVoice: true),
      );
      notifyListeners();
      final mode = await LocalCommandService.currentMode();
      if (mode != 'rest') {
        _setState(AssistantState.speaking);
        await _tts.speak(response);
      }
      _setState(AssistantState.idle);
    } catch (e) {
      _setError('Не удалось выполнить локальную команду: $e');
    }
  }

  Future<void> stopRecordingAndProcess() async {
    if (_state != AssistantState.recording) return;

    _setState(AssistantState.processing);

    final audioFile = await _recorder.stopRecording();
    if (audioFile == null) {
      _setError('Не удалось записать аудио');
      return;
    }

    try {
      final userText = await _stt.transcribe(audioFile);
      await audioFile.delete().catchError((_) => audioFile);

      if (userText.trim().isEmpty) {
        _setError('Не услышал. Попробуй снова.');
        return;
      }

      _lastUserText = userText;
      final userMsg =
          ChatMessage(role: 'user', text: userText, fromVoice: true);
      _messages.add(userMsg);
      final pending = ChatMessage(role: 'assistant', pending: true);
      _messages.add(pending);
      notifyListeners();

      final response = _stripEmoTag(
          await _troika.sendMessage(userMsg, recent: _recentContext()));
      _lastTroikaText = response;
      _setLastResult(AssistantResult.forTurn(response: response));
      pending
        ..text = response
        ..pending = false;
      notifyListeners();

      _setState(AssistantState.speaking);
      await _tts.speak(response);
      _setState(AssistantState.idle);
    } catch (e) {
      await audioFile.delete().catchError((_) => audioFile);
      _messages.removeWhere((m) => m.pending);
      _setError(e.toString());
    }
  }

  /// Несколько последних реплик для немедленного контекста (сервер и так
  /// помнит сессию, но это страхует первый ход после рестарта).
  List<ChatMessage> _recentContext({int n = 6}) {
    final done = _messages.where((m) => !m.pending).toList();
    if (done.length <= 1) return const [];
    final slice =
        done.sublist(0, done.length - 1); // без только что добавленного user
    return slice.length > n ? slice.sublist(slice.length - n) : slice;
  }

  Future<void> interrupt() async {
    // Останавливаем И Flutter-side TTS, И нативный Edge TTS player из
    // HermesListenerService — Тройка молчит сразу.
    try {
      await _platform.invokeMethod('interruptTts');
    } catch (_) {}
    await _tts.stop();
    await _recorder.cancelRecording();
    _setState(AssistantState.idle);
  }

  Future<String> _waitForApproval(RunApprovalRequest request) async {
    // A run is tied to the current device token.  Still require a visible,
    // one-time decision before changing anything on the phone.
    final completer = Completer<String>();
    _pendingApproval = request;
    _approvalCompleter = completer;
    notifyListeners();
    try {
      return await completer.future;
    } finally {
      if (identical(_approvalCompleter, completer)) {
        _approvalCompleter = null;
        _pendingApproval = null;
        notifyListeners();
      }
    }
  }

  void resolvePendingApproval(String choice) {
    final completer = _approvalCompleter;
    if (completer == null || completer.isCompleted) return;
    final allowed = _pendingApproval?.choices ?? const <String>['deny'];
    completer.complete(allowed.contains(choice) ? choice : 'deny');
  }

  /// Отправить текст и/или картинки из чата.
  /// [imageDataUrls] — список data:image/...;base64,... (галерея/камера).
  /// [speak] — проговаривать ли ответ голосом (в текстовом чате обычно нет).
  Future<void> sendTextQuery(
    String text, {
    List<String> imageDataUrls = const [],
    bool speak = false,
  }) async {
    if (text.trim().isEmpty && imageDataUrls.isEmpty) return;

    _lastUserText = text;
    _activityStatus = '';
    final userMsg = ChatMessage(
      role: 'user',
      text: text,
      imageDataUrls: List.of(imageDataUrls),
    );
    _messages.add(userMsg);
    final pending = ChatMessage(role: 'assistant', pending: true);
    _messages.add(pending);
    _setState(AssistantState.processing);
    notifyListeners();

    try {
      if (imageDataUrls.isEmpty) {
        final local = await _localCommands.execute(text);
        if (local.handled) {
          _queueUiAction(local, text);
          final response = local.response.isEmpty ? 'Готово' : local.response;
          _lastTroikaText = response;
          _setLastResult(AssistantResult.forTurn(
            response: response,
            successfulTools: const ['local_action'],
          ));
          pending
            ..text = response
            ..pending = false;
          notifyListeners();
          if (speak) {
            _setState(AssistantState.speaking);
            await _tts.speak(response);
          }
          _setState(AssistantState.idle);
          return;
        }
      }

      if (TroikaConfig.serverUrl.trim().isEmpty) {
        const response = 'Эта локальная команда пока не поддерживается. '
            'Свободные вопросы будут доступны в AI-тарифе.';
        _lastTroikaText = response;
        _setLastResult(AssistantResult.forTurn(response: response));
        pending
          ..text = response
          ..pending = false;
        notifyListeners();
        if (speak) {
          _setState(AssistantState.speaking);
          await _tts.speak(response);
        }
        _setState(AssistantState.idle);
        return;
      }

      // Стримим «поток мыслей»: размышления и вызовы инструментов
      // появляются в пузыре в реальном времени, пока Тройка работает.
      final successfulTools = <String>[];
      RunActionResult? structuredResult;
      final response = await _troika.streamMessage(
        userMsg,
        recent: _recentContext(),
        onThought: (t) {
          pending.thoughts.add(ThoughtStep(ThoughtKind.thinking, t));
          notifyListeners();
        },
        onToolStart: (tool) {
          _actionInProgress = true;
          _activityStatus = safeActivityStatusForTool(tool);
          pending.thoughts.add(ThoughtStep(ThoughtKind.toolStart, tool));
          notifyListeners();
        },
        onToolDone: (tool, isErr) {
          pending.thoughts
              .add(ThoughtStep(ThoughtKind.toolDone, tool, isError: isErr));
          if (!isErr && tool.trim().isNotEmpty) successfulTools.add(tool);
          notifyListeners();
        },
        onResult: (result) => structuredResult = result,
        onDelta: (d) {
          // Чистим накопленный текст от тега на каждом апдейте, чтобы
          // [emo:...] не мелькал в пузыре пока идёт стрим.
          pending.text = _stripEmoTag(pending.text + d);
          notifyListeners();
        },
        onApproval: _waitForApproval,
      );
      final cleanResponse = _stripEmoTag(response);
      _lastTroikaText = cleanResponse;
      _setLastResult(AssistantResult.forTurn(
        response: cleanResponse,
        successfulTools: successfulTools,
        structuredKind: structuredResult?.kind ?? '',
        structuredTitle: structuredResult?.title ?? '',
        resourceId: structuredResult?.id ?? '',
      ));
      pending
        ..text = cleanResponse
        ..pending = false;
      notifyListeners();

      if (speak) {
        _setState(AssistantState.speaking);
        await _tts.speak(cleanResponse);
      }
      _setState(AssistantState.idle);
    } catch (e) {
      _messages.remove(pending);
      _setError(e.toString());
    } finally {
      _actionInProgress = false;
      _activityStatus = '';
      notifyListeners();
      if (_wakeWordEnabled) await _startWakeWordListening();
    }
  }

  static String safeActivityStatusForTool(String tool) {
    final value = tool.toLowerCase();
    if (value.contains('research') ||
        value.contains('search') ||
        value.contains('web_')) {
      return 'Ищу источники';
    }
    if (value.contains('ppt') || value.contains('presentation')) {
      return 'Создаю презентацию';
    }
    if (value.contains('doc') || value.contains('pdf')) {
      return 'Создаю документ';
    }
    if (value.contains('task') || value.contains('reminder')) {
      return 'Сохраняю задачу';
    }
    if (value.contains('memory')) return 'Обновляю память';
    if (value.contains('android') ||
        value.contains('open_app') ||
        value.contains('open_file')) {
      return 'Открываю приложение';
    }
    return 'Выполняю задачу';
  }

  /// Стереть локальную ленту (визуально). Серверную сессию не трогает.
  void clearConversation() {
    _messages.clear();
    _lastUserText = '';
    _lastTroikaText = '';
    _lastResult = null;
    unawaited(_clearStoredResult());
    notifyListeners();
  }

  void _setLastResult(AssistantResult result) {
    _lastResult = result;
    unawaited(_storeLastResult(result));
  }

  Future<void> _restoreLastResult() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_lastResultKey);
      if (raw == null || raw.isEmpty) return;
      final decoded = json.decode(raw);
      if (decoded is! Map<String, dynamic>) return;
      final restored = AssistantResult.fromJson(decoded);
      if (restored.kind != AssistantResultKind.answer) _lastResult = restored;
    } catch (_) {
      await _clearStoredResult();
    }
  }

  Future<void> _storeLastResult(AssistantResult result) async {
    final prefs = await SharedPreferences.getInstance();
    if (result.kind == AssistantResultKind.answer) {
      await prefs.remove(_lastResultKey);
      return;
    }
    await prefs.setString(_lastResultKey, json.encode(result.toJson()));
  }

  Future<void> _clearStoredResult() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_lastResultKey);
  }

  void _setState(AssistantState s) {
    _state = s;
    notifyListeners();
  }

  void _setError(String msg) {
    _errorMessage = msg;
    _state = AssistantState.error;
    notifyListeners();

    Future.delayed(const Duration(seconds: 4), () {
      if (_state == AssistantState.error) {
        _state = AssistantState.idle;
        if (_wakeWordEnabled) _startWakeWordListening();
        notifyListeners();
      }
    });
  }

  @override
  void dispose() {
    resolvePendingApproval('deny');
    _recorder.dispose();
    _tts.dispose();
    _wakeWord.dispose();
    super.dispose();
  }
}
