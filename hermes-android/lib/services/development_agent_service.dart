import 'dart:io';
import 'dart:typed_data';

import '../config/troika_config.dart';
import 'files_service.dart';
import 'troika_api_service.dart';

class GeneratedProject {
  final TroikaFile file;
  final Uint8List bytes;
  const GeneratedProject(this.file, this.bytes);
}

/// Development uses the cloud agent directly: task text is never a phone command.
class DevelopmentAgentService {
  final TroikaApiService _api;
  final FilesService _files;
  String? _runId;
  bool _stopped = false;
  bool _busy = false;

  DevelopmentAgentService({TroikaApiService? api, FilesService? files})
      : _api = api ?? TroikaApiService(),
        _files = files ?? FilesService();

  Future<void> stop() async {
    _stopped = true;
    final id = _runId;
    if (id != null) await _api.stopRun(id);
  }

  Future<GeneratedProject> generate(String prompt,
      {void Function(String status)? onStatus}) async {
    if (_busy) throw StateError('Разработка уже выполняется.');
    _busy = true;
    _stopped = false;
    _runId = null;
    final owner = TroikaConfig.accountEmail;
    final session = TroikaConfig.sessionId;
    TroikaFile? project;
    try {
      await _api.streamMessage(
        ChatMessage(role: 'user', text: prompt),
        onRunStarted: (id) async {
          _runId = id;
          if (_stopped) await _api.stopRun(id);
        },
        onToolStart: (_) => onStatus?.call('Тройка разрабатывает проект…'),
        onResult: (result) async {
          if (_stopped ||
              owner != TroikaConfig.accountEmail ||
              session != TroikaConfig.sessionId) {
            return;
          }
          final artifact = result.artifact;
          if (result.kind == 'file_pending' && artifact?['kind'] == 'zip') {
            project = await _files.receiveDeviceFile(artifact!);
          }
        },
      );
      if (_stopped) throw StateError('Разработка остановлена.');
      if (owner != TroikaConfig.accountEmail ||
          session != TroikaConfig.sessionId) {
        throw StateError('Аккаунт изменился. Разработка остановлена.');
      }
      if (project?.localPath == null) {
        throw StateError(
            'Тройка не передала проект. Код не сохранён; повтори запрос.');
      }
      final bytes = await File(project!.localPath!).readAsBytes();
      return GeneratedProject(project!, bytes);
    } finally {
      _runId = null;
      _busy = false;
    }
  }
}
