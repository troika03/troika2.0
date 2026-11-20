import '../widgets/troika_page.dart';
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../services/development_agent_service.dart';
import '../services/development_autopilot_service.dart';
import '../widgets/development_autopilot_panel.dart';
import '../services/development_remote_service.dart';
import '../services/development_service.dart';
import '../services/development_workflow.dart';
import '../services/files_service.dart';
import '../config/troika_config.dart';

class DevelopmentScreen extends StatefulWidget {
  final DevelopmentAgentService? agent;
  final DevelopmentAutopilotService? autopilot;
  final FilesService? files;
  final DevelopmentService? runner;
  final DevelopmentRemoteService? remote;
  final bool? windowsForTesting;
  final bool? androidForTesting;
  const DevelopmentScreen(
      {super.key,
      this.agent,
      this.autopilot,
      this.files,
      this.runner,
      this.remote,
      this.windowsForTesting,
      this.androidForTesting});
  @override
  State<DevelopmentScreen> createState() => _DevelopmentScreenState();
}

class _DevelopmentScreenState extends State<DevelopmentScreen> {
  final _task = TextEditingController();
  late final DevelopmentAgentService _agent;
  DevelopmentAutopilotService? _background;
  late final FilesService _files;
  late final DevelopmentService _runner;
  late final DevelopmentRemoteService _remote;
  DevelopmentWorkflow? _workflow;
  List<TroikaFile> _projects = [];
  TroikaFile? _selected;
  Directory? _directory;
  ProjectCheck? _check;
  String _status = '';
  String _mode = 'model_review';
  String? _modelReport;
  String _executionSummary = '';
  bool _busy = false;
  bool _closing = false;
  int _operation = 0;
  late final String _owner;
  bool get _windows => widget.windowsForTesting ?? Platform.isWindows;
  bool get _android => widget.androidForTesting ?? Platform.isAndroid;

  @override
  void initState() {
    super.initState();
    _owner = TroikaConfig.accountEmail;
    _agent = widget.agent ?? DevelopmentAgentService();
    _background = widget.autopilot ??
        (widget.agent == null ? DevelopmentAutopilotService.instance : null);
    if (_background != null) unawaited(_background!.observe());
    _files = widget.files ?? FilesService();
    _runner = widget.runner ?? DevelopmentService();
    _remote = (widget.remote ??
        DevelopmentRemoteService(approve: _approveRemote))
      ..addListener(_remoteChanged);
    unawaited(_perform(_load));
  }

