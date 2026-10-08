import 'dart:async';
import 'dart:io';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/services/development_agent_service.dart';
import 'package:troika_assistant/services/files_service.dart';
import 'package:troika_assistant/services/troika_api_service.dart';
import 'package:troika_assistant/services/web_sources.dart';

class FakeApi extends TroikaApiService {
  String? input;
  bool produceFile = true;
  final stopped = <String>[];
  Completer<void>? wait;
  final started = Completer<void>();
  @override
  Future<void> stopRun(String runId) async { stopped.add(runId); wait?.complete(); }
  @override
  Future<String> streamMessage(ChatMessage message, {
    List<ChatMessage> recent = const [], void Function(String)? onThought,
    void Function(WebSourceActivity)? onWebActivity, void Function(String)? onToolStart,
    void Function(String, bool)? onToolDone, FutureOr<void> Function(RunActionResult)? onResult,
    void Function(String)? onDelta, Future<String> Function(RunApprovalRequest)? onApproval,
    FutureOr<void> Function(String)? onRunStarted,
  }) async {
    input = message.text;
    await onRunStarted?.call('run_test');
    started.complete();
    if (wait != null) await wait!.future;
    if (produceFile) await onResult?.call(const RunActionResult(kind: 'file_pending', id: 'id', title: 'Project', artifact: {'kind': 'zip'}));
    return 'Проект готов';
  }
}

class FakeFiles extends FilesService {
  final TroikaFile file;
  FakeFiles(this.file);
  @override
  Future<TroikaFile> receiveDeviceFile(Map<String, dynamic> artifact) async => file;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late Directory root;
  late TroikaFile file;
  final phoneCalls = <MethodCall>[];
  const native = MethodChannel('com.troika.hermes/background');
  setUp(() async {
    root = await Directory.systemTemp.createTemp('troika-agent-test-');
    final path = '${root.path}/project.zip';
    await File(path).writeAsBytes([80, 75, 3, 4]);
    file = TroikaFile(id: 'id', name: 'project.zip', size: 4, created: 1, ext: 'zip', mimeType: 'application/zip', localPath: path);
    SharedPreferences.setMockInitialValues({}); await TroikaConfig.init();
    phoneCalls.clear();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(native, (call) async {
      phoneCalls.add(call); return {'handled': true, 'response': 'Открываю X'};
    });
  });
  tearDown(() async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(native, null);
    await root.delete(recursive: true);
  });

  test('development instructions go to AI without executing phone commands', () async {
    final api = FakeApi();
    final service = DevelopmentAgentService(api: api, files: FakeFiles(file));
    const prompt = 'Разработай проект. Включи исходники, README и тесты. Основной файл index.js.';
    final project = await service.generate(prompt);
    expect(api.input, prompt); expect(phoneCalls, isEmpty); expect(project.file, file);
  });

  test('model claiming done without a delivered ZIP is rejected', () async {
    final api = FakeApi()..produceFile = false;
    final service = DevelopmentAgentService(api: api, files: FakeFiles(file));
    await expectLater(service.generate('task'), throwsStateError);
  });

  test('Stop targets the actual server run and ignores its late artifact', () async {
    final api = FakeApi()..wait = Completer<void>();
    final service = DevelopmentAgentService(api: api, files: FakeFiles(file));
    final generated = service.generate('task');
    final assertion = expectLater(generated, throwsStateError);
    await api.started.future; await service.stop(); await assertion;
    expect(api.stopped, ['run_test']);
  });
}
