import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../services/hermes_api_service.dart';
import '../theme/troika_theme.dart';

class AssistantHubScreen extends StatefulWidget {
  const AssistantHubScreen({super.key});
  @override
  State<AssistantHubScreen> createState() => _AssistantHubScreenState();
}

class _AssistantHubScreenState extends State<AssistantHubScreen> {
  static const _platform = MethodChannel('com.troika.hermes/background');
  final HermesApiService _api = HermesApiService();
  List<TroikaProject> _projects = const [];
  List<TroikaTask> _tasks = const [];
  List<TroikaInboxMessage> _messages = const [];
  TroikaNotificationPreferences? _preferences;
  bool _loading = true;
  bool _screenReady = false;
  bool _screenBusy = false;
  String? _error;

  TroikaProject? get _activeProject {
    for (final item in _projects) {
      if (item.isActive) return item;
    }
    return _projects.isEmpty ? null : _projects.first;
  }

  @override
  void initState() {
    super.initState();
    _load();
    _refreshScreenState();
  }

  Future<void> _refreshScreenState() async {
    try {
      final ready =
          await _platform.invokeMethod<bool>('isScreenSnapshotReady') ?? false;
      if (mounted) setState(() => _screenReady = ready);
    } catch (_) {
      if (mounted) setState(() => _screenReady = false);
    }
  }

  Future<void> _requestScreenConsent() async {
    if (_screenBusy) return;
    setState(() => _screenBusy = true);
    try {
      final granted =
          await _platform.invokeMethod<bool>('requestScreenSnapshotConsent') ??
              false;
      await _refreshScreenState();
      if (mounted && !granted) {
        _showError('Показ экрана не разрешён.');
      }
    } catch (error) {
      _showError(error.toString());
    } finally {
      if (mounted) setState(() => _screenBusy = false);
    }
  }

  Future<void> _stopScreenConsent() async {
    try {
      await _platform.invokeMethod<void>('stopScreenSnapshot');
    } finally {
      await _refreshScreenState();
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final projects = await _api.listAssistantProjects();
      TroikaProject? active;
      for (final item in projects) {
        if (item.isActive) {
          active = item;
          break;
        }
      }
      final results = await Future.wait<Object>([
        _api.listAssistantInbox(),
        _api.listAssistantTasks(projectId: active?.id),
        _api.getNotificationPreferences(),
      ]);
      if (!mounted) return;
      setState(() {
        _projects = projects;
        _messages = results[0] as List<TroikaInboxMessage>;
        _tasks = results[1] as List<TroikaTask>;
        _preferences = results[2] as TroikaNotificationPreferences;
        _loading = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = error.toString();
      });
    }
  }

  Future<void> _activate(TroikaProject project) async {
    try {
      await _api.activateAssistantProject(project.id);
      await _load();
    } catch (error) {
      _showError(error.toString());
    }
  }

  Future<void> _createProject() async {
    final result = await _textDialog(
        'Новый проект', const ['Название', 'Кратко о проекте']);
    if (result == null || result[0].trim().isEmpty) return;
    try {
      await _api.createAssistantProject(result[0].trim(),
          summary: result[1].trim());
      await _load();
    } catch (error) {
      _showError(error.toString());
    }
  }

  Future<void> _createTask() async {
    final project = _activeProject;
    if (project == null) {
      _showError('Сначала создай проект.');
      return;
    }
    final result =
        await _textDialog('Добавить задачу', const ['Задача', 'Подробности']);
    if (result == null || result[0].trim().isEmpty) return;
    final dueAt = await _pickOptionalDueAt();
    try {
      await _api.createAssistantTask(
          title: result[0].trim(),
          details: result[1].trim(),
          dueAt: dueAt,
          projectId: project.id);
      await _load();
    } catch (error) {
      _showError(error.toString());
    }
  }

