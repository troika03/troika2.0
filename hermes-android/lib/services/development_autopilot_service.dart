import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../config/troika_config.dart';
import 'account_service.dart';
import 'files_service.dart';
import 'own_api_service.dart';

typedef ProjectRequest = Future<Map<String, dynamic>> Function(
    String method, String path, Map<String, dynamic>? body);

/// App-wide observer. Leaving the development page never cancels server work.
class DevelopmentAutopilotService extends ChangeNotifier {
  static final instance = DevelopmentAutopilotService();
  final ProjectRequest? requestForTesting;
  final FilesService files;
  final Map<String, TroikaFile> results = {};
  List<Map<String, dynamic>> projects = [];
  bool isPro = false;
  bool voiceReports = true;
  String error = '';
  String _owner = '';
  Timer? _timer;
  bool _refreshing = false;
  final Set<String> _receiving = {};
  final Set<String> _spoken = {};
  final List<({String key, String text})> _reports = [];
  Future<bool> Function(String text)? speakWhenIdle;
  Future<void> Function()? stopSpeakingReport;
  final Map<String, String> _startKeys = {};
  bool _speaking = false;

  DevelopmentAutopilotService({this.requestForTesting, FilesService? files})
      : files = files ?? FilesService();

  Future<Map<String, dynamic>> _request(
      String method, String path, Map<String, dynamic>? body) async {
    if (requestForTesting != null)
      return requestForTesting!(method, path, body);
    await AccountService().ensureFreshSession();
    final uri = Uri.parse('${TroikaConfig.serverUrl}$path');
    final headers = {...TroikaConfig.headers};
    if (method == 'POST' && path == '/v1/runs') {
      headers.addAll(await OwnApiService.headers(TroikaConfig.accountEmail));
    }
    final response = await (method == 'GET'
            ? http.get(uri, headers: headers)
            : http.post(uri,
                headers: headers, body: jsonEncode(body)))
        .timeout(const Duration(seconds: 30));
    if (response.statusCode < 200 || response.statusCode >= 300) {
      if (response.statusCode == 404) {
        throw StateError('Для автопилота требуется обновить сервер Тройки.');
      }
      final decoded = jsonDecode(utf8.decode(response.bodyBytes));
      throw StateError(decoded['error'] is Map
          ? decoded['error']['message']?.toString() ?? 'Автопилот недоступен.'
          : 'Автопилот недоступен.');
    }
    return Map<String, dynamic>.from(
        jsonDecode(utf8.decode(response.bodyBytes)) as Map);
  }

  Future<void> observe() async {
    final owner = TroikaConfig.accountEmail;
    if (_owner != owner) {
      if (_owner.isNotEmpty) {
        try {
          await stopSpeakingReport?.call();
        } catch (_) {}
      }
      _owner = owner;
      projects = [];
      results.clear();
      _reports.clear();
      _spoken.clear();
      _startKeys.clear();
      if (requestForTesting == null) {
        final preferences = await SharedPreferences.getInstance();
        voiceReports = preferences.getBool('project_voice:$owner') ?? true;
        _spoken
            .addAll(preferences.getStringList('project_reports:$owner') ?? []);
      }
    }
    _timer ??= Timer.periodic(const Duration(seconds: 4), (_) {
      unawaited(refresh());
      unawaited(drainReports());
    });
    await refresh();
  }

