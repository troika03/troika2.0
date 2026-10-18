import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter/services.dart';
import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../config/troika_config.dart';
import 'account_service.dart';
import 'development_checkpoint_store.dart';
import 'files_service.dart';
import 'own_api_service.dart';

typedef ProjectRequest = Future<Map<String, dynamic>> Function(
    String method, String path, Map<String, dynamic>? body);

/// App-wide observer. Leaving the development page never cancels server work.
class DevelopmentAutopilotService extends ChangeNotifier {
  static final instance = DevelopmentAutopilotService();
  final ProjectRequest? requestForTesting;
  final FilesService files;
  late final DevelopmentCheckpointStore checkpoints;
  final Map<String, TroikaFile> results = {};
  List<Map<String, dynamic>> projects = [];
  bool isPro = false;
  bool voiceReports = true;
  bool backgroundReports = true;
  bool _foreground = true;
  AppLifecycleListener? _lifecycle;
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
  final Set<String> _resuming = {};
  final Map<String, DateTime> _resumeAfter = {};
  final Set<String> _pendingHandoffs = {};

  bool get needsBackgroundObservation =>
      _pendingHandoffs.isNotEmpty ||
      (!_foreground && projects.isEmpty && _owner.isNotEmpty) ||
      projects.any((p) => ![
            'completed',
            'failed',
            'cancelled',
            'paused',
            'waiting_budget'
          ].contains(p['status'])) ||
      _reports.isNotEmpty;

  DevelopmentAutopilotService(
      {this.requestForTesting,
      FilesService? files,
      DevelopmentCheckpointStore? checkpointStore})
      : files = files ?? FilesService() {
    checkpoints = checkpointStore ?? DevelopmentCheckpointStore(this.files);
  }

