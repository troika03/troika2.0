import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:permission_handler/permission_handler.dart';
import '../config/troika_config.dart';
import '../services/troika_api_service.dart';
import '../services/reminder_delivery_service.dart';
import '../widgets/troika_page.dart';
import '../theme/troika_theme.dart';
import 'memory_screen.dart';

class AssistantHubScreen extends StatefulWidget {
  const AssistantHubScreen({super.key, this.reminderDelivery});
  final ReminderDeliveryService? reminderDelivery;
  @override
  State<AssistantHubScreen> createState() => _AssistantHubScreenState();
}

class _AssistantHubScreenState extends State<AssistantHubScreen> {
  static const _platform = MethodChannel('com.troika.hermes/background');
  final TroikaApiService _api = TroikaApiService();
  late final ReminderDeliveryService _delivery =
      widget.reminderDelivery ?? ReminderDeliveryService.instance;
  List<TroikaProject> _projects = const [];
  List<TroikaTask> _tasks = const [];
  List<TroikaInboxMessage> _messages = const [];
  TroikaNotificationPreferences? _preferences;
  bool _loading = true;
  bool _screenReady = false;
  bool _screenBusy = false;
  int _sectionFilter = 0;
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
    final result = await _textDialog('Новый проект', const [
      'Название',
      'Кратко о проекте',
    ]);
    if (!mounted || result == null || result[0].trim().isEmpty) return;
    try {
      await _api.createAssistantProject(
        result[0].trim(),
        summary: result[1].trim(),
      );
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
    final result = await _textDialog('Добавить задачу', const [
      'Задача',
      'Подробности',
    ]);
    if (!mounted || result == null || result[0].trim().isEmpty) return;
    final dueAt = await _pickOptionalDueAt();
    if (!mounted) return;
    try {
      await _api.createAssistantTask(
        title: result[0].trim(),
        details: result[1].trim(),
        dueAt: dueAt,
        projectId: project.id,
      );
      await _delivery.sync(refresh: true);
      await _load();
    } catch (error) {
      _showError(error.toString());
    }
  }

