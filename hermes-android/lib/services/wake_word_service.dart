import 'package:flutter/services.dart';
import 'package:flutter/foundation.dart';

/// Wake-word через нативный Kotlin ForegroundService.
/// Kotlin сам слушает амплитуду, пишет 2.5 сек, шлёт на STT proxy
/// и определяет wake-word. Flutter получает только финальный сигнал.
class WakeWordService {
  static const _platform = MethodChannel('com.troika.hermes/background');

  bool _isListening = false;
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

    _platform.setMethodCallHandler(_handleNativeEvent);

    try {
      await _platform.invokeMethod('startListenerService');
      onStatusUpdate?.call('Фоновый сервис запущен');
    } catch (e) {
      onStatusUpdate?.call('Ошибка запуска: $e');
      _isListening = false;
    }
  }

  Future<void> _handleNativeEvent(MethodCall call) async {
    debugPrint('[Native] ${call.method} ${call.arguments}');
    if (call.method == 'wake_word_detected' && _isListening) {
      onWakeWordDetected?.call();
    } else if (call.method == 'debug_heard') {
      final text = call.arguments?.toString() ?? '';
      onDebugHeard?.call(text);
    } else if (call.method == 'voice_message') {
      final args = call.arguments;
      if (args is Map) {
        final role = args['role']?.toString() ?? 'assistant';
        final content = args['content']?.toString() ?? '';
        if (content.trim().isNotEmpty) onVoiceMessage?.call(role, content);
      }
    }
  }

  Future<void> stopListening() async {
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