  Future<String?> _pickOptionalDueAt() async {
    final choose = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
              backgroundColor: TroikaColors.surface,
              title: const Text('Добавить срок?',
                  style: TextStyle(color: TroikaColors.text)),
              content: const Text('Со сроком Тройка сможет напомнить о задаче.',
                  style: TextStyle(color: TroikaColors.textMuted)),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: const Text('Без срока')),
                FilledButton(
                    onPressed: () => Navigator.pop(context, true),
                    child: const Text('Выбрать')),
              ],
            ));
    if (choose != true || !mounted) return null;
    final now = DateTime.now();
    final date = await showDatePicker(
        context: context,
        initialDate: now,
        firstDate: DateTime(now.year, now.month, now.day),
        lastDate: DateTime(now.year + 10, 12, 31));
    if (date == null || !mounted) return null;
    final time = await showTimePicker(
        context: context,
        initialTime: TimeOfDay(hour: now.hour, minute: now.minute));
    if (time == null) return null;
    return DateTime(date.year, date.month, date.day, time.hour, time.minute)
        .toUtc()
        .toIso8601String();
  }

  Future<List<String>?> _textDialog(String title, List<String> labels) async {
    final controllers = [for (final _ in labels) TextEditingController()];
    final result = await showDialog<List<String>>(
        context: context,
        builder: (context) => AlertDialog(
              backgroundColor: TroikaColors.surface,
              title:
                  Text(title, style: const TextStyle(color: TroikaColors.text)),
              content: SingleChildScrollView(
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                for (var i = 0; i < labels.length; i++)
                  Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: TextField(
                          controller: controllers[i],
                          maxLines: i == 1 ? 3 : 1,
                          style: const TextStyle(color: TroikaColors.text),
                          decoration: InputDecoration(labelText: labels[i])))
              ])),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('Отмена')),
                FilledButton(
                    onPressed: () => Navigator.pop(
                        context, [for (final item in controllers) item.text]),
                    child: const Text('Сохранить'))
              ],
            ));
    for (final item in controllers) {
      item.dispose();
    }
    return result;
  }

  void _showError(String message) {
    if (mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(message)));
    }
  }

  Future<void> _savePreferences(TroikaNotificationPreferences next) async {
    setState(() => _preferences = next);
    try {
      await _api.setNotificationPreferences(next);
    } catch (error) {
      _showError(error.toString());
      await _load();
    }
  }

  Future<void> _configureQuietHours() async {
    final prefs = _preferences;
    if (prefs == null) return;
    TimeOfDay parse(String value) {
      final parts = value.split(':');
      return TimeOfDay(
          hour: int.tryParse(parts.first) ?? 22,
          minute: parts.length > 1 ? int.tryParse(parts[1]) ?? 0 : 0);
    }

    final start = await showTimePicker(
        context: context, initialTime: parse(prefs.quietStart));
    if (start == null || !mounted) return;
    final end = await showTimePicker(
        context: context, initialTime: parse(prefs.quietEnd));
    if (end == null) return;
    String timezone = prefs.timezone;
    try {
      final detected = await _platform.invokeMethod<String>('getTimeZoneId');
      if (detected == 'UTC' || (detected?.contains('/') ?? false)) {
        timezone = detected!;
      }
    } catch (_) {}
    String format(TimeOfDay value) =>
        '${value.hour.toString().padLeft(2, '0')}:'
        '${value.minute.toString().padLeft(2, '0')}';
    await _savePreferences(prefs.copyWith(
        quietHoursEnabled: true,
        timezone: timezone,
        quietStart: format(start),
        quietEnd: format(end)));
  }

  Future<void> _updateTaskStatus(TroikaTask task, String status) async {
    try {
      await _api.updateAssistantTaskStatus(task.id, status);
      await _load();
    } catch (error) {
      _showError(error.toString());
    }
  }

  Future<void> _read(TroikaInboxMessage message) async {
    if (!message.isRead) {
      try {
        await _api.markAssistantMessageRead(message.id);
      } catch (_) {}
      await _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    final prefs = _preferences;
    return Scaffold(
      backgroundColor: TroikaColors.bg,
      appBar: AppBar(title: const Text('Помощник'), actions: [
        IconButton(onPressed: _load, icon: const Icon(Icons.refresh))
      ]),
      body: _loading && _projects.isEmpty
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
                  children: [
                    if (_error != null)
                      _Panel(
                          child: Text(_error!,
                              style:
                                  const TextStyle(color: TroikaColors.error))),
                    _section(
                        'Входящие',
                        IconButton(
                            onPressed: _createTask,
                            icon: const Icon(Icons.add_task))),
                    if (_messages.isEmpty)
                      _empty('Пока нет полезных напоминаний.'),
                    for (final message in _messages)
                      _MessageCard(
                          message: message, onTap: () => _read(message)),
                    _section(
                        'Проекты',
                        IconButton(
                            onPressed: _createProject,
                            icon:
                                const Icon(Icons.create_new_folder_outlined))),
                    if (_projects.isEmpty)
                      _empty(
                          'Создай проект. Потом скажи: «запомни это в проект».',
                          action: _createProject),
                    for (final project in _projects)
                      _ProjectCard(
                          project: project, onTap: () => _activate(project)),
                    _section(
                        'Задачи',
                        IconButton(
                            onPressed: _createTask,
                            icon: const Icon(Icons.add))),
                    if (_tasks.isEmpty)
                      _empty(_activeProject == null
                          ? 'Выбери проект.'
                          : 'В активном проекте нет открытых задач.'),
                    for (final task in _tasks)
                      _TaskCard(
                          task: task,
                          onStatusChanged: (status) =>
                              _updateTaskStatus(task, status)),
                    _section('Правила сообщений', null),
                    _Panel(
                        child: Column(children: [
                      SwitchListTile(
                          contentPadding: EdgeInsets.zero,
                          title: const Text('Напоминания',
                              style: TextStyle(color: TroikaColors.text)),
                          subtitle: const Text('Только задачи со сроком',
                              style: TextStyle(color: TroikaColors.textMuted)),
                          value: prefs?.remindersEnabled ?? false,
                          onChanged: (value) {
                            if (prefs != null) {
                              _savePreferences(
                                  prefs.copyWith(remindersEnabled: value));
                            }
                          }),
                      SwitchListTile(
                          contentPadding: EdgeInsets.zero,
                          title: const Text('Полезные follow-up',
                              style: TextStyle(color: TroikaColors.text)),
                          subtitle: const Text(
                              'Сроки, блокировки, решения и прогресс',
                              style: TextStyle(color: TroikaColors.textMuted)),
                          value: prefs?.proactiveEnabled ?? false,
                          onChanged: (value) {
                            if (prefs != null) {
                              _savePreferences(
                                  prefs.copyWith(proactiveEnabled: value));
                            }
                          }),
                      SwitchListTile(
                          contentPadding: EdgeInsets.zero,
                          title: const Text('Тихие часы',
                              style: TextStyle(color: TroikaColors.text)),
                          subtitle: Text(
                              '${prefs?.quietStart ?? '22:00'} — '
                              '${prefs?.quietEnd ?? '08:00'} '
                              '(${prefs?.timezone ?? 'UTC'})',
                              style: const TextStyle(
                                  color: TroikaColors.textMuted)),
                          secondary: IconButton(
                              tooltip: 'Настроить время',
                              onPressed: _configureQuietHours,
                              icon: const Icon(Icons.schedule,
                                  color: TroikaColors.brand)),
                          value: prefs?.quietHoursEnabled ?? false,
                          onChanged: (value) {
                            if (prefs != null) {
                              _savePreferences(TroikaNotificationPreferences(
                                  remindersEnabled: prefs.remindersEnabled,
                                  proactiveEnabled: prefs.proactiveEnabled,
                                  quietHoursEnabled: value,
                                  timezone: prefs.timezone,
                                  quietStart: prefs.quietStart,
                                  quietEnd: prefs.quietEnd));
                            }
                          }),
                    ])),
                    _section('Показ экрана', null),
                    _Panel(
                        child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                          Row(children: [
                            Icon(
                                _screenReady
                                    ? Icons.visibility
                                    : Icons.visibility_off_outlined,
                                color: _screenReady
                                    ? TroikaColors.brand
                                    : TroikaColors.textMuted),
                            const SizedBox(width: 10),
                            Expanded(
                                child: Text(
                                    _screenReady
                                        ? 'Разрешён один снимок'
                                        : 'Снимок запрещён',
                                    style: const TextStyle(
                                        color: TroikaColors.text,
                                        fontWeight: FontWeight.w600))),
                          ]),
                          const SizedBox(height: 8),
                          const Text(
                              'Android покажет системное окно. Разрешение действует 2 минуты и исчезает после одного кадра. Перед отправкой сервер запросит отдельное подтверждение.',
                              style: TextStyle(color: TroikaColors.textMuted)),
                          const SizedBox(height: 12),
                          Row(children: [
                            Expanded(
                                child: FilledButton.icon(
                                    onPressed: _screenReady || _screenBusy
                                        ? null
                                        : _requestScreenConsent,
                                    icon: _screenBusy
                                        ? const SizedBox(
                                            width: 16,
                                            height: 16,
                                            child: CircularProgressIndicator(
                                                strokeWidth: 2))
                                        : const Icon(Icons.screenshot_monitor),
                                    label: const Text('Разрешить снимок'))),
                            if (_screenReady) ...[
                              const SizedBox(width: 10),
                              OutlinedButton(
                                  onPressed: _stopScreenConsent,
                                  child: const Text('Остановить')),
                            ]
                          ])
                        ])),
                  ])),
    );
  }

  Widget _section(String title, Widget? action) => Padding(
      padding: const EdgeInsets.only(top: 18, bottom: 6),
      child: Row(children: [
        Text(title,
            style: const TextStyle(
                color: TroikaColors.text,
                fontSize: 18,
                fontWeight: FontWeight.w600)),
        const Spacer(),
        if (action != null) action
      ]));
  Widget _empty(String text, {VoidCallback? action}) => _Panel(
          child: Row(children: [
        Expanded(
            child: Text(text,
                style: const TextStyle(color: TroikaColors.textMuted))),
        if (action != null)
          TextButton(onPressed: action, child: const Text('Создать'))
      ]));
}

