import 'dart:convert';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/assistant_service.dart';
import '../services/development_service.dart';
import '../services/files_service.dart';

class DevelopmentScreen extends StatefulWidget {
  const DevelopmentScreen({super.key});
  @override
  State<DevelopmentScreen> createState() => _DevelopmentScreenState();
}

class _DevelopmentScreenState extends State<DevelopmentScreen> {
  final _task = TextEditingController();
  final _runner = DevelopmentService();
  List<TroikaFile> _projects = [];
  TroikaFile? _selected;
  Directory? _directory;
  String _status = '';
  String _mode = 'python_syntax';
  ProjectCheck? _check;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _perform(_load);
  }

  @override
  void dispose() {
    _runner.stop();
    _task.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      await FilesService().recoverPending();
    } catch (_) {}
    final files = await FilesService().localFiles();
    if (mounted)
      setState(() {
        _projects = files.where((f) => f.ext == 'zip').toList();
      });
  }

  Future<void> _perform(Future<void> Function() action) async {
    setState(() {
      _busy = true;
      _status = '';
    });
    try {
      await action();
    } catch (error) {
      if (mounted)
        setState(() {
          _status = 'Не удалось выполнить: $error';
        });
    } finally {
      if (mounted)
        setState(() {
          _busy = false;
        });
    }
  }

  Future<void> _generate() async {
    if (_task.text.trim().isEmpty) return;
    final assistant = context.read<AssistantService>();
    final previousIds = _projects.map((project) => project.id).toSet();
    await assistant.sendTextQuery('Разработай проект: ${_task.text.trim()}. '
        'Используй troika_create_project. Включи исходники, README и тесты. '
        'Python unittest-тесты положи в корень как test_*.py. '
        'Для JavaScript основной файл index.js. Не утверждай, что тесты запускались.');
    await _load();
    final newProjects =
        _projects.where((project) => !previousIds.contains(project.id));
    if (mounted && assistant.errorMessage.isEmpty && newProjects.isNotEmpty) {
      setState(() {
        _selected = newProjects.first;
        _directory = null;
        _check = null;
      });
    }
    if (mounted)
      setState(() {
        _status = assistant.errorMessage.isNotEmpty
            ? assistant.errorMessage
            : assistant.lastResult?.summary ??
                'Проверь ответ Тройки на главном экране.';
      });
  }

  Future<void> _unpack() async {
    if (_selected == null) return;
    final folder = await FilePicker.platform
        .getDirectoryPath(dialogTitle: 'Выбери папку для нового проекта');
    if (folder == null) return;
    final bytes = await File(_selected!.localPath!).readAsBytes();
    final directory =
        await DevelopmentService().unpack(bytes, Directory(folder));
    if (mounted)
      setState(() {
        _directory = directory;
        _check = null;
        _status = 'Проект сохранён: ${directory.path}';
      });
  }

  Future<void> _runCheck() async {
    if (_directory == null) return;
    final approved = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
              title: const Text('Запустить проверку на этом ПК?'),
              content: Text(_mode == 'python_tests'
                  ? 'Тесты запускают код проекта с правами твоей учётной записи. Сначала просмотри исходники. Это не изолированная среда.'
                  : 'Будет запущена проверка синтаксиса файлов проекта. Содержимое программы не выполняется.'),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(ctx, false),
                    child: const Text('Отмена')),
                FilledButton(
                    onPressed: () => Navigator.pop(ctx, true),
                    child: const Text('Запустить'))
              ],
            ));
    if (approved != true) return;
    final check = await _runner.check(_directory!, _mode);
    if (mounted)
      setState(() {
        _check = check;
        _status = check.timedOut
            ? 'Проверка остановлена по времени.'
            : check.noTests
                ? 'Тесты не найдены. Качество кода не подтверждено.'
                : 'Код завершения: ${check.exitCode}';
      });
  }

  Future<void> _fix() async {
    if (_directory == null || _check == null || _selected == null) return;
    final paths = DevelopmentService.decodeProject(
            await File(_selected!.localPath!).readAsBytes())
        .keys;
    final files =
        await DevelopmentService.readCurrentSources(_directory!, paths);
    final source = json.encode(files);
    if (source.length > 120000)
      throw const FormatException(
          'Проект слишком большой для одного запроса исправления.');
    if (!mounted) return;
    final assistant = context.read<AssistantService>();
    final previousIds = _projects.map((project) => project.id).toSet();
    await assistant.sendTextQuery(
        'Исправь проект по реальному результату проверки. '
        'Верни новую полную версию через troika_create_project; исходную не перезаписывай. '
        'Команда: ${_check!.command}; exit=${_check!.exitCode}; timeout=${_check!.timedOut}. '
        'Вывод: ${_check!.output}\nИсходники: $source');
    await _load();
    final newProjects =
        _projects.where((project) => !previousIds.contains(project.id));
    if (mounted)
      setState(() {
        if (assistant.errorMessage.isNotEmpty) {
          _status = assistant.errorMessage;
        } else if (newProjects.isNotEmpty) {
          _selected = newProjects.first;
          _directory = null;
          _check = null;
          _status =
              'Новая версия сохранена. Распакуй её в новую папку и повтори проверку.';
        } else {
          _status =
              'Новый проект не получен. Проверь ответ Тройки на главном экране.';
        }
      });
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Разработка')),
        body: ListView(padding: const EdgeInsets.all(20), children: [
          const Text(
              'Опиши задачу. Тройка подготовит код, тесты и инструкцию. Проект сохранится на этом устройстве.'),
          const SizedBox(height: 16),
          TextField(
              controller: _task,
              maxLines: 4,
              decoration: const InputDecoration(labelText: 'Что разработать?')),
          const SizedBox(height: 12),
          FilledButton(
              onPressed: _busy ? null : () => _perform(_generate),
              child: const Text('Создать проект через AI')),
          const SizedBox(height: 20),
          for (final project in _projects)
            RadioListTile<TroikaFile>(
                title: Text(project.name),
                value: project,
                groupValue: _selected,
                onChanged: _busy
                    ? null
                    : (v) => setState(() {
                          _selected = v;
                          _directory = null;
                          _check = null;
                        })),
          if (_selected != null)
            OutlinedButton(
                onPressed: _busy ? null : () => _perform(_unpack),
                child: const Text('Сохранить исходники в папку')),
          if (_directory != null) SelectableText(_directory!.path),
          if (!Platform.isWindows)
            const Text(
                'Создание и сохранение проектов доступны здесь. Запуск Python/JS проверок в этой версии доступен на Windows.'),
          if (Platform.isWindows && _directory != null) ...[
            DropdownButton<String>(
                value: _mode,
                items: const [
                  DropdownMenuItem(
                      value: 'python_syntax', child: Text('Python: синтаксис')),
                  DropdownMenuItem(
                      value: 'python_tests',
                      child: Text('Python: unittest-тесты')),
                  DropdownMenuItem(
                      value: 'javascript',
                      child: Text('JavaScript: синтаксис index.js')),
                ],
                onChanged: _busy
                    ? null
                    : (v) => setState(() {
                          _mode = v!;
                          _check = null;
                        })),
            FilledButton(
                onPressed: _busy ? null : () => _perform(_runCheck),
                child: const Text('Проверить на этом ПК')),
          ],
          if (_check != null) ...[
            SelectableText(
                _check!.output.isEmpty ? 'Вывод отсутствует.' : _check!.output),
            OutlinedButton(
                onPressed: _busy ? null : () => _perform(_fix),
                child:
                    const Text('Передать код и результат AI для исправления')),
          ],
          if (_busy) const LinearProgressIndicator(),
          if (_busy && _directory != null)
            TextButton(
                onPressed: _runner.stop,
                child: const Text('Остановить проверку')),
          if (_status.isNotEmpty)
            Padding(
                padding: const EdgeInsets.only(top: 16),
                child: SelectableText(_status)),
        ]),
      );
}
