import 'dart:async';
import 'dart:io';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
import 'package:permission_handler/permission_handler.dart';

/// Сервис записи голоса с микрофона
class AudioRecorderService {
  final AudioRecorder _recorder = AudioRecorder();
  String? _currentPath;
  bool _isRecording = false;

  bool get isRecording => _isRecording;

  /// Запросить разрешение на микрофон
  Future<bool> requestPermission() async {
    // Десктоп (Windows/Linux/macOS): permission_handler не поддерживает
    // микрофон — доступ к устройству проверяет сам record.hasPermission().
    if (!Platform.isAndroid && !Platform.isIOS) {
      try {
        return await _recorder.hasPermission();
      } catch (_) {
        return true; // на Windows доступ к мику обычно не требует runtime-запроса
      }
    }
    final status = await Permission.microphone.request();
    return status.isGranted;
  }

  /// Начать запись в WAV файл
  Future<bool> startRecording() async {
    if (_isRecording) return false;

    final hasPermission = await requestPermission();
    if (!hasPermission) return false;

    // Десктоп (Windows/Linux/macOS): record_windows надёжно пишет WAV/PCM,
    // а AAC-LC там не всегда поддержан. На мобилке оставляем компактный m4a.
    final isDesktop = !Platform.isAndroid && !Platform.isIOS;
    final dir = await getTemporaryDirectory();
    final ext = isDesktop ? 'wav' : 'm4a';
    _currentPath =
        '${dir.path}/hermes_voice_${DateTime.now().millisecondsSinceEpoch}.$ext';

    await _recorder.start(
      RecordConfig(
        encoder: isDesktop ? AudioEncoder.wav : AudioEncoder.aacLc,
        sampleRate: 16000,
        numChannels: 1,
        bitRate: 64000,
      ),
      path: _currentPath!,
    );

    _isRecording = true;
    return true;
  }

  /// Остановить запись и вернуть файл
  Future<File?> stopRecording() async {
    if (!_isRecording) return null;

    final path = await _recorder.stop();
    _isRecording = false;

    if (path == null) return null;
    final file = File(path);
    if (!await file.exists()) return null;
    return file;
  }

  /// Отменить запись (выбросить файл)
  Future<void> cancelRecording() async {
    if (_isRecording) {
      await _recorder.stop();
      _isRecording = false;
      if (_currentPath != null) {
        final f = File(_currentPath!);
        if (await f.exists()) await f.delete();
      }
    }
  }

  void dispose() {
    _recorder.dispose();
  }
}
