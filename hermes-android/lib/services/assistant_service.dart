import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:permission_handler/permission_handler.dart';
import 'audio_recorder_service.dart';
import 'stt_service.dart';
import 'tts_service.dart';
import 'hermes_api_service.dart';
import 'wake_word_service.dart';
import '../config/hermes_config.dart';

enum AssistantState {
  idle,
  wakeDetected,
  recording,
  processing,
  speaking,
  error,
}

class AssistantService extends ChangeNotifier {
  final AudioRecorderService _recorder = AudioRecorderService();
  final SttService _stt = SttService();
  final TtsService _tts = TtsService();
  final HermesApiService _hermes = HermesApiService();
  final WakeWordService _wakeWord = WakeWordService();

  AssistantState _state = AssistantState.idle;
  String _lastUserText = '';
  String _lastHermesText = '';
  String _errorMessage = '';
  String _debugHeard = '';
  bool _wakeWordEnabled = true;

  AssistantState get state => _state;
  String get lastUserText => _lastUserText;
  String get lastHermesText => _lastHermesText;
  String get errorMessage => _errorMessage;
  String get debugHeard => _debugHeard;
  bool get wakeWordEnabled => _wakeWordEnabled;

  static const _platform = MethodChannel('com.troika.hermes/background');

  Future<void> init() async {
    await _tts.init();

    final micStatus = await Permission.microphone.request();
    debugPrint('[Assistant] mic: $micStatus');

    // Запросить отключение оптимизации батареи (нужно для фона)
    try {
      final ignored = await _platform.invokeMethod<bool>('isBatteryOptimizationIgnored') ?? false;
      if (!ignored) {
        await _platform.invokeMethod('requestBatteryOptimizationDisable');
      }
    } catch (e) {
      debugPrint('[Assistant] battery opt check failed: $e');
    }

    // Запросить разрешение на overlay (для bottom sheet поверх приложений)
    try {
      final hasOverlay = await _platform.invokeMethod<bool>('hasOverlayPermission') ?? false;
      if (!hasOverlay) {
        await _platform.invokeMethod('requestOverlayPermission');
      }
    } catch (e) {
      debugPrint('[Assistant] overlay check failed: $e');
    }

    // Уведомления (Android 13+)
    if (await Permission.notification.isDenied) {
      await Permission.notification.request();
    }

    _wakeWord.onWakeWordDetected = _onWakeWordConfirmed;
    _wakeWord.onStatusUpdate = (s) => debugPrint('[WakeWord] $s');
    _wakeWord.onDebugHeard = (text) {
      _debugHeard = text;
      notifyListeners();
    };

    // Гарантируем что URL/key уже лежат в SharedPreferences с префиксом 'flutter.'
    // (нативный сервис их читает оттуда). Forсируем запись текущих значений.
    HermesConfig.serverUrl = HermesConfig.serverUrl;
    HermesConfig.apiKey = HermesConfig.apiKey;

    if (micStatus.isGranted && _wakeWordEnabled) {
      await _startWakeWordListening();
    }
  }

  Future<void> setWakeWordEnabled(bool enabled) async {
    _wakeWordEnabled = enabled;
    if (enabled) {
      await _startWakeWordListening();
    } else {
      await _wakeWord.stopListening();
    }
    notifyListeners();
  }

  Future<void> _startWakeWordListening() async {
    if (!_wakeWordEnabled) return;
    await _wakeWord.startListening();
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

    final micStatus = await Permission.microphone.status;
    if (!micStatus.isGranted) {
      final r = await Permission.microphone.request();
      if (!r.isGranted) {
        _setError('Нет доступа к микрофону.');
        return;
      }
    }

    // Весь диалог (запись → STT → Hermes → TTS) идёт в нативном сервисе,
    // он сам берёт микрофон без конфликта с listener loop.
    try {
      await _platform.invokeMethod('triggerDialog');
      _setState(AssistantState.processing);
      // Сбрасываем состояние через 60с (страховка)
      Future.delayed(const Duration(seconds: 60), () {
        if (_state == AssistantState.processing) {
          _setState(AssistantState.idle);
        }
      });
    } catch (e) {
      _setError('Не удалось запустить диалог: $e');
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
      notifyListeners();

      final response = await _hermes.sendMessage(userText);
      _lastHermesText = response;
      notifyListeners();

      _setState(AssistantState.speaking);
      await _tts.speak(response);
      _setState(AssistantState.idle);
    } catch (e) {
      await audioFile.delete().catchError((_) => audioFile);
      _setError(e.toString());
    }
  }

  Future<void> interrupt() async {
    // Останавливаем И Flutter-side TTS, И нативный Edge TTS player из
    // HermesListenerService — Тройка молчит сразу.
    try { await _platform.invokeMethod('interruptTts'); } catch (_) {}
    await _tts.stop();
    await _recorder.cancelRecording();
    _setState(AssistantState.idle);
  }

  Future<void> sendTextQuery(String text) async {
    if (text.trim().isEmpty) return;

    _lastUserText = text;
    _setState(AssistantState.processing);

    try {
      final response = await _hermes.sendMessage(text);
      _lastHermesText = response;
      _setState(AssistantState.speaking);
      notifyListeners();
      await _tts.speak(response);
      _setState(AssistantState.idle);
    } catch (e) {
      _setError(e.toString());
    } finally {
      if (_wakeWordEnabled) await _startWakeWordListening();
    }
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
    _recorder.dispose();
    _tts.dispose();
    _wakeWord.dispose();
    super.dispose();
  }
}
