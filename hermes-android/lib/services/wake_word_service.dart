import 'package:flutter/services.dart';
import 'package:flutter/foundation.dart';
import '../config/troika_config.dart';

/// Wake-word через нативный Kotlin ForegroundService.
/// Kotlin сам слушает амплитуду, пишет 2.5 сек, шлёт на STT proxy
/// и определяет wake-word. Flutter получает только финальный сигнал.
class WakeWordService {
  WakeWordService({Future<void> Function()? reloadAccountSession})
    : _reloadAccountSession =
          reloadAccountSession ?? TroikaConfig.reloadAccountSession;

  static const _platform = MethodChannel('com.troika.hermes/background');
  final Future<void> Function() _reloadAccountSession;

  bool _isListening = false;
  int _eventGeneration = 0;
  Function()? onWakeWordDetected;
  Function(String)? onStatusUpdate;
  Function(String)? onDebugHeard;
  // Реплика голосового диалога (role, content) → в общую ленту чата.
  void Function(String role, String content)? onVoiceMessage;

  bool get isListening => _isListening;

  Future<void> startListening({
    Future<String> Function(String audioPath)? transcribeFn,
  }) async {
    if (_isListening) return;
    _isListening = true;
    final generation = ++_eventGeneration;

    _platform.setMethodCallHandler(_handleNativeEvent);

    try {
      await _platform.invokeMethod('startListenerService');
      if (!_isListening || generation != _eventGeneration) return;
      onStatusUpdate?.call('Фоновый сервис запущен');
    } catch (e) {
      if (generation != _eventGeneration) return;
      onStatusUpdate?.call('Ошибка запуска: $e');
      _isListening = false;
    }
  }

  Future<void> _handleNativeEvent(MethodCall call) async {
    debugPrint('[Native] ${call.method}');
    if (call.method == 'wake_word_detected' && _isListening) {
      onWakeWordDetected?.call();
    } else if (call.method == 'debug_heard') {
      final text = call.arguments?.toString() ?? '';
      onDebugHeard?.call(text);
    } else if (call.method == 'voice_message') {
      final args = call.arguments;
      if (!_isListening || args is! Map || args['identity'] is! Map) return;
      final role = args['role'];
      final content = args['content'];
      final identity = args['identity'] as Map;
      if ((role != 'user' && role != 'assistant') ||
          content is! String ||
          content.trim().isEmpty) {
        return;
      }
      final generation = _eventGeneration;
      try {
        await _reloadAccountSession();
      } catch (_) {
        return;
      }
      if (!_isListening ||
          generation != _eventGeneration ||
          !_matchesVoiceIdentity(identity)) {
        return;
      }
      onVoiceMessage?.call(role as String, content);
    }
  }

  bool _matchesVoiceIdentity(Map identity) {
    final origin = identity['origin'];
    final owner = identity['owner'];
    final revision = identity['native_generation'];
    final signedIn = identity['signed_in'];
    if (identity['version'] != 1 ||
        origin is! String ||
        owner is! String ||
        identity['session_id'] is! String ||
        identity['session_key'] is! String ||
        revision is! int ||
        signedIn is! bool) {
      return false;
    }
    String normalizeOrigin(String value) =>
        value.trim().replaceFirst(RegExp(r'/+$'), '');
    return signedIn == TroikaConfig.signedIn &&
        (!signedIn || TroikaConfig.voiceSessionAvailable) &&
        revision == TroikaConfig.nativeIdentityRevision &&
        normalizeOrigin(origin) == normalizeOrigin(TroikaConfig.serverUrl) &&
        owner.trim().toLowerCase() == TroikaConfig.accountEmail.toLowerCase() &&
        identity['session_id'] == TroikaConfig.sessionId &&
        identity['session_key'] == TroikaConfig.sessionKey;
  }

  Future<void> stopListening() async {
    _eventGeneration++;
    if (!_isListening) return;
    _isListening = false;
    _platform.setMethodCallHandler(null);
    try {
      await _platform.invokeMethod('stopListenerService');
    } catch (e) {
      debugPrint('Stop error: $e');
    }
  }

  void dispose() => stopListening();
}
