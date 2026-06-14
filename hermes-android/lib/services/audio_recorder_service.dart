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
    final status = await Permission.microphone.request();
    return status.isGranted;
  }

  /// Начать запись в WAV файл
  Future<bool> startRecording() async {
    if (_isRecording) return false;

    final hasPermission = await requestPermission();
    if (!hasPermission) return false;

    final dir = await getTemporaryDirectory();
    _currentPath = '${dir.path}/hermes_voice_${DateTime.now().millisecondsSinceEpoch}.m4a';

    await _recorder.start(
      const RecordConfig(
        encoder: AudioEncoder.aacLc,
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