  Future<String?> _pickOptionalDueAt() async {
    final choose = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: TroikaPalette.of(context).surface,
        title: Text(
          'Добавить срок?',
          style: TextStyle(color: TroikaPalette.of(context).text),
        ),
        content: Text(
          'Со сроком Тройка сможет напомнить о задаче.',
          style: TextStyle(color: TroikaPalette.of(context).textMuted),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Без срока'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Выбрать'),
          ),
        ],
      ),
    );
    if (choose != true || !mounted) return null;
    final now = DateTime.now();
    final date = await showDatePicker(
      context: context,
      initialDate: now,
      firstDate: DateTime(now.year, now.month, now.day),
      lastDate: DateTime(now.year + 10, 12, 31),
    );
    if (date == null || !mounted) return null;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay(hour: now.hour, minute: now.minute),
    );
    if (time == null) return null;
    return DateTime(
      date.year,
      date.month,
      date.day,
      time.hour,
      time.minute,
    ).toUtc().toIso8601String();
  }

  Future<List<String>?> _textDialog(String title, List<String> labels) async {
    final controllers = [for (final _ in labels) TextEditingController()];
    final route = DialogRoute<List<String>>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: TroikaPalette.of(context).surface,
        title: Text(
          title,
          style: TextStyle(color: TroikaPalette.of(context).text),
        ),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (var i = 0; i < labels.length; i++)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: TextField(
                    controller: controllers[i],
                    maxLines: i == 1 ? 3 : 1,
                    style: TextStyle(color: TroikaPalette.of(context).text),
                    decoration: InputDecoration(labelText: labels[i]),
                  ),
                ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, [
              for (final item in controllers) item.text,
            ]),
            child: const Text('Сохранить'),
          ),
        ],
      ),
    );
    final result = await Navigator.of(context, rootNavigator: true).push(route);
    // A popped route still builds while its reverse animation is running.
    await route.completed;
    for (final item in controllers) {
      item.dispose();
    }
    return result;
  }

  void _showError(String message) {
    if (mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(message)));
    }
  }

  Future<void> _savePreferences(TroikaNotificationPreferences next) async {
    setState(() => _preferences = next);
    try {
      await _api.setNotificationPreferences(next);
      if (Platform.isAndroid && next.remindersEnabled) {
        await Permission.notification.request();
      }
      await _delivery.sync(refresh: true);
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
        minute: parts.length > 1 ? int.tryParse(parts[1]) ?? 0 : 0,
      );
    }

    final start = await showTimePicker(
      context: context,
      initialTime: parse(prefs.quietStart),
    );
    if (start == null || !mounted) return;
    final end = await showTimePicker(
      context: context,
      initialTime: parse(prefs.quietEnd),
    );
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
    await _savePreferences(
      prefs.copyWith(
        quietHoursEnabled: true,
        timezone: timezone,
        quietStart: format(start),
        quietEnd: format(end),
      ),
    );
  }

  Future<void> _updateTaskStatus(TroikaTask task, String status) async {
    try {
      await _api.updateAssistantTaskStatus(task.id, status);
      await _delivery.sync(refresh: true);
      await _load();
    } catch (error) {
      _showError(error.toString());
    }
  }

  Future<void> _read(TroikaInboxMessage message) async {
    if (!message.isRead) {
      try {
        await _api.markAssistantMessageRead(message.id);
        await _delivery.sync(refresh: true);
      } catch (_) {}
      await _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    final prefs = _preferences;
    return TroikaPage(
      backgroundColor: TroikaPalette.of(context).bg,
      appBar: AppBar(
        title: const Text('Помощник'),
        actions: [
          IconButton(onPressed: _load, icon: const Icon(Icons.refresh)),
        ],
      ),
      body: _loading && _projects.isEmpty
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
                children: [
                  TroikaIntro(
                    icon: Icons.checklist_rounded,
                    title: _activeProject?.name ?? 'Освободи голову',
                    subtitle: _activeProject == null
                        ? 'Собери дела и напоминания в одном месте. Начни с проекта.'
                        : 'Задачи, сроки и заметки твоего проекта — всегда под рукой.',
                  ),
                  _Panel(
                    child: Row(
                      children: [
                        Expanded(
                          child: _SummaryValue(
                            label: 'Проекты',
                            value: '${_projects.length}',
                            icon: Icons.folder_outlined,
                          ),
                        ),
                        const SizedBox(width: 16),
                        Expanded(
                          child: _SummaryValue(
                            label: 'Задачи',
                            value: '${_tasks.length}',
                            icon: Icons.check_circle_outline,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      for (final (index, label) in [
                        (0, 'Обзор'),
                        (1, 'Проекты'),
                        (2, 'Задачи'),
                        (3, 'Напоминания'),
                      ])
                        ChoiceChip(
                          label: Text(label),
                          selected: _sectionFilter == index,
                          showCheckmark: false,
                          onSelected: (_) =>
                              setState(() => _sectionFilter = index),
                        ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  if (_error != null)
                    _Panel(
                      child: Text(
                        _error!,
                        style: const TextStyle(color: TroikaColors.error),
                      ),
                    ),
                  if (_sectionFilter == 0) ...[
                    _section('Память', null),
                    _Panel(
                      child: ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: Container(
                          width: 44,
                          height: 44,
                          decoration: BoxDecoration(
                            color: Theme.of(
                              context,
                            ).colorScheme.primary.withValues(alpha: 0.08),
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: Icon(
                            Icons.psychology_outlined,
                            color: Theme.of(context).colorScheme.primary,
                          ),
                        ),
                        title: Text(
                          'Что Тройка помнит',
                          style: TextStyle(
                            color: TroikaPalette.of(context).text,
                          ),
                        ),
                        subtitle: Text(
                          'Просматривай, исправляй и удаляй личный контекст.',
                          style: TextStyle(
                            color: TroikaPalette.of(context).textMuted,
                          ),
                        ),
                        trailing: Icon(
                          Icons.chevron_right,
                          color: TroikaPalette.of(context).textMuted,
                        ),
                        onTap: () => Navigator.push(
                          context,
                          MaterialPageRoute(
                            builder: (_) =>
                                const TroikaPageScope(child: MemoryScreen()),
                          ),
                        ),
                      ),
                    ),
                  ],
                  if (_sectionFilter == 0 || _sectionFilter == 3) ...[
                    _section(
                      'Входящие',
                      IconButton(
                        onPressed: _createTask,
                        icon: const Icon(Icons.add_task),
                      ),
                    ),
                    if (_messages.isEmpty)
                      _empty('Пока нет полезных напоминаний.'),
                    for (final message in _messages)
                      _MessageCard(
                        message: message,
                        onTap: () => _read(message),
                      ),
                  ],
                  if (_sectionFilter == 0 || _sectionFilter == 1) ...[
                    _section(
                      'Проекты',
                      IconButton(
                        onPressed: _createProject,
                        icon: const Icon(Icons.create_new_folder_outlined),
                      ),
                    ),
                    if (_projects.isEmpty)
                      _empty(
                        'Создай проект. Потом скажи: «запомни это в проект».',
                        action: _createProject,
                      ),
                    for (final project in _projects)
                      _ProjectCard(
                        project: project,
                        onTap: () => _activate(project),
                      ),
                  ],
                  if (_sectionFilter == 0 || _sectionFilter == 2) ...[
                    _section(
                      'Задачи',
                      IconButton(
                        onPressed: _createTask,
                        icon: const Icon(Icons.add),
                      ),
                    ),
                    if (_tasks.isEmpty)
                      _empty(
                        _activeProject == null
                            ? 'Выбери проект.'
                            : 'В активном проекте нет открытых задач.',
                      ),
                    for (final task in _tasks)
                      _TaskCard(
                        task: task,
                        onStatusChanged: (status) =>
                            _updateTaskStatus(task, status),
                      ),
                  ],
                  if (_sectionFilter == 0 || _sectionFilter == 3) ...[
                    _section('Правила сообщений', null),
                    _Panel(
                      child: Column(
                        children: [
                          SwitchListTile(
                            contentPadding: EdgeInsets.zero,
                            title: Text(
                              'Напоминания',
                              style: TextStyle(
                                color: TroikaPalette.of(context).text,
                              ),
                            ),
                            subtitle: Text(
                              'Просьбы напомнить и задачи со сроком',
                              style: TextStyle(
                                color: TroikaPalette.of(context).textMuted,
                              ),
                            ),
                            value: prefs?.remindersEnabled ?? false,
                            onChanged: (value) {
                              if (prefs != null) {
                                _savePreferences(
                                  prefs.copyWith(remindersEnabled: value),
                                );
                              }
                            },
                          ),
                          if (Platform.isAndroid)
                            ListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(
                                'Точные напоминания на телефоне',
                                style: TextStyle(
                                  color: TroikaPalette.of(context).text,
                                ),
                              ),
                              subtitle: Text(
                                'Разрешение Android для уведомления в нужную минуту',
                                style: TextStyle(
                                  color: TroikaPalette.of(context).textMuted,
                                ),
                              ),
                              onTap: () async {
                                await Permission.notification.request();
                                await _delivery.requestExactAlarms();
                                await _delivery.sync(refresh: true);
                              },
                            ),
                          SwitchListTile(
                            contentPadding: EdgeInsets.zero,
                            title: Text(
                              'Полезные follow-up',
                              style: TextStyle(
                                color: TroikaPalette.of(context).text,
                              ),
                            ),
                            subtitle: Text(
                              'Сроки, блокировки, решения и прогресс',
                              style: TextStyle(
                                color: TroikaPalette.of(context).textMuted,
                              ),
                            ),
                            value: prefs?.proactiveEnabled ?? false,
                            onChanged: (value) {
                              if (prefs != null) {
                                _savePreferences(
                                  prefs.copyWith(proactiveEnabled: value),
                                );
                              }
                            },
                          ),
                          SwitchListTile(
                            contentPadding: EdgeInsets.zero,
                            title: Text(
                              'Тихие часы',
                              style: TextStyle(
                                color: TroikaPalette.of(context).text,
                              ),
                            ),
                            subtitle: Text(
                              '${prefs?.quietStart ?? '22:00'} — '
                              '${prefs?.quietEnd ?? '08:00'} '
                              '(${prefs?.timezone ?? 'UTC'})',
                              style: TextStyle(
                                color: TroikaPalette.of(context).textMuted,
                              ),
                            ),
                            secondary: IconButton(
                              tooltip: 'Настроить время',
                              onPressed: _configureQuietHours,
                              icon: Icon(
                                Icons.schedule,
                                color: Theme.of(context).colorScheme.primary,
                              ),
                            ),
                            value: prefs?.quietHoursEnabled ?? false,
                            onChanged: (value) {
                              if (prefs != null) {
                                _savePreferences(
                                  TroikaNotificationPreferences(
                                    remindersEnabled: prefs.remindersEnabled,
                                    proactiveEnabled: prefs.proactiveEnabled,
                                    quietHoursEnabled: value,
                                    timezone: prefs.timezone,
                                    quietStart: prefs.quietStart,
                                    quietEnd: prefs.quietEnd,
                                  ),
                                );
                              }
                            },
                          ),
                        ],
                      ),
                    ),
                  ],
                  if (TroikaConfig.screenSnapshotBetaEnabled &&
                      (_sectionFilter == 0 || _sectionFilter == 3)) ...[
                    _section('Показ экрана', null),
                    _Panel(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Icon(
                                _screenReady
                                    ? Icons.visibility
                                    : Icons.visibility_off_outlined,
                                color: _screenReady
                                    ? Theme.of(context).colorScheme.primary
                                    : TroikaPalette.of(context).textMuted,
                              ),
                              const SizedBox(width: 10),
                              Expanded(
                                child: Text(
                                  _screenReady
                                      ? 'Разрешён один снимок'
                                      : 'Снимок запрещён',
                                  style: TextStyle(
                                    color: TroikaPalette.of(context).text,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 8),
                          Text(
                            'Android покажет системное окно. Разрешение действует 2 минуты и исчезает после одного кадра. Перед отправкой сервер запросит отдельное подтверждение.',
                            style: TextStyle(
                              color: TroikaPalette.of(context).textMuted,
                            ),
                          ),
                          const SizedBox(height: 12),
                          Row(
                            children: [
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
                                            strokeWidth: 2,
                                          ),
                                        )
                                      : const Icon(Icons.screenshot_monitor),
                                  label: const Text('Разрешить снимок'),
                                ),
                              ),
                              if (_screenReady) ...[
                                const SizedBox(width: 10),
                                OutlinedButton(
                                  onPressed: _stopScreenConsent,
                                  child: const Text('Остановить'),
                                ),
                              ],
                            ],
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
              ),
            ),
    );
  }

  Widget _section(String title, Widget? action) => Padding(
    padding: const EdgeInsets.only(top: 18, bottom: 6),
    child: Row(
      children: [
        Text(
          title,
          style: TextStyle(
            color: TroikaPalette.of(context).text,
            fontSize: 18,
            fontWeight: FontWeight.w600,
          ),
        ),
        const Spacer(),
        if (action != null) action,
      ],
    ),
  );
  Widget _empty(String text, {VoidCallback? action}) => _Panel(
    child: Row(
      children: [
        Expanded(
          child: Text(
            text,
            style: TextStyle(color: TroikaPalette.of(context).textMuted),
          ),
        ),
        if (action != null)
          TextButton(onPressed: action, child: const Text('Создать')),
      ],
    ),
  );
}

class _Panel extends StatelessWidget {
  final Widget child;
  const _Panel({required this.child});
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(14),
    margin: const EdgeInsets.only(bottom: 8),
    decoration: BoxDecoration(
      color: TroikaPalette.of(context).surface,
      borderRadius: BorderRadius.circular(14),
    ),
    child: Material(type: MaterialType.transparency, child: child),
  );
}

class _SummaryValue extends StatelessWidget {
  final String label, value;
  final IconData icon;
  const _SummaryValue({
    required this.label,
    required this.value,
    required this.icon,
  });
  @override
  Widget build(BuildContext context) {
    final p = TroikaPalette.of(context);
    return Row(
      children: [
        TroikaIcon(icon: icon, size: 40),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                value,
                style: TextStyle(
                  color: p.text,
                  fontSize: 22,
                  fontWeight: FontWeight.w600,
                ),
              ),
              Text(label, style: TextStyle(color: p.textMuted)),
            ],
          ),
        ),
      ],
    );
  }
}

