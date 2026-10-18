import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/screens/development_screen.dart';
import 'package:troika_assistant/services/development_autopilot_service.dart';
import 'package:troika_assistant/services/development_remote_service.dart';
import 'package:troika_assistant/services/development_service.dart';
import 'package:troika_assistant/services/files_service.dart';

class LocalFiles extends FilesService {
  int received = 0;
  @override
  Future<void> recoverPending() async {}
  @override
  Future<List<TroikaFile>> localFiles() async => [];
  @override
  Future<TroikaFile> receiveDeviceFile(Map<String, dynamic> metadata) async {
    received++;
    return TroikaFile(
        id: 'delivery',
        name: 'example.docx',
        size: 10,
        created: 1,
        ext: 'docx',
        mimeType: 'application/zip',
        localPath: '/example.docx');
  }
}

class NoRunner extends DevelopmentService {
  @override
  Future<void> stop() async {}
}

class NoRemote extends DevelopmentRemoteService {
  @override
  Future<List<DevelopmentTarget>> targets() async => [];
  @override
  Future<void> stopOutgoing() async {}
  @override
  Future<void> disable() async {}
}

Map<String, dynamic> project(
        String status, List<Map<String, dynamic>> reports) =>
    {
      'run_id': 'run_project',
      'title': 'Example',
      'status': status,
      'stage': status,
      'workers': [],
      'reports': reports,
    };

void pauseApp() {
  final binding = TestWidgetsFlutterBinding.instance;
  binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
  binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
  binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
}