  Future<Map<String, dynamic>> _request(
      String method, String path, Map<String, dynamic>? body) async {
    if (requestForTesting != null)
      return requestForTesting!(method, path, body);
    final requestOwner = TroikaConfig.accountEmail;
    await AccountService().ensureFreshSession();
    if (requestOwner != TroikaConfig.accountEmail)
      throw StateError('Аккаунт изменился.');
    final uri = Uri.parse('${TroikaConfig.serverUrl}$path');
    final headers = {...TroikaConfig.headers};
    if (method == 'POST' && (path == '/v1/runs' || path.endsWith('/resume'))) {
      headers.addAll(await OwnApiService.headers(TroikaConfig.accountEmail));
    }
    if (requestOwner != TroikaConfig.accountEmail)
      throw StateError('Аккаунт изменился.');
    final response = await (method == 'GET'
            ? http.get(uri, headers: headers)
            : http.post(uri, headers: headers, body: jsonEncode(body)))
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
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
      if (_lifecycle == null) {
        final initial = WidgetsBinding.instance.lifecycleState;
        _foreground = initial == null || initial == AppLifecycleState.resumed;
        _lifecycle = AppLifecycleListener(onStateChange: (state) {
          _foreground = state == AppLifecycleState.resumed;
          unawaited(_syncBackground());
          if (_foreground) unawaited(refresh());
        });
      }
    }
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
      _resuming.clear();
      _resumeAfter.clear();
      _pendingHandoffs.clear();
      if (requestForTesting == null) {
        final preferences = await SharedPreferences.getInstance();
        voiceReports = preferences.getBool('project_voice:$owner') ?? true;
        backgroundReports =
            preferences.getBool('project_background:$owner') ?? true;
        _spoken
            .addAll(preferences.getStringList('project_reports:$owner') ?? []);
      }
    }
    _timer ??= Timer.periodic(const Duration(seconds: 4), (_) {
      unawaited(refresh());
      unawaited(drainReports());
    });
    await refresh();
    if (!_foreground) await _syncBackground();
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
      await _syncBackground();
      notifyListeners();
      return;
    }
    if (_refreshing || _owner.isEmpty || !_foreground && backgroundReports)
      return;
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
      final visibleRuns = projects.map((p) => p['run_id'].toString()).toSet();
      _pendingHandoffs.removeWhere(visibleRuns.contains);
      _reports.removeWhere(
          (report) => !visibleRuns.contains(report.key.split(':').first));
      error = '';
      for (final project in projects) {
        final id = project['run_id'].toString();
        final projectId = (project['project_id'] ?? id).toString();
        if (project['checkpoint_revision'] is int) {
          try {
            var local = await checkpoints.read(projectId, owner: owner);
            if ((project['checkpoint_revision'] as int) >
                (local?['revision'] as int? ?? 0)) {
              try {
                final value = await _request('GET',
                    '/v1/development/projects/$projectId/checkpoint', null);
                if (owner != TroikaConfig.accountEmail) return;
                await checkpoints.save(
                    projectId,
                    {
                      ...?local,
                      ...value,
                      'title': project['title'] ?? local?['title'],
                      'run_id': id
                    },
                    owner: owner);
                local = await checkpoints.read(projectId, owner: owner);
                await _request(
                    'POST',
                    '/v1/development/projects/$projectId/checkpoint/received',
                    {'revision': value['revision'], 'digest': value['digest']});
              } catch (_) {
                project['checkpoint_error'] =
                    'Последняя копия ещё не сохранена. Ранее сохранённые файлы доступны.';
              }
            }
            if ((project['title'] ?? '').toString().isEmpty)
              project['title'] = local?['title'] ?? 'Проект';
            project['local_checkpoint'] = local != null;
            if (local != null &&
                local['revision'] == project['checkpoint_revision'] &&
                (project['checkpoint_confirmed'] as int? ?? 0) <
                    (local['revision'] as int)) {
              await _request(
                  'POST',
                  '/v1/development/projects/$projectId/checkpoint/received',
                  {'revision': local['revision'], 'digest': local['digest']});
            }
            final pending = project['status'] == 'paused' &&
                local?['pending_instruction'] is String;
            if ((project['status'] == 'interrupted' || pending) &&
                local != null &&
                !_resuming.contains(projectId) &&
                DateTime.now()
                    .isAfter(_resumeAfter[projectId] ?? DateTime(2000))) {
              _resuming.add(projectId);
              _resumeAfter[projectId] =
                  DateTime.now().add(const Duration(seconds: 30));
              try {
                await _resume(project, local,
                    reuseBudget: !pending,
                    instruction:
                        pending ? local['pending_instruction'] as String : '',
                    budgetTokens:
                        pending ? local['pending_budget'] as int : 100000);
              } finally {
                _resuming.remove(projectId);
              }
            }
          } catch (_) {
            project['checkpoint_error'] =
                'Для продолжения откройте локальную контрольную копию и подтвердите бюджет.';
          }
        }
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
        if ([
              'completed',
              'failed',
              'cancelled',
              'paused',
              'waiting_budget',
              'interrupted'
            ].contains(project['status']) &&
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
      await _syncBackground();
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
      'budget_tokens': 250000,
      'budget_approved': true,
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
    _pendingHandoffs.add(result['run_id'].toString());
    await refresh();
    await _syncBackground();
    return result['run_id'].toString();
  }

  Future<void> stopProject(String id) async {
    final project = projects.where((p) => p['run_id'] == id).firstOrNull;
    if (project?['project_id'] != null) {
      await _request(
          'POST',
          '/v1/development/projects/${project!['project_id']}/control',
          {'action': 'stop'});
    } else {
      await _request('POST', '/v1/runs/${Uri.encodeComponent(id)}/stop', {});
    }
    await refresh();
  }

  Future<void> pauseProject(Map<String, dynamic> project) async {
    final id = project['project_id'] ?? project['run_id'];
    await _request(
        'POST', '/v1/development/projects/$id/control', {'action': 'pause'});
    await refresh();
  }

  Future<void> resumeProject(Map<String, dynamic> project,
      {String instruction = '', int budgetTokens = 100000}) async {
    final id = (project['project_id'] ?? project['run_id']).toString();
    final local = await checkpoints.read(id, owner: _owner);
    if (local == null)
      throw StateError('На устройстве нет контрольной копии проекта.');
    await _resume(project, local,
        instruction: instruction, budgetTokens: budgetTokens);
    await refresh();
  }

  Future<void> clarifyProject(Map<String, dynamic> project, String instruction,
      int budgetTokens) async {
    final id = (project['project_id'] ?? project['run_id']).toString();
    final owner = _owner;
    final local = await checkpoints.read(id, owner: owner);
    if (local == null)
      throw StateError('Дождитесь сохранения первой контрольной копии.');
    await checkpoints.save(
        id,
        {
          ...local,
          'pending_instruction': instruction,
          'pending_budget': budgetTokens
        },
        owner: owner);
    await pauseProject(project);
  }

  Future<void> _resume(Map<String, dynamic> project, Map<String, dynamic> local,
      {String instruction = '',
      int budgetTokens = 100000,
      bool reuseBudget = false}) async {
    final id = (project['project_id'] ?? project['run_id']).toString();
    final owner = _owner;
    if (owner != TroikaConfig.accountEmail)
      throw StateError('Аккаунт изменился.');
    final fingerprint = sha256
        .convert(utf8.encode(jsonEncode(
            [id, local['revision'], instruction, budgetTokens, reuseBudget])))
        .toString();
    final key = _startKeys.putIfAbsent(
        fingerprint, () => 'resume-${DateTime.now().microsecondsSinceEpoch}');
    final started =
        await _request('POST', '/v1/development/projects/$id/resume', {
      'checkpoint': local['checkpoint'],
      'revision': local['revision'],
      'title': local['title'],
      'instruction': instruction,
      'budget_tokens': budgetTokens,
      'reuse_budget': reuseBudget,
      'idempotency_key': key,
    });
    _startKeys.remove(fingerprint);
    if (owner != TroikaConfig.accountEmail) return;
    _pendingHandoffs.add(started['run_id'].toString());
    await _syncBackground();
    final current = await checkpoints.read(id, owner: owner);
    if (current != null && current['pending_instruction'] == instruction) {
      current.remove('pending_instruction');
      current.remove('pending_budget');
      await checkpoints.save(id, current, owner: owner);
    }
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
    await _syncBackground();
  }

  Future<void> setBackgroundReports(bool enabled) async {
    backgroundReports = enabled;
    if (requestForTesting == null) {
      final preferences = await SharedPreferences.getInstance();
      await preferences.setBool('project_background:$_owner', enabled);
    }
    await _syncBackground();
    notifyListeners();
  }

  Future<void> _syncBackground() async {
    if (requestForTesting != null ||
        kIsWeb ||
        defaultTargetPlatform != TargetPlatform.android) return;
    try {
      final response = await DevelopmentCheckpointStore.channel
          .invokeMapMethod<String, dynamic>('configure', {
        'owner': TroikaConfig.accountEmail,
        'server': TroikaConfig.serverUrl,
        'files_root': (await files.localRoot()).path,
        'foreground': _foreground,
        'enabled': backgroundReports && _owner == TroikaConfig.accountEmail,
        'active': needsBackgroundObservation,
        'seen': _spoken.toList().take(400).toList(),
      });
      if (response != null) {
        backgroundReports = response['enabled'] == true;
        _spoken.addAll((response['seen'] as List? ?? []).whereType<String>());
        _reports.removeWhere((r) => _spoken.contains(r.key));
      }
    } on MissingPluginException {
      /* Other desktop clients own their background observer. */
    } catch (_) {
      error = 'Фоновое наблюдение Android недоступно. Откройте Тройку снова.';
    }
  }

  Future<void> drainReports() async {
    if (_speaking ||
        !_foreground && backgroundReports ||
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
    _lifecycle?.dispose();
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
      'testing' => 'Запускаю тесты в изолированной среде',
      'visual_review' => 'Проверяю готовый дизайн',
      'repairing' => 'Исправление',
      'waiting_limit' => 'Жду лимит бесплатной модели',
      'completed' => 'Результат готов',
      'cancelled' => 'Остановлено',
      'failed' => 'Требуется внимание',
      'pausing' => 'Сохраняю и ставлю на паузу',
      'paused' => 'На паузе',
      'waiting_budget' => 'Нужно подтвердить продолжение',
      'interrupted' => 'Восстанавливаю из локальной копии',
      _ => 'Выполняется',
    };