class _MessageCard extends StatelessWidget {
  final TroikaInboxMessage message;
  final VoidCallback onTap;
  const _MessageCard({required this.message, required this.onTap});
  @override
  Widget build(BuildContext context) => InkWell(
    onTap: onTap,
    child: _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                message.requiresApproval
                    ? Icons.pending_actions
                    : Icons.notifications_none,
                color: Theme.of(context).colorScheme.primary,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  message.title,
                  style: TextStyle(
                    color: TroikaPalette.of(context).text,
                    fontWeight: message.isRead
                        ? FontWeight.normal
                        : FontWeight.w700,
                  ),
                ),
              ),
              Text(
                message.category,
                style: TextStyle(
                  color: TroikaPalette.of(context).textMuted,
                  fontSize: 11,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            message.body,
            style: TextStyle(color: TroikaPalette.of(context).text),
          ),
          const SizedBox(height: 6),
          Text(
            'Почему: ${message.reason}',
            style: TextStyle(
              color: TroikaPalette.of(context).textMuted,
              fontSize: 12,
            ),
          ),
        ],
      ),
    ),
  );
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
        project.isActive ? Icons.radio_button_checked : Icons.folder_outlined,
        color: project.isActive
            ? Theme.of(context).colorScheme.primary
            : TroikaPalette.of(context).textMuted,
      ),
      title: Text(
        project.name,
        style: TextStyle(color: TroikaPalette.of(context).text),
      ),
      subtitle: Text(
        project.summary.isEmpty
            ? 'Нажми, чтобы сделать активным'
            : project.summary,
        style: TextStyle(color: TroikaPalette.of(context).textMuted),
      ),
    ),
  );
}