  void _remoteChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _closing = true;
    unawaited(_stop());
    _remote.removeListener(_remoteChanged);
    _remote.dispose();
    _task.dispose();
    super.dispose();
  }

  Future<void> _stop() async {
    _operation++;
    if (mounted && !_closing)
      setState(() => _status = 'Останавливаю разработку…');
    final operations = <Future<void>>[
      _agent.stop(),
      _runner.stop(),
      _remote.stopOutgoing(),
      if (_workflow != null) _workflow!.stop(),
    ];
    final results = await Future.wait(operations.map((operation) async {
      try {
        await operation;
        return true;
      } catch (_) {
        return false;
      }
    }));
    if (mounted && !_closing && results.contains(false)) {
      setState(() => _status =
          'Не удалось подтвердить остановку всех действий. Повтори остановку.');
    }
  }

  Future<void> _load() async {
    try {
      await _files.recoverPending();
    } catch (_) {}
    final files = await _files.localFiles();
    if (mounted)
      setState(
          () => _projects = files.where((file) => file.ext == 'zip').toList());
  }

  Future<void> _perform(Future<void> Function() action) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _status = '';
    });
    try {
      await action();
    } catch (error) {
      if (mounted)
        setState(
            () => _status = error.toString().replaceFirst('Bad state: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _readModelReview(Map<String, List<int>> files) {
    final manifest = json.decode(utf8.decode(files['troika-project.json']!));
    final review = manifest['review'];
    final report = files['MODEL_REVIEW.md'];
    _modelReport = report == null ? null : utf8.decode(report);
    final execution = review is Map ? review['execution'] : null;
    _executionSummary = switch (execution ?? manifest['execution']) {
      'passed' => 'Тесты прошли в изолированной среде.',
      'failed' => 'Тесты завершились с ошибками.',
      'not_run' => 'Тесты не запускались.',
      _ => 'Результат запуска тестов неизвестен.',
    };
    if (review is! Map || review['method'] != 'api_model_review') {
      _status = 'Проект сохранён. Ревью модели не подтверждено.';
      return;
    }
    final conclusion = review['status'] == 'passed'
        ? 'Модель проверила исходники.'
        : 'Смотри выводы модели в отчёте.';
    _status = 'Проект сохранён. $conclusion $_executionSummary';
  }

  void _showVersion(DevelopmentOutcome version) {
    if (!mounted) return;
    setState(() {
      _selected = version.project.file;
      _directory = version.directory;
      _check = version.check;
      if (!_projects.any((project) => project.id == version.project.file.id)) {
        _projects.insert(0, version.project.file);
      }
    });
  }

  Future<String?> _chooseLocation() async {
    var targets = <DevelopmentTarget>[];
    String? error;
    try {
      targets = await _remote.targets();
    } catch (_) {
      error =
          'Подключённые ПК пока недоступны. На ПК открой «Разработка» и разреши приём проверок.';
    }
    if (!mounted) return null;
    return showModalBottomSheet<String>(
        context: context,
        isScrollControlled: true,
        builder: (context) => SafeArea(
            child: SingleChildScrollView(
                child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Text('Где проверять код?',
                              style: Theme.of(context).textTheme.titleLarge),
                          const SizedBox(height: 16),
                          if (_windows || _android)
                            ListTile(
                                leading: Icon(_windows
                                    ? Icons.computer
                                    : Icons.phone_android),
                                title: Text(_windows
                                    ? 'На этом ПК'
                                    : 'На этом телефоне'),
                                subtitle: Text(_windows
                                    ? 'Python или Node.js должны быть установлены'
                                    : 'Python и переносимый JavaScript, локально и без сети'),
                                onTap: () => Navigator.pop(context, 'local')),
                          for (final target in targets)
                            ListTile(
                                leading: const Icon(Icons.computer),
                                title: Text(target.name),
                                subtitle: const Text(
                                    'ПК попросит разрешение на проверку'),
                                onTap: () => Navigator.pop(context, target.id)),
                          if (targets.isEmpty)
                            Padding(
                                padding:
                                    const EdgeInsets.symmetric(vertical: 8),
                                child: Text(error ??
                                    'Нет ПК, готовых принимать проверки.')),
                          ListTile(
                              title: const Text('Только создать код'),
                              subtitle: const Text(
                                  'Сохранить проект без запуска тестов'),
                              onTap: () => Navigator.pop(context, 'none')),
                        ])))));
  }

  Future<bool> _approveLocal(String location) async {
    if (!mounted) return false;
    return await showDialog<bool>(
            context: context,
            builder: (context) => AlertDialog(
                  title: const Text('Разрешить проверку и исправление?'),
                  content: Text(location == 'local' && _windows
                      ? 'Тройка запустит выбранную проверку и до трёх исправленных версий проекта в новой папке. Код работает с правами твоей учётной записи. Сначала просмотри исходники. Каждый AI-запрос учитывается в тарифе.'
                      : location == 'local'
                          ? 'Тройка проверит проект в локальной среде телефона и выполнит до трёх исправлений. Файлы телефона не доступны коду. Синтаксис отдельно от тестов. Каждый AI-запрос учитывается в тарифе.'
                          : 'Исходники временно передаются выбранному ПК. После его разрешения Тройка проверит проект и до трёх исправленных версий. Постоянная серверная копия не создаётся. Каждый AI-запрос учитывается в тарифе.'),
                  actions: [
                    TextButton(
                        onPressed: () => Navigator.pop(context, false),
                        child: const Text('Отмена')),
                    FilledButton(
                        onPressed: () => Navigator.pop(context, true),
                        child: const Text('Разрешить'))
                  ],
                )) ??
        false;
  }

  Future<bool> _approveRemote(Map<String, dynamic> job) async {
    if (!mounted) return false;
    return await showDialog<bool>(
            context: context,
            barrierDismissible: false,
            builder: (context) => AlertDialog(
                  title: const Text('Проверить проект с телефона?'),
                  content: const Text(
                      'Разрешение действует на этот проект и до трёх исправлений в течение 10 минут. Код запускается с правами твоей учётной записи в выбранной папке. Отчёт вернётся на телефон.'),
                  actions: [
                    TextButton(
                        onPressed: () => Navigator.pop(context, false),
                        child: const Text('Отклонить')),
                    FilledButton(
                        onPressed: () => Navigator.pop(context, true),
                        child: const Text('Разрешить'))
                  ],
                )) ??
        false;
  }

  Future<void> _run({bool selected = false}) async {
    _verifyOwner();
    final operation = ++_operation;
    if (!selected && _task.text.trim().isEmpty) {
      setState(() => _status = 'Опиши, что разработать.');
      return;
    }
    if (_mode == 'model_review') {
      Map<String, String>? sources;
      if (selected && _selected?.localPath != null) {
        sources = DevelopmentService.sourcesForModel(
            await File(_selected!.localPath!).readAsBytes());
      }
      if (_background != null) {
        await _background!.start(
            _task.text.trim().isEmpty
                ? 'Сохрани функции проекта, проверь и исправь ошибки.'
                : _task.text.trim(),
            sources: sources);
        if (mounted) {
          setState(() => _status =
              'Автопилот запущен. Можно вернуться к разговору; проект продолжает работу.');
        }
        return;
      }
      final project = await _agent.generate(
          DevelopmentWorkflow.modelPrompt(
              _task.text.trim().isEmpty
                  ? 'Сохрани функции проекта, проверь и исправь ошибки.'
                  : _task.text.trim(),
              sources: sources), onStatus: (status) {
        if (mounted && operation == _operation)
          setState(() => _status = status);
      });
      if (!mounted || operation != _operation) return;
      _verifyOwner();
      final decoded = DevelopmentService.decodeProject(project.bytes);
      _showVersion(DevelopmentOutcome(project, null, null, 0));
      setState(() => _readModelReview(decoded));
      return;
    }
    _modelReport = null;
    final location = await _chooseLocation();
    if (location == null || !mounted || operation != _operation) return;
    if (location != 'none' && !await _approveLocal(location)) return;
    Directory? parent;
    if (location != 'none') {
      if (_windows && location == 'local') {
        final folder = await FilePicker.platform
            .getDirectoryPath(dialogTitle: 'Папка для версий проекта');
        if (folder == null) return;
        parent = Directory(folder);
      } else {
        parent = Directory('${(await _files.localRoot()).path}/projects');
        await parent.create(recursive: true);
      }
    }
    GeneratedProject? initial;
    if (selected && _selected?.localPath != null) {
      initial = GeneratedProject(
          _selected!, await File(_selected!.localPath!).readAsBytes());
    }
    if (!mounted || operation != _operation) return;
    _verifyOwner();
    final workflowId = DevelopmentRemoteService.newWorkflowId();
    _workflow = DevelopmentWorkflow(
      generate: (prompt) => _agent.generate(prompt, onStatus: (status) {
        if (mounted) setState(() => _status = status);
      }),
      check: (directory, sources, mode) => location == 'local'
          ? _runner.check(directory, mode)
          : _remote.checkOnPC(sources, mode, location, workflowId),
      stopWork: () async {
        await _runner.stop();
        await _agent.stop();
        await _remote.stopOutgoing();
      },
    );
    final outcome = await _workflow!.run(
      task: _task.text.trim().isEmpty
          ? 'Сохрани требования выбранного проекта и исправь ошибки.'
          : _task.text.trim(),
      mode: _mode,
      parent: parent,
      initial: initial,
      onStatus: (status) {
        if (mounted) setState(() => _status = status);
      },
      onVersion: _showVersion,
    );
    _showVersion(outcome);
    if (mounted)
      setState(() {
        _status = outcome.stopped || outcome.check?.cancelled == true
            ? 'Разработка остановлена. Сохранённые версии доступны.'
            : outcome.check == null
                ? 'Проект сохранён. Проверка этой версии не выполнена.'
                : outcome.check!.passed
                    ? (_mode.endsWith('_tests')
                        ? 'Тесты прошли. Проект сохранён.'
                        : 'Синтаксис проверен. Тесты не запускались.')
                    : outcome.check!.timedOut
                        ? 'Проверка остановлена по времени. Проект требует проверки.'
                        : outcome.check!.noTests
                            ? 'Тесты не найдены. Качество кода не подтверждено.'
                            : 'После ${outcome.repairs} исправлений проверка ещё содержит ошибки. Версии сохранены.';
      });
  }

  Future<void> _export() async {
    _verifyOwner();
    if (_selected?.localPath == null) return;
    final folder = await FilePicker.platform
        .getDirectoryPath(dialogTitle: 'Куда сохранить исходники?');
    if (folder == null) return;
    _verifyOwner();
    final directory = await _runner.unpack(
        await File(_selected!.localPath!).readAsBytes(), Directory(folder));
    if (mounted)
      setState(() {
        _directory = directory;
        _status = 'Исходники сохранены: ${directory.path}';
      });
  }

  void _verifyOwner() {
    if (_owner == TroikaConfig.accountEmail) return;
    _selected = null;
    _projects = [];
    _check = null;
    _directory = null;
    throw StateError('Аккаунт изменился. Открой «Разработка» заново.');
  }

  Future<void> _toggleRemote() async {
    if (_remote.enabled) {
      await _remote.disable();
      return;
    }
    final folder = await FilePicker.platform
        .getDirectoryPath(dialogTitle: 'Папка для проектов с телефона');
    if (folder == null || !mounted) return;
    await _remote.enable(Directory(folder));
  }

  @override
  Widget build(BuildContext context) => TroikaPage(
        appBar: AppBar(title: const Text('Разработка')),
        body: Center(
            child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 640),
                child: ListView(padding: const EdgeInsets.all(24), children: [
                  const TroikaIntro(
                      icon: Icons.code_rounded,
                      title: 'Дай идее форму',
                      subtitle:
                          'Опиши проект. Тройка напишет код, проверит исходники моделью и исправит ошибки через API.'),
                  TextField(
                      controller: _task,
                      enabled: !_busy,
                      minLines: 3,
                      maxLines: 6,
                      decoration: const InputDecoration(
                          labelText: 'Что разработать?',
                          hintText:
                              'Например, калькулятор расходов с тестами')),
                  const SizedBox(height: 16),
                  DropdownButtonFormField<String>(
                      value: _mode,
                      isExpanded: true,
                      decoration:
                          const InputDecoration(labelText: 'Проверка проекта'),
                      items: const [
                        DropdownMenuItem(
                            value: 'model_review',
                            child: Text('Модель: ревью и исправление')),
                        DropdownMenuItem(
                            value: 'python_tests',
                            child: Text('Python: тесты unittest')),
                        DropdownMenuItem(
                            value: 'javascript_tests',
                            child: Text('JavaScript: тесты')),
                        DropdownMenuItem(
                            value: 'python_syntax',
                            child: Text('Python: только синтаксис')),
                        DropdownMenuItem(
                            value: 'javascript',
                            child: Text('JavaScript: только синтаксис')),
                      ],
                      onChanged: _busy
                          ? null
                          : (value) => setState(() => _mode = value!)),
                  const SizedBox(height: 16),
                  FilledButton(
                      onPressed: _busy ? null : () => _perform(_run),
                      child: const Text('Разработать проект')),
                  if (_background != null)
                    const Padding(
                        padding: EdgeInsets.only(top: 8),
                        child: Text(
                            'Запуская проект, вы подтверждаете предел 250 000 AI-токенов из месячного остатка. Спишется фактический расход; превышение потребует подтверждения.')),
                  if (_busy) ...[
                    const SizedBox(height: 16),
                    const LinearProgressIndicator(),
                    TextButton(
                        onPressed: _stop, child: const Text('Остановить')),
                  ],
                  if (_status.isNotEmpty)
                    Padding(
                        padding: const EdgeInsets.only(top: 16),
                        child: SelectableText(_status)),
                  if (_background != null)
                    DevelopmentAutopilotPanel(
                        controller: _background!,
                        onOpen: (file) => unawaited(_perform(() async {
                              _verifyOwner();
                              if (file.ext != 'zip') {
                                await _files.openFile(file);
                                return;
                              }
                              final bytes =
                                  await File(file.localPath!).readAsBytes();
                              final decoded =
                                  DevelopmentService.decodeProject(bytes);
                              _selected = file;
                              _readModelReview(decoded);
                              if (!_projects.any((p) => p.id == file.id)) {
                                _projects.insert(0, file);
                              }
                              if (mounted) setState(() {});
                            }))),
                  if (_directory != null)
                    Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: SelectableText(_directory!.path)),
                  if (_check != null)
                    ExpansionTile(
                        title: const Text('Результат проверки'),
                        subtitle: Text('Код завершения: ${_check!.exitCode}'),
                        children: [
                          Padding(
                              padding: const EdgeInsets.all(16),
                              child: SelectableText(_check!.output.isEmpty
                                  ? 'Вывод отсутствует.'
                                  : _check!.output))
                        ]),
                  if (_modelReport != null)
                    ExpansionTile(
                        title: const Text('Ревью модели'),
                        subtitle: Text(_executionSummary),
                        children: [
                          Padding(
                              padding: const EdgeInsets.all(16),
                              child: SelectableText(_modelReport!))
                        ]),
                  const SizedBox(height: 24),
                  Text('Сохранённые проекты',
                      style: Theme.of(context).textTheme.titleMedium),
                  if (_projects.isEmpty)
                    const Padding(
                        padding: EdgeInsets.symmetric(vertical: 12),
                        child: Text(
                            'Здесь появятся исходники и версии твоих проектов.')),
                  for (final project in _projects)
                    RadioListTile<TroikaFile>(
                        title: Text(project.name),
                        value: project,
                        groupValue: _selected,
                        onChanged: _busy
                            ? null
                            : (value) => setState(() {
                                  _selected = value;
                                  _directory = null;
                                  _check = null;
                                  _modelReport = null;
                                })),
                  if (_selected != null) ...[
                    OutlinedButton(
                        onPressed: _busy
                            ? null
                            : () => _perform(() => _run(selected: true)),
                        child: const Text('Проверить и исправить проект')),
                    TextButton(
                        onPressed: _busy ? null : () => _perform(_export),
                        child: const Text('Сохранить исходники в папку')),
                  ],
                  if (_windows) ...[
                    const SizedBox(height: 24),
                    SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Принимать проверки с телефона'),
                        subtitle: Text(_remote.enabled
                            ? _remote.status
                            : 'Выбери папку и оставь эту страницу открытой. Каждый новый проект требует разрешения.'),
                        value: _remote.enabled,
                        onChanged:
                            _busy ? null : (_) => _perform(_toggleRemote)),
                  ],
                ]))),
      );
}
