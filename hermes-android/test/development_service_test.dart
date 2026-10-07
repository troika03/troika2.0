import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:archive/archive.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:troika_assistant/services/development_service.dart';
import 'package:troika_assistant/services/files_service.dart';

Uint8List project(Map<String, String> files, {List<String>? manifest}) {
  final archive = Archive();
  for (final e in files.entries) {
    archive.addFile(ArchiveFile.string(e.key, e.value));
  }
  archive.addFile(ArchiveFile.string(
      'troika-project.json',
      json.encode({
        'version': 1,
        'files': manifest ?? files.keys.toList(),
      })));
  return Uint8List.fromList(ZipEncoder().encode(archive));
}

void main() {
  test('a hanging local check is stopped by the timeout', () async {
    final root = await Directory.systemTemp.createTemp('troika-timeout-check-');
    addTearDown(() => root.delete(recursive: true));
    await File('${root.path}/test_wait.py')
        .writeAsString('import time\ntime.sleep(30)\n');
    final service = DevelopmentService(
        pythonExecutable:
            Platform.environment['TROIKA_TEST_PYTHON'] ?? 'python');
    final result = await service.check(root, 'python_tests',
        timeout: const Duration(seconds: 1));
    expect(result.timedOut, isTrue);
    expect(result.exitCode, isNot(0));
  });
  test('unpack preserves source and never overwrites an existing project',
      () async {
    final root =
        await Directory.systemTemp.createTemp('troika-development-test-');
    addTearDown(() => root.delete(recursive: true));
    final bytes = project({'main.py': 'print(42)'});
    final first = await DevelopmentService().unpack(bytes, root);
    final second = await DevelopmentService().unpack(bytes, root);
    expect(first.path, isNot(second.path));
    expect(await File('${first.path}/main.py').readAsString(), 'print(42)');
    await File('${first.path}/main.py').writeAsString('print(43)');
    expect(await DevelopmentService.readCurrentSources(first, ['main.py']),
        {'main.py': 'print(43)'});
  });

  for (final paths in [
    {'../escape.py': 'x'},
    {'C:/escape.py': 'x'},
    {'CON.py': 'x'},
    {'.ENV': 'secret'},
    {'a': 'x', 'a/b.py': 'x'},
    {'A.py': 'x', 'a.py': 'x'},
  ]) {
    test('rejects unsafe archive ${paths.keys}', () {
      expect(() => DevelopmentService.decodeProject(project(paths)),
          throwsFormatException);
    });
  }
  test('rejects a duplicated manifest entry hiding a file', () {
    expect(
        () => DevelopmentService.decodeProject(
            project({'a.py': '', 'b.py': ''}, manifest: ['a.py', 'a.py'])),
        throwsFormatException);
  });

  test('local metadata cannot introduce a traversal path', () {
    expect(FilesService.validLocalIdentity('../outside', 'pdf'), isFalse);
    expect(FilesService.validLocalIdentity('delivery_${'a' * 32}', '../pdf'),
        isFalse);
    expect(
        FilesService.validLocalIdentity('delivery_${'a' * 32}', 'zip'), isTrue);
  });
  test('truncated or wrong file content is rejected', () {
    expect(
        () => FilesService.validateDeviceBytes(
            Uint8List.fromList([37, 80, 68, 70, 45]), 'pdf', 6),
        throwsFormatException);
    expect(
        () => FilesService.validateDeviceBytes(
            Uint8List.fromList([0, 0, 0, 0]), 'zip', 4),
        throwsFormatException);
  });

  test(
      'actual Python tests report failure, fixed success, and zero tests honestly',
      () async {
    final root = await Directory.systemTemp.createTemp('troika-python-check-');
    addTearDown(() => root.delete(recursive: true));
    final service = DevelopmentService(
        pythonExecutable:
            Platform.environment['TROIKA_TEST_PYTHON'] ?? 'python');
    await File('${root.path}/test_calc.py').writeAsString(
        'import unittest\nclass Calc(unittest.TestCase):\n def test_sum(self):\n  self.assertEqual(2 + 2, 5)\n');
    final failed = await service.check(root, 'python_tests');
    expect(failed.exitCode, isNot(0));
    expect(failed.output, contains('FAILED'));
    await File('${root.path}/test_calc.py').writeAsString(
        'import unittest\nclass Calc(unittest.TestCase):\n def test_sum(self):\n  self.assertEqual(2 + 2, 4)\n');
    final passed = await service.check(root, 'python_tests');
    expect(passed.exitCode, 0);
    expect(passed.output, contains('Ran 1 test'));
    await File('${root.path}/test_calc.py').delete();
    expect((await service.check(root, 'python_tests')).noTests, isTrue);
  });
}