  Future<void> refresh() async {
    if (_owner != TroikaConfig.accountEmail) {
      try {
        await stopSpeakingReport?.call();
      } catch (_) {}
      _owner = '';
      projects = [];
      results.clear();
      _reports.clear();
      isPro = false;
      notifyListeners();
      return;
    }
    if (_refreshing || _owner.isEmpty) return;
    _refreshing = true;
    final owner = _owner;
    try {
      final snapshot = await _request('GET', '/v1/development/projects', null);
      if (owner != TroikaConfig.accountEmail) return;
      isPro = snapshot['enabled'] == true;
      projects = (snapshot['projects'] as List? ?? [])
          .whereType<Map>()
          .map((p) => Map<String, dynamic>.from(p))
          .toList();
      error = '';
      for (final project in projects) {
        final id = project['run_id'].toString();
        if (project['status'] == 'completed' &&
            project['artifact'] is Map &&
            !results.containsKey(id) &&
            !_receiving.contains(id)) {
          _receiving.add(id);
          try {
            final result = await files.receiveDeviceFile(
                Map<String, dynamic>.from(project['artifact'] as Map));
            if (owner == TroikaConfig.accountEmail) results[id] = result;
          } catch (_) {
            project['delivery_error'] =
                'Результат ещё не сохранён. Проверь сеть и повтори скачивание.';
          } finally {
            _receiving.remove(id);
          }
        }
        var reportList =
            (project['reports'] as List? ?? []).whereType<Map>().toList();
        if (['completed', 'failed', 'cancelled'].contains(project['status']) &&
            reportList.isNotEmpty) {
          final latestKey = '$id:${reportList.last['id']}';
          final stale = _reports
              .where((r) => r.key.startsWith('$id:') && r.key != latestKey)
              .toList();
          _spoken.addAll(stale.map((r) => r.key));
          _reports.removeWhere((r) => stale.any((old) => old.key == r.key));
          reportList = [reportList.last];
        }
        final latest = <String, Map>{};
        for (final report in reportList) {
          latest[report['stage'].toString()] = report;
        }
        for (final report in latest.values) {
          final key = '$id:${report['id']}';
          final text = report['text']?.toString() ?? '';
          if (!voiceReports) {
            _spoken.add(key);
            continue;
          }
          if (!_spoken.contains(key) &&
              text.isNotEmpty &&
              !_reports.any((r) => r.key == key)) {
            final title = project['title']?.toString() ?? 'Проект';
            _reports.add((key: key, text: '$title. $text'));
          }
        }
      }
      notifyListeners();
      await drainReports();
    } catch (exception) {
      if (owner == TroikaConfig.accountEmail) {
        error = exception.toString().replaceFirst('Bad state: ', '');
        notifyListeners();
      }
    } finally {
      _refreshing = false;
    }
  }

  Future<String> start(String task, {Map<String, String>? sources}) async {
    await observe();
    // Require a fresh protocol handshake, even if the last snapshot was Pro.
    final handshake = await _request('GET', '/v1/development/projects', null);
    if (handshake['enabled'] != true) {
      throw StateError('Разработка доступна только в Pro.');
    }
    final owner = _owner;
    final fingerprint = sha256
        .convert(utf8.encode(jsonEncode([owner, task, sources])))
        .toString();
    final key = _startKeys.putIfAbsent(fingerprint,
        () => 'development-${DateTime.now().microsecondsSinceEpoch}');
    final result = await _request('POST', '/v1/runs', {
      'workflow': 'development',
      'input': task,
      'title': task.length > 70 ? task.substring(0, 70) : task,
      'free_only': true,
      'artifact_delivery': 'device',
      'idempotency_key': key,
      if (sources != null)
        'files': [
          for (final entry in sources.entries)
            {'path': entry.key, 'content': entry.value}
        ],
    });
    if (owner != TroikaConfig.accountEmail) {
      throw StateError('Аккаунт изменился.');
    }
    _startKeys.remove(fingerprint);
    await refresh();
    return result['run_id'].toString();
  }

  Future<void> stopProject(String id) async {
    await _request('POST', '/v1/runs/${Uri.encodeComponent(id)}/stop', {});
    await refresh();
  }

  Future<void> setVoiceReports(bool enabled) async {
    voiceReports = enabled;
    if (requestForTesting == null) {
      final preferences = await SharedPreferences.getInstance();
      await preferences.setBool('project_voice:$_owner', enabled);
    }
    if (!enabled) {
      await stopSpeakingReport?.call();
      _spoken.addAll(_reports.map((r) => r.key));
      _reports.clear();
    }
    notifyListeners();
  }

  Future<void> drainReports() async {
    if (_speaking ||
        !voiceReports ||
        speakWhenIdle == null ||
        _reports.isEmpty ||
        _owner != TroikaConfig.accountEmail) return;
    _speaking = true;
    final owner = _owner;
    final report = _reports.first;
    try {
      if (await speakWhenIdle!(report.text) &&
          owner == TroikaConfig.accountEmail) {
        _spoken.add(report.key);
        _reports.removeWhere((r) => r.key == report.key);
        if (requestForTesting == null) {
          final preferences = await SharedPreferences.getInstance();
          await preferences.setStringList('project_reports:$owner',
              _spoken.toList().reversed.take(400).toList());
        }
      }
    } catch (_) {
      // A failed voice attempt does not erase the visible text report.
    } finally {
      _speaking = false;
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    _timer = null;
    speakWhenIdle = null;
    stopSpeakingReport = null;
    super.dispose(); // Observer disposal never sends project Stop.
  }
}

String projectStage(String stage) => switch (stage) {
      'queued' => 'В очереди',
      'planning' => 'План',
      'designing' => 'Дизайн',
      'implementing' => 'Создание проекта',
      'reviewing' => 'Проверка исходников',
      'repairing' => 'Исправление',
      'waiting_limit' => 'Жду лимит бесплатной модели',
      'completed' => 'Результат готов',
      'cancelled' => 'Остановлено',
      'failed' => 'Требуется внимание',
      _ => 'Выполняется',
    };
