import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:archive/archive.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:troika_assistant/services/development_agent_service.dart';
import 'package:troika_assistant/services/development_service.dart';
import 'package:troika_assistant/services/development_workflow.dart';
import 'package:troika_assistant/services/files_service.dart';

GeneratedProject version(Map<String, String> sources, String id) {
  final archive = Archive();
  for (final entry in sources.entries) {
    archive.addFile(ArchiveFile.string(entry.key, entry.value));
  }
  archive.addFile(ArchiveFile.string('troika-project.json',
      json.encode({'version': 1, 'files': sources.keys.toList()})));
  return GeneratedProject(
      TroikaFile(
          id: id,
          name: '$id.zip',
          size: 1,
          created: 1,
          ext: 'zip',
          mimeType: 'application/zip'),
      Uint8List.fromList(ZipEncoder().encode(archive)));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late Directory root;
  setUp(() async {
    root = await Directory.systemTemp.createTemp('troika-workflow-test-');
  });
  tearDown(() async {
    await root.delete(recursive: true);
  });

  test(
      'real failure is sent to AI, replacement is checked and original preserved',
      () async {
    final runner = DevelopmentService();
    var calls = 0;
    final prompts = <String>[];
    final workflow = DevelopmentWorkflow(
        generate: (prompt) async {
          prompts.add(prompt);
          calls++;
          return version({
            'calc.py': 'def add(a,b): return a+b${calls == 1 ? '+1' : ''}\n',
            'test_calc.py':
                'import unittest\nfrom calc import add\nclass Calc(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2, 2), 4)\n',
          }, 'v$calls');
        },
        check: (directory, _, mode) => runner.check(directory, mode),
        stopWork: runner.stop);
    final result = await workflow.run(
        task: 'Сложение', mode: 'python_tests', parent: root);
    expect(result.check!.passed, isTrue);
    expect(result.repairs, 1);
    expect(prompts.last, contains('FAILED'));
    expect(prompts.last, contains('"calc.py"'));
    final directories =
        (await root.list().toList()).whereType<Directory>().toList();
    expect(directories, hasLength(2));
    expect(await File('${directories.first.path}/calc.py').readAsString(),
        contains('+1'));
  });

  test('zero tests never counts as success and triggers bounded repairs',
      () async {
    var calls = 0;
    final workflow = DevelopmentWorkflow(
        generate: (_) async =>
            version({'main.py': 'print(${++calls})'}, 'v$calls'),
        check: (_, __, ___) async =>
            const ProjectCheck(0, 'Ran 0 tests', 'unittest'),
        stopWork: () async {});
    final result = await workflow.run(
        task: 'task', mode: 'python_tests', parent: root, maxRepairs: 2);
    expect(calls, 3);
    expect(result.check!.passed, isFalse);
    expect(result.repairs, 2);
  });

  test('unchanged code stops and does not attach stale proof to new ZIP',
      () async {
    var calls = 0;
    final workflow = DevelopmentWorkflow(
        generate: (_) async => version({'main.py': 'bad code'}, 'v${++calls}'),
        check: (_, __, ___) async =>
            const ProjectCheck(1, 'syntax error', 'python'),
        stopWork: () async {});
    final result =
        await workflow.run(task: 'task', mode: 'python_tests', parent: root);
    expect(calls, 2);
    expect(result.check, isNull);
    expect(result.directory, isNull);
  });

  test('stop during check prevents any repair request', () async {
    late DevelopmentWorkflow workflow;
    var calls = 0;
    workflow = DevelopmentWorkflow(
        generate: (_) async => version({'main.py': '${++calls}'}, 'v$calls'),
        check: (_, __, ___) async {
          await workflow.stop();
          return const ProjectCheck(1, 'failed', 'python');
        },
        stopWork: () async {});
    final result =
        await workflow.run(task: 'task', mode: 'python_tests', parent: root);
    expect(result.stopped, isTrue);
    expect(calls, 1);
  });

  test('creation without a check never executes code', () async {
    final workflow = DevelopmentWorkflow(
        generate: (_) async => version({'main.py': 'x'}, 'v1'),
        check: (_, __, ___) async => throw StateError('Must not check'),
        stopWork: () async {});
    final result = await workflow.run(task: 'task', mode: 'python_tests');
    expect(result.check, isNull);
    expect(result.directory, isNull);
  });

  test('current sources reject traversal and credentials', () async {
    await expectLater(
        DevelopmentService.readCurrentSources(root, ['../outside']),
        throwsFormatException);
    await File('${root.path}/main.py')
        .writeAsString('token="trk_live_abcdefghijklmnopqrstuvwxyz"');
    await expectLater(DevelopmentService.readCurrentSources(root, ['main.py']),
        throwsFormatException);
  });
}