class _Panel extends StatelessWidget {
  final Widget child;
  const _Panel({required this.child});
  @override
  Widget build(BuildContext context) => Container(
      padding: const EdgeInsets.all(14),
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
          color: TroikaColors.surface, borderRadius: BorderRadius.circular(14)),
      child: child);
}

class _MessageCard extends StatelessWidget {
  final TroikaInboxMessage message;
  final VoidCallback onTap;
  const _MessageCard({required this.message, required this.onTap});
  @override
  Widget build(BuildContext context) => InkWell(
      onTap: onTap,
      child: _Panel(
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(
              message.requiresApproval
                  ? Icons.pending_actions
                  : Icons.notifications_none,
              color: TroikaColors.brand),
          const SizedBox(width: 8),
          Expanded(
              child: Text(message.title,
                  style: TextStyle(
                      color: TroikaColors.text,
                      fontWeight: message.isRead
                          ? FontWeight.normal
                          : FontWeight.w700))),
          Text(message.category,
              style:
                  const TextStyle(color: TroikaColors.textMuted, fontSize: 11))
        ]),
        const SizedBox(height: 8),
        Text(message.body, style: const TextStyle(color: TroikaColors.text)),
        const SizedBox(height: 6),
        Text('Почему: ${message.reason}',
            style: const TextStyle(color: TroikaColors.textMuted, fontSize: 12))
      ])));
}

