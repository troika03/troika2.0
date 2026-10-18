import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:flutter/services.dart';

class ProjectCheck {
  final int exitCode;
  final String output;
  final String command;
  final bool timedOut;
  final bool cancelled;
  final bool? _noTests;
  bool get noTests =>
      _noTests == true ||
      RegExp(r'Ran 0 tests?|# tests 0(?:\s|$)').hasMatch(output);
  bool get passed => exitCode == 0 && !timedOut && !cancelled && !noTests;
  const ProjectCheck(this.exitCode, this.output, this.command,
      {this.timedOut = false, this.cancelled = false, bool? noTests})
      : _noTests = noTests;

  Map<String, dynamic> toJson() => {
        'exit_code': exitCode,
        'output': output,
        'timed_out': timedOut,
        'cancelled': cancelled,
        'no_tests': noTests,
      };

  factory ProjectCheck.fromJson(Map<String, dynamic> value, String command) =>
      ProjectCheck(
          value['exit_code'] as int, value['output'] as String, command,
          timedOut: value['timed_out'] == true,
          cancelled: value['cancelled'] == true,
          noTests: value['no_tests'] == true);
}

/// Generated projects are unpacked into a new directory, never over an existing project.
class DevelopmentService {
  static const _native = MethodChannel('troika/development');
  Process? _activeProcess;
  bool _cancelled = false;
  bool _checking = false;
  final String pythonExecutable;
  final String nodeExecutable;
  DevelopmentService(
      {this.pythonExecutable = 'python', this.nodeExecutable = 'node'});

  static Map<String, String> sourcesForModel(Uint8List bytes) {
    final sources = {
      for (final entry in decodeProject(bytes).entries)
        if (entry.key != 'troika-project.json')
          entry.key: utf8.decode(entry.value),
    };
    if (utf8.encode(json.encode(sources)).length > 2 * 1024 * 1024) {
      throw const FormatException(
          'Проект слишком большой для полного ревью модели.');
    }
    final secret = RegExp(
        r'trk_(?:live|refresh)_[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----');
    if (sources.values.any(secret.hasMatch)) {
      throw const FormatException(
          'Исходники содержат секрет. Удали секрет перед передачей ИИ.');
    }
    return sources;
  }

  Future<void> stop() async {
    _cancelled = true;
    if (Platform.isAndroid) {
      await _native.invokeMethod<void>('stop');
      return;
    }
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
    if (bytes.length > 3 * 1024 * 1024) {
      throw const FormatException('Проект слишком большой.');
    }
    final archive = ZipDecoder().decodeBytes(bytes, verify: true);
    if (archive.length > 101) {
      throw const FormatException('Слишком много файлов.');
    }
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
      if (size > 3 * 1024 * 1024) {
        throw const FormatException('Проект слишком большой.');
      }
      final content = Uint8List.fromList(file.content);
      if (content.length != file.size) {
        throw const FormatException('Размер файла не совпадает.');
      }
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
      final parts = path.split('/');
      if (path.isEmpty ||
          path.length > 240 ||
          RegExp(r'[\\<>:"|?*\x00-\x1f]').hasMatch(path) ||
          parts.any((part) =>
              part.isEmpty ||
              part == '.' ||
              part == '..' ||
              {'.env', '.git', 'id_rsa', 'id_ed25519'}
                  .contains(part.toLowerCase()) ||
              part.endsWith('.') ||
              part.endsWith(' '))) {
        throw const FormatException('Небезопасный путь исходника.');
      }
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
      if (size > 120000) {
        throw const FormatException(
            'Проект слишком большой для одного запроса.');
      }
      final source = await file.readAsString();
      if (RegExp(
              r'trk_live_[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----')
          .hasMatch(source)) {
        throw const FormatException(
            'Исходники содержат секрет. Удали секрет перед передачей ИИ.');
      }
      result[path] = source;
    }
    return result;
  }

  Future<Directory> unpack(Uint8List bytes, Directory parent) async {
    final files = decodeProject(bytes);
    final project = Directory(
        '${parent.path}/Troika-project-${DateTime.now().microsecondsSinceEpoch}');
    if (await project.exists()) {
      throw const FileSystemException('Папка проекта уже существует.');
    }
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
    if (_checking) throw StateError('Проверка уже выполняется.');
    _checking = true;
    _cancelled = false;
    try {
      return await _check(project, mode, timeout);
    } finally {
      _checking = false;
    }
  }

  Future<ProjectCheck> _check(
      Directory project, String mode, Duration timeout) async {
    if (Platform.isAndroid) {
      final manifest = json.decode(
              await File('${project.path}/troika-project.json').readAsString())
          as Map<String, dynamic>;
      final paths = (manifest['files'] as List).cast<String>();
      final sources = await readCurrentSources(project, paths);
      if (_cancelled)
        return const ProjectCheck(-1, 'Проверка остановлена.', 'Android',
            cancelled: true);
      final report = await _native.invokeMapMethod<String, dynamic>('check', {
        'mode': mode,
        'files': sources,
        'timeout_ms': timeout.inMilliseconds,
      });
      if (report == null) {
        throw StateError('Телефон не вернул результат проверки.');
      }
      return ProjectCheck.fromJson(report, 'Android: $mode');
    }
    final executable =
        mode.startsWith('javascript') ? nodeExecutable : pythonExecutable;
    final testPaths = <String>[];
    if (mode == 'javascript_tests') {
      await for (final entry
          in project.list(recursive: true, followLinks: false)) {
        if (entry is File &&
            (entry.path.endsWith('.test.js') ||
                entry.uri.pathSegments.last.startsWith('test_') &&
                    entry.path.endsWith('.js'))) {
          testPaths.add(entry.path);
        }
      }
      if (testPaths.isEmpty) {
        return const ProjectCheck(
            2, 'JavaScript-тесты не найдены.', 'node --test',
            noTests: true);
      }
    }
    final baseArgs = switch (mode) {
      'python_syntax' => ['-I', '-m', 'compileall', '-q', '.'],
      'python_tests' => ['-I', '-m', 'unittest', 'discover', '-s', '.', '-v'],
      'javascript' => ['--check', 'index.js'],
      'javascript_tests' => ['--test', ...testPaths],
      _ => throw ArgumentError('Unknown check mode'),
    };
    // Avoid stale project .pyc files after edits with identical size/timestamp.
    final cache = mode.startsWith('javascript')
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
    if (_cancelled) {
      if (cache != null) await cache.delete(recursive: true);
      return const ProjectCheck(-1, 'Проверка остановлена.', 'PC',
          cancelled: true);
    }
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
    if (_cancelled) unawaited(stop());
    void collect(String text) {
      if (output.length < 64000) {
        output.write(
            text.substring(0, text.length.clamp(0, 64000 - output.length)));
      }
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
        timedOut: timedOut, cancelled: _cancelled);
  }
}