class _TaskCard extends StatelessWidget {
  final TroikaTask task;
  final ValueChanged<String> onStatusChanged;
  const _TaskCard({required this.task, required this.onStatusChanged});
  @override
  Widget build(BuildContext context) => _Panel(
    child: Row(
      children: [
        Icon(
          task.status == 'blocked' ? Icons.block : Icons.radio_button_unchecked,
          color: task.status == 'blocked'
              ? TroikaColors.error
              : TroikaPalette.of(context).textMuted,
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                task.title,
                style: TextStyle(color: TroikaPalette.of(context).text),
              ),
              if (task.details.isNotEmpty)
                Text(
                  task.details,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: TroikaPalette.of(context).textMuted,
                    fontSize: 12,
                  ),
                ),
              if (task.dueAt.isNotEmpty)
                Text(
                  'Срок: ${task.dueAt}',
                  style: TextStyle(
                    color: Theme.of(context).colorScheme.primary,
                    fontSize: 12,
                  ),
                ),
            ],
          ),
        ),
        if (task.requiresApproval)
          Icon(
            Icons.verified_user_outlined,
            color: Theme.of(context).colorScheme.primary,
            size: 18,
          ),
        PopupMenuButton<String>(
          tooltip: 'Изменить статус',
          icon: Icon(
            Icons.more_vert,
            color: TroikaPalette.of(context).textMuted,
          ),
          onSelected: onStatusChanged,
          itemBuilder: (context) => const [
            PopupMenuItem(value: 'in_progress', child: Text('В работе')),
            PopupMenuItem(value: 'blocked', child: Text('Заблокирована')),
            PopupMenuItem(value: 'completed', child: Text('Завершена')),
            PopupMenuItem(value: 'cancelled', child: Text('Отменена')),
          ],
        ),
      ],
    ),
  );
}