class _ProjectCard extends StatelessWidget {
  final TroikaProject project;
  final VoidCallback onTap;
  const _ProjectCard({required this.project, required this.onTap});
  @override
  Widget build(BuildContext context) => _Panel(
      child: ListTile(
          onTap: onTap,
          contentPadding: EdgeInsets.zero,
          leading: Icon(
              project.isActive
                  ? Icons.radio_button_checked
                  : Icons.folder_outlined,
              color: project.isActive
                  ? TroikaColors.brand
                  : TroikaColors.textMuted),
          title: Text(project.name,
              style: const TextStyle(color: TroikaColors.text)),
          subtitle: Text(
              project.summary.isEmpty
                  ? 'Нажми, чтобы сделать активным'
                  : project.summary,
              style: const TextStyle(color: TroikaColors.textMuted))));
}

class _TaskCard extends StatelessWidget {
  final TroikaTask task;
  final ValueChanged<String> onStatusChanged;
  const _TaskCard({required this.task, required this.onStatusChanged});
  @override
  Widget build(BuildContext context) => _Panel(
          child: Row(children: [
        Icon(
            task.status == 'blocked'
                ? Icons.block
                : Icons.radio_button_unchecked,
            color: task.status == 'blocked'
                ? TroikaColors.error
                : TroikaColors.textMuted),
        const SizedBox(width: 10),
        Expanded(
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(task.title, style: const TextStyle(color: TroikaColors.text)),
          if (task.details.isNotEmpty)
            Text(task.details,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                    color: TroikaColors.textMuted, fontSize: 12)),
          if (task.dueAt.isNotEmpty)
            Text('Срок: ${task.dueAt}',
                style: const TextStyle(color: TroikaColors.brand, fontSize: 12))
        ])),
        if (task.requiresApproval)
          const Icon(Icons.verified_user_outlined,
              color: TroikaColors.brand, size: 18),
        PopupMenuButton<String>(
            tooltip: 'Изменить статус',
            icon: const Icon(Icons.more_vert, color: TroikaColors.textMuted),
            onSelected: onStatusChanged,
            itemBuilder: (context) => const [
                  PopupMenuItem(value: 'in_progress', child: Text('В работе')),
                  PopupMenuItem(value: 'blocked', child: Text('Заблокирована')),
                  PopupMenuItem(value: 'completed', child: Text('Завершена')),
                  PopupMenuItem(value: 'cancelled', child: Text('Отменена')),
                ])
      ]));
}
