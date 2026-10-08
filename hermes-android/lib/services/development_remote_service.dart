import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:archive/archive.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../config/troika_config.dart';
import 'account_service.dart';
import 'development_service.dart';
import 'troika_api_service.dart';

class DevelopmentTarget {
  final String id;
  final String name;
  const DevelopmentTarget(this.id, this.name);
}

/// The PC worker runs only while the development screen is open and enabled.
class DevelopmentRemoteService extends ChangeNotifier {
  final http.Client _client;
  final DevelopmentService _runner;
  Timer? _timer;
  Directory? _root;
  bool _polling = false;
  bool _enabled = false;
  bool _disposed = false;
  String? _outgoing;
  bool _stopOutgoing = false;
  String _owner = '';
  String _session = '';
  String status = '';
  bool get enabled => _enabled;
  final _approvals = <String, (DateTime, int)>{};
  final Future<bool> Function(Map<String, dynamic> job)? approve;

  DevelopmentRemoteService(
      {http.Client? client, DevelopmentService? runner, this.approve})
      : _client = client ?? http.Client(),
        _runner = runner ?? DevelopmentService();

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  Future<Map<String, dynamic>> _request(String method, String path,
      [Map<String, dynamic>? body]) async {
    await AccountService().ensureFreshSession();
    final request = http.Request(
        method, Uri.parse('${TroikaConfig.serverUrl}/v1/development/$path'))
      ..headers.addAll(TroikaConfig.headers);
    if (body != null) {
      request.headers['Content-Type'] = 'application/json';
      request.body = json.encode(body);
    }
    final response = await http.Response.fromStream(await _client.send(request))
        .timeout(const Duration(seconds: 15));
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw TroikaApiException(response.statusCode == 404
          ? 'Проверка на выбранном ПК недоступна. Обнови сервер и клиент ПК.'
          : 'Не удалось передать проверку на ПК (${response.statusCode}).');
    }
    return json.decode(response.body) as Map<String, dynamic>;
  }

  Future<List<DevelopmentTarget>> targets() async {
    final data = await _request('GET', 'devices');
    return [
      for (final item in data['devices'] as List)
        DevelopmentTarget(item['id'] as String, item['name'] as String)
    ];
  }

  static String newWorkflowId() => List.generate(16,
          (_) => Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0'))
      .join();

  Future<ProjectCheck> checkOnPC(Map<String, String> sources, String mode,
      String target, String workflow) async {
    _stopOutgoing = false;
    final owner = TroikaConfig.accountEmail;
    final session = TroikaConfig.sessionId;
    final job = await _request('POST', 'checks', {
      'files': sources,
      'mode': mode,
      'target_device_id': target,
      'workflow_id': workflow,
    });
    final id = job['id'] as String;
    _outgoing = id;
    try {
      final deadline = DateTime.now().add(const Duration(minutes: 3));
      while (DateTime.now().isBefore(deadline)) {
        if (_stopOutgoing ||
            owner != TroikaConfig.accountEmail ||
            session != TroikaConfig.sessionId) {
          if (owner == TroikaConfig.accountEmail &&
              session == TroikaConfig.sessionId) {
            await _request('DELETE', 'checks/$id');
          }
          return ProjectCheck(-1, 'Проверка остановлена.', 'ПК: $mode',
              cancelled: true);
        }
        final current = await _request('GET', 'checks/$id');
        if (current['state'] == 'cancelled') {
          return ProjectCheck(
              -1, 'Проверка отклонена или остановлена на ПК.', 'ПК: $mode',
              cancelled: true);
        }
        if (current['state'] == 'completed') {
          return ProjectCheck.fromJson(
              current['report'] as Map<String, dynamic>, 'ПК: $mode');
        }
        await Future<void>.delayed(const Duration(seconds: 1));
      }
      await _request('DELETE', 'checks/$id');
      return ProjectCheck(-1, 'ПК не завершил проверку вовремя.', 'ПК: $mode',
          timedOut: true);
    } finally {
      _outgoing = null;
    }
  }

  Future<void> stopOutgoing() async {
    _stopOutgoing = true;
    final id = _outgoing;
    if (id != null) await _request('DELETE', 'checks/$id');
  }

  Future<void> enable(Directory root) async {
    if (!Platform.isWindows) {
      throw StateError('Приём проверок доступен на ПК Windows.');
    }
    _root = Directory(await root.resolveSymbolicLinks());
    _owner = TroikaConfig.accountEmail;
    _session = TroikaConfig.sessionId;
    _enabled = true;
    status = 'Готов принимать проверки с телефона.';
    _timer?.cancel();
    _timer =
        Timer.periodic(const Duration(seconds: 5), (_) => unawaited(_poll()));
    await _poll();
    _notify();
  }

  Future<void> disable() async {
    _enabled = false;
    _timer?.cancel();
    _approvals.clear();
    await _runner.stop();
    if (_owner == TroikaConfig.accountEmail &&
        _session == TroikaConfig.sessionId) {
      try {
        await _request('POST', 'worker', {'enabled': false});
      } catch (_) {}
    }
    status = 'Приём проверок выключен.';
    _notify();
  }

  Future<void> _poll() async {
    if (!_enabled || _polling || _disposed) return;
    if (_owner != TroikaConfig.accountEmail ||
        _session != TroikaConfig.sessionId) {
      await disable();
      return;
    }
    _polling = true;
    try {
      final data = await _request('POST', 'worker', {'enabled': true});
      if (!_enabled) return;
      final job = data['job'];
      if (job is Map<String, dynamic>) await _execute(job);
    } catch (_) {
      status = 'Нет связи для проверок с телефона. Повторяю подключение.';
    } finally {
      _polling = false;
      _notify();
    }
  }

  Future<void> _execute(Map<String, dynamic> job) async {
    final id = job['id'] as String;
    final key = '${job['requester_device_id']}:${job['workflow_id']}';
    final previous = _approvals[key];
    var accepted = previous != null &&
        DateTime.now().difference(previous.$1) < const Duration(minutes: 10) &&
        previous.$2 < 4;
    final heartbeat = Timer.periodic(const Duration(seconds: 5), (_) async {
      if (!_enabled) return;
      try {
        await _request('POST', 'worker', {'enabled': true, 'claim': false});
        final current = await _request('GET', 'checks/$id');
        if (current['state'] == 'cancelled') await _runner.stop();
      } catch (_) {
        await _runner.stop();
      }
    });
    try {
      if (!accepted) accepted = await approve?.call(job) ?? false;
      if (!accepted ||
          !_enabled ||
          _owner != TroikaConfig.accountEmail ||
          _session != TroikaConfig.sessionId) {
        await _request('DELETE', 'checks/$id');
        return;
      }
      _approvals[key] =
          // Recheck cancellation after waiting for the local approval dialog.
          (previous?.$1 ?? DateTime.now(), (previous?.$2 ?? 0) + 1);
      final live = await _request('GET', 'checks/$id');
      if (live['state'] != 'running' || !_enabled) return;
      final sources =
          (job['files'] as Map<String, dynamic>).cast<String, String>();
      final archive = Archive();
      for (final entry in sources.entries) {
        archive.addFile(ArchiveFile.string(entry.key, entry.value));
      }
      archive.addFile(ArchiveFile.string('troika-project.json',
          json.encode({'version': 1, 'files': sources.keys.toList()})));
      final project = await _runner.unpack(
          Uint8List.fromList(ZipEncoder().encode(archive)), _root!);
      if (!_enabled) return;
      final ready = await _request('GET', 'checks/$id');
      if (ready['state'] != 'running') return;
      status = 'Проверяю проект из телефона…';
      _notify();
      final result = await _runner.check(project, job['mode'] as String);
      // A cancelled lease cannot be turned into a success after the process exits.
      final current = await _request('GET', 'checks/$id');
      if (current['state'] == 'running' && _enabled) {
        await _request('POST', 'checks/$id/report',
            {'lease': job['lease'], 'report': result.toJson()});
      }
      status = result.passed
          ? 'Проверка прошла. Отчёт отправлен на телефон.'
          : 'Проверка завершена с ошибками. Отчёт отправлен на телефон.';
    } finally {
      heartbeat.cancel();
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    unawaited(disable().whenComplete(_client.close));
    super.dispose();
  }
}