void resumeApp() {
  final binding = TestWidgetsFlutterBinding.instance;
  if (binding.lifecycleState == AppLifecycleState.paused) {
    binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
  }
  if (binding.lifecycleState == AppLifecycleState.hidden) {
    binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
  }
  binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() async {
    resumeApp();
    SharedPreferences.setMockInitialValues({
      'troika_account_email': 'owner@example.com',
      'troika_session_id': 'conversation'
    });
    await TroikaConfig.init();
  });
  test('observer created after background transition waits for foreground',
      () async {
    var requests = 0;
    pauseApp();
    final controller =
        DevelopmentAutopilotService(requestForTesting: (_, __, ___) async {
      requests++;
      return {'enabled': true, 'projects': []};
    });
    addTearDown(() {
      controller.dispose();
      resumeApp();
    });
    await controller.observe();
    expect(requests, 0);
    expect(controller.needsBackgroundObservation, true);
    resumeApp();
    await controller.refresh();
    expect(requests, greaterThan(0));
    expect(controller.needsBackgroundObservation, false);
  });
  test('start accepted after leaving the app still hands off to native worker',
      () async {
    final accepted = Completer<Map<String, dynamic>>();
    final posted = Completer<void>();
    var snapshot = project('completed', []);
    final controller = DevelopmentAutopilotService(
        requestForTesting: (method, path, body) async {
      if (method == 'POST') {
        posted.complete();
        return accepted.future;
      }
      return {
        'enabled': true,
        'projects': [snapshot]
      };
    });
    addTearDown(() {
      controller.dispose();
      resumeApp();
    });
    await controller.observe();
    final start = controller.start('Background project');
    await posted.future;
    pauseApp();
    accepted.complete({'run_id': 'run_new'});
    await start;
    expect(controller.projects.single['run_id'], 'run_project');
    expect(controller.needsBackgroundObservation, true);
    snapshot = {...project('completed', []), 'run_id': 'run_new'};
    resumeApp();
    await controller.refresh();
    expect(controller.needsBackgroundObservation, false);
  });
  test(
      'background start preserves conversation and retries unknown delivery with same key',
      () async {
    final keys = <String>[];
    final controller = DevelopmentAutopilotService(
        requestForTesting: (method, path, body) async {
      if (method == 'GET') return {'enabled': true, 'projects': []};
      keys.add(body!['idempotency_key'].toString());
      expect(body['workflow'], 'development');
      expect(body.containsKey('session_id'), false);
      if (keys.length == 1) throw StateError('Network interrupted');
      return {'run_id': 'run_project'};
    });
    addTearDown(controller.dispose);
    final conversation = TroikaConfig.sessionId;
    await expectLater(controller.start('Create website'), throwsStateError);
    expect(await controller.start('Create website'), 'run_project');
    expect(keys.toSet().length, 1);
    expect(TroikaConfig.sessionId, conversation);
  });
  test(
      'fresh protocol handshake blocks legacy server even after an earlier Pro snapshot',
      () async {
    var unavailable = false;
    var posts = 0;
    final controller = DevelopmentAutopilotService(
        requestForTesting: (method, path, body) async {
      if (method == 'POST') posts++;
      if (unavailable) throw StateError('Server update required');
      return {'enabled': true, 'projects': []};
    });
    addTearDown(controller.dispose);
    await controller.observe();
    unavailable = true;
    await expectLater(controller.start('Create website'), throwsStateError);
    expect(posts, 0);
  });
  test(
      'reports wait for conversation idle, coalesce completed project and do not repeat',
      () async {
    var idle = false;
    final spoken = <String>[];
    var snapshot = project('running', [
      {'id': 1, 'stage': 'planning', 'text': 'Plan ready'}
    ]);
    final controller = DevelopmentAutopilotService(
        requestForTesting: (_, __, ___) async => {
              'enabled': true,
              'projects': [snapshot]
            });
    addTearDown(controller.dispose);
    controller.speakWhenIdle = (text) async {
      if (!idle) return false;
      spoken.add(text);
      return true;
    };
    await controller.observe();
    expect(spoken, isEmpty);
    snapshot = project('completed', [
      {'id': 1, 'stage': 'planning', 'text': 'Plan ready'},
      {'id': 2, 'stage': 'completed', 'text': 'Project ready'},
    ]);
    await controller.refresh();
    idle = true;
    await controller.drainReports();
    await controller.refresh();
    expect(spoken, ['Example. Project ready']);
  });
  test(
      'resumed attempt retires the old pause report before announcing completion',
      () async {
    var snapshot = project('paused', [
      {'id': 1, 'text': 'Old pause'}
    ]);
    final controller = DevelopmentAutopilotService(
        requestForTesting: (_, __, ___) async => {
              'enabled': true,
              'projects': [snapshot]
            });
    addTearDown(controller.dispose);
    await controller.observe();
    snapshot = {
      ...project('completed', [
        {'id': 1, 'text': 'New result'}
      ]),
      'run_id': 'new_attempt'
    };
    final spoken = <String>[];
    controller.speakWhenIdle = (text) async {
      spoken.add(text);
      return true;
    };
    await controller.refresh();
    await controller.drainReports();
    await controller.refresh();
    expect(spoken, ['Example. New result']);
  });
  test('mute clears announcements and cancels active project voice', () async {
    var stopped = 0;
    final spoken = <String>[];
    final snapshot = project('running', [
      {'id': 1, 'stage': 'planning', 'text': 'Plan ready'}
    ]);
    final controller = DevelopmentAutopilotService(
        requestForTesting: (_, __, ___) async => {
              'enabled': true,
              'projects': [snapshot]
            });
    addTearDown(controller.dispose);
    controller.speakWhenIdle = (_) async => false;
    controller.stopSpeakingReport = () async {
      stopped++;
    };
    await controller.observe();
    await controller.setVoiceReports(false);
    await controller.setVoiceReports(true);
    controller.speakWhenIdle = (text) async {
      spoken.add(text);
      return true;
    };
    await controller.refresh();
    expect(stopped, 1);
    expect(spoken, isEmpty);
  });
  test('account switch discards private snapshots and announcements', () async {
    var interrupted = 0;
    final spoken = <String>[];
    final controller = DevelopmentAutopilotService(
        requestForTesting: (_, __, ___) async => {
              'enabled': true,
              'projects': [
                project('running', [
                  {'id': 1, 'stage': 'planning', 'text': 'Private report'}
                ])
              ],
            });
    addTearDown(controller.dispose);
    controller.speakWhenIdle = (_) async => false;
    await controller.observe();
    controller.stopSpeakingReport = () async {
      interrupted++;
    };
    await (await SharedPreferences.getInstance())
        .setString('troika_account_email', 'another@example.com');
    controller.speakWhenIdle = (text) async {
      spoken.add(text);
      return true;
    };
    await controller.refresh();
    await controller.drainReports();
    expect(controller.projects, isEmpty);
    expect(controller.results, isEmpty);
    expect(spoken, isEmpty);
    expect(interrupted, 1);
  });
  test(
      'completed artifact is received once and project stop targets its own Run',
      () async {
    final files = LocalFiles();
    final paths = <String>[];
    final snapshot = {
      ...project('completed', []),
      'artifact': {'id': 'delivery'}
    };
    final controller = DevelopmentAutopilotService(
        files: files,
        requestForTesting: (method, path, body) async {
          paths.add('$method $path');
          return {
            'enabled': true,
            'projects': [snapshot]
          };
        });
    addTearDown(controller.dispose);
    await controller.observe();
    await controller.refresh();
    await controller.stopProject('run_project');
    expect(files.received, 1);
    expect(controller.results['run_project']!.ext, 'docx');
    expect(paths, contains('POST /v1/runs/run_project/stop'));
  });
  testWidgets(
      'leaving Development leaves app observer and server project running',
      (tester) async {
    final paths = <String>[];
    final files = LocalFiles();
    final controller = DevelopmentAutopilotService(
        files: files,
        requestForTesting: (method, path, body) async {
          paths.add('$method $path');
          return {
            'enabled': true,
            'projects': [project('running', [])]
          };
        });
    await tester.pumpWidget(MaterialApp(
        home: DevelopmentScreen(
            autopilot: controller,
            files: files,
            runner: NoRunner(),
            remote: NoRemote(),
            androidForTesting: true,
            windowsForTesting: false)));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));
    await tester.scrollUntilVisible(find.text('Example'), 200,
        scrollable: find
            .descendant(
                of: find.byType(ListView).first,
                matching: find.byType(Scrollable))
            .first);
    expect(find.text('Example'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    await tester.pump();
    await controller.refresh();
    expect(controller.projects.length, 1);
    expect(paths.where((p) => p.endsWith('/stop')), isEmpty);
    controller.dispose();
  });
}
