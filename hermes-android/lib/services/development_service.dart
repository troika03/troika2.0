import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:archive/archive.dart';

class ProjectCheck {
  final int exitCode;
  final String output;
  final String command;
  final bool timedOut;
  bool get noTests => RegExp(r'Ran 0 tests?').hasMatch(output);
  const ProjectCheck(this.exitCode, this.output, this.command,
      {this.timedOut = false});
}

/// Generated projects are unpacked into a new directory, never over an existing project.
class DevelopmentService {
  Process? _activeProcess;
  final String pythonExecutable;
  final String nodeExecutable;
  DevelopmentService(
      {this.pythonExecutable = 'python', this.nodeExecutable = 'node'});

  Future<void> stop() async {
    final process = _activeProcess;
    if (process == null) return;
    if (Platform.isWindows) {
      try {
        final result = await Process.run(
            'taskkill', ['/PID', '${process.pid}', '/T', '/F']);
        if (result.exitCode != 0) process.kill();
      } catch (_) {
        process.kill();
      }
    } else {
      process.kill(ProcessSignal.sigkill);
    }
  }

  static Map<String, Uint8List> decodeProject(Uint8List bytes) {
    if (bytes.length > 3 * 1024 * 1024)
      throw const FormatException('Проект слишком большой.');
    final archive = ZipDecoder().decodeBytes(bytes, verify: true);
    if (archive.length > 101)
      throw const FormatException('Слишком много файлов.');
    final result = <String, Uint8List>{};
    var size = 0;
    final names = <String>{};
    for (final file in archive) {
      final name = file.name;
      final parts = name.split('/');
      if (!file.isFile ||
          file.isSymbolicLink ||
          name.length > 240 ||
          parts.any((p) =>
              p.isEmpty ||
              p == '.' ||
              p == '..' ||
              p == '.git' ||
              {'.git', '.env', 'id_rsa', 'id_ed25519'}
                  .contains(p.toLowerCase()) ||
              p.endsWith('.') ||
              p.endsWith(' ')) ||
          RegExp(r'[\\<>:"|?*\x00-\x1f]').hasMatch(name) ||
          parts.any((p) => RegExp(
                  r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$',
                  caseSensitive: false)
              .hasMatch(p)) ||
          result.keys.any((p) =>
              name.toLowerCase().startsWith('${p.toLowerCase()}/') ||
              p.toLowerCase().startsWith('${name.toLowerCase()}/')) ||
          !names.add(name.toLowerCase())) {
        throw const FormatException('Небезопасный путь в проекте.');
      }
      size += file.size;
      if (size > 3 * 1024 * 1024)
        throw const FormatException('Проект слишком большой.');
      final content = Uint8List.fromList(file.content);
      if (content.length != file.size)
        throw const FormatException('Размер файла не совпадает.');
      utf8.decode(
          content); // Project files must be text, not executable binaries.
      result[name] = content;
    }
    final manifest = result['troika-project.json'];
    if (manifest == null) throw const FormatException('Это не проект Тройки.');
    final decoded = json.decode(utf8.decode(manifest)) as Map<String, dynamic>;
    if (decoded['version'] != 1 ||
        decoded['files'] is! List ||
        (decoded['files'] as List).length != result.length - 1 ||
        (decoded['files'] as List).toSet().length !=
            (decoded['files'] as List).length ||
        !(decoded['files'] as List).every((p) =>
            p is String &&
            p != 'troika-project.json' &&
            result.containsKey(p))) {
      throw const FormatException('Список файлов проекта повреждён.');
    }
    return result;
  }

  static Future<Map<String, String>> readCurrentSources(
      Directory root, Iterable<String> paths) async {
    final result = <String, String>{};
    var size = 0;
    for (final path in paths) {
      var current = root.path;
      for (final part in path.split('/')) {
        current = '$current/$part';
        if (await FileSystemEntity.type(current, followLinks: false) ==
            FileSystemEntityType.link) {
          throw const FormatException('Ссылки в проекте нельзя передавать ИИ.');
        }
      }
      final file = File(current);
      size += await file.length();
      if (size > 120000)
        throw const FormatException(
            'Проект слишком большой для одного запроса.');
      result[path] = await file.readAsString();
    }
    return result;
  }

  Future<Directory> unpack(Uint8List bytes, Directory parent) async {
    final files = decodeProject(bytes);
    final project = Directory(
        '${parent.path}/Troika-project-${DateTime.now().microsecondsSinceEpoch}');
    if (await project.exists())
      throw const FileSystemException('Папка проекта уже существует.');
    await project.create(recursive: true);
    for (final entry in files.entries) {
      final file = File('${project.path}/${entry.key}');
      await file.parent.create(recursive: true);
      await file.writeAsBytes(entry.value, flush: true);
    }
    return project;
  }

  /// Fixed commands only; execution still has the user's OS permissions, not a sandbox.
  Future<ProjectCheck> check(Directory project, String mode,
      {Duration timeout = const Duration(seconds: 60)}) async {
    final executable = mode == 'javascript' ? nodeExecutable : pythonExecutable;
    final baseArgs = switch (mode) {
      'python_syntax' => ['-I', '-m', 'compileall', '-q', '.'],
      'python_tests' => ['-I', '-m', 'unittest', 'discover', '-s', '.', '-v'],
      'javascript' => ['--check', 'index.js'],
      _ => throw ArgumentError('Unknown check mode'),
    };
    // Avoid stale project .pyc files after edits with identical size/timestamp.
    final cache = mode == 'javascript'
        ? null
        : await Directory.systemTemp.createTemp('troika-check-cache-');
    final args = cache == null
        ? baseArgs
        : [
            '-I',
            '-B',
            '-X',
            'pycache_prefix=${cache.path}',
            ...baseArgs.skip(1)
          ];
    final process = await Process.start(executable, args,
        workingDirectory: project.path,
        runInShell: false,
        includeParentEnvironment: false,
        environment: {
          for (final name in [
            'PATH',
            'SystemRoot',
            'WINDIR',
            'TEMP',
            'TMP',
            'PATHEXT'
          ])
            if (Platform.environment[name] != null)
              name: Platform.environment[name]!,
          'PYTHONIOENCODING': 'utf-8',
          'PYTHONUTF8': '1',
        });
    final output = StringBuffer();
    _activeProcess = process;
    void collect(String text) {
      if (output.length < 64000)
        output.write(
            text.substring(0, text.length.clamp(0, 64000 - output.length)));
    }

    final drains = [process.stdout, process.stderr].map((s) async {
      await for (final text
          in s.transform(const Utf8Decoder(allowMalformed: true))) {
        collect(text);
      }
    }).toList();
    var timedOut = false;
    final timer = Timer(timeout, () {
      timedOut = true;
      unawaited(stop());
    });
    final code = await process.exitCode;
    timer.cancel();
    _activeProcess = null;
    await Future.wait(drains)
        .timeout(const Duration(seconds: 2), onTimeout: () => []);
    if (cache != null) {
      await cache.delete(recursive: true);
    }
    return ProjectCheck(
        code, output.toString(), '$executable ${args.join(' ')}',
        timedOut: timedOut);
  }
}
