import 'dart:async';

import 'package:flutter/material.dart';

import '../services/development_autopilot_service.dart';
import '../services/files_service.dart';

class DevelopmentAutopilotPanel extends StatelessWidget {
  final DevelopmentAutopilotService controller;
  final void Function(TroikaFile file) onOpen;
  const DevelopmentAutopilotPanel(
      {super.key, required this.controller, required this.onOpen});

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
      animation: controller,
      builder: (context, _) => Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Голосовые отчёты по проектам'),
                  subtitle: const Text(
                      'Важные этапы и готовый результат. Во время разговора Тройка подождёт.'),
                  value: controller.voiceReports,
                  onChanged: (value) =>
                      unawaited(controller.setVoiceReports(value))),
              if (!controller.isPro)
                const Padding(
                    padding: EdgeInsets.symmetric(vertical: 8),
                    child: Text('Автопилот разработки доступен только в Pro.')),
              SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Работать при закрытом экране'),
                  subtitle: const Text(
                      'Сохранять проекты и сообщать о результате через системное уведомление. Принудительная остановка приложения выключает фон.'),
                  value: controller.backgroundReports,
                  onChanged: (value) =>
                      unawaited(controller.setBackgroundReports(value))),
              if (controller.error.isNotEmpty)
                Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Text(controller.error)),
              for (final project in controller.projects)
                _project(context, project),
            ],
          ));

  Widget _project(BuildContext context, Map<String, dynamic> project) {
    final id = project['run_id'].toString();
    final terminal = [
      'completed',
      'failed',
      'cancelled',
      'paused',
      'waiting_budget',
      'interrupted'
    ].contains(project['status']);
    final workers = (project['workers'] as List? ?? []).whereType<Map>();
    final running = workers.where((w) => w['status'] == 'running').length;
    final reports = (project['reports'] as List? ?? []).whereType<Map>();
    final result = controller.results[id];
    return Card(
        margin: const EdgeInsets.symmetric(vertical: 8),
        child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(project['title']?.toString() ?? 'Проект',
                      style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 8),
                  Text(projectStage(project['stage']?.toString() ?? 'queued')),
                  if (!terminal) ...[
                    const SizedBox(height: 12),
                    const LinearProgressIndicator(),
                    const SizedBox(height: 8),
                    Text(running == 0
                        ? 'Можно вернуться к разговору'
                        : 'Работают специалисты: $running'),
                    TextButton(
                        onPressed: () async {
                          try {
                            await controller.stopProject(id);
                          } catch (error) {
                            if (context.mounted) {
                              ScaffoldMessenger.of(context).showSnackBar(
                                  SnackBar(content: Text(error.toString())));
                            }
                          }
                        },
                        child: const Text('Остановить проект')),
                    if (project['project_id'] != null &&
                        project['status'] != 'pausing')
                      Wrap(spacing: 12, children: [
                        TextButton(
                            onPressed: () => _perform(context,
                                () => controller.pauseProject(project)),
                            child: const Text('Пауза')),
                        TextButton(
                            onPressed: project['local_checkpoint'] == true
                                ? () => _continueDialog(context, project,
                                    active: true)
                                : null,
                            child: const Text('Уточнить задачу')),
                      ]),
                  ],
                  if (terminal && project['local_checkpoint'] == true)
                    FilledButton.tonal(
                        onPressed: () => _continueDialog(context, project),
                        child: Text(project['status'] == 'completed'
                            ? 'Изменить проект'
                            : 'Продолжить')),
                  if (project['checkpoint_error'] != null)
                    Text(project['checkpoint_error'].toString()),
                  if (project['error'] is Map)
                    Text(project['error']['message']?.toString() ?? 'Ошибка'),
                  if (project['delivery_error'] != null)
                    Text(project['delivery_error'].toString()),
                  if (result != null)
                    FilledButton.tonal(
                        onPressed: () => onOpen(result),
                        child: const Text('Показать результат')),
                  if (reports.isNotEmpty)
                    ExpansionTile(
                        tilePadding: EdgeInsets.zero,
                        title: const Text('Отчёты Тройки'),
                        children: [
                          for (final report in reports)
                            Padding(
                                padding: const EdgeInsets.only(bottom: 12),
                                child: Align(
                                    alignment: Alignment.centerLeft,
                                    child: Text(report['text'].toString())))
                        ]),
                ])));
  }

  Future<void> _perform(
      BuildContext context, Future<void> Function() action) async {
    try {
      await action();
    } catch (error) {
      if (context.mounted)
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(error.toString())));
    }
  }

  Future<void> _continueDialog(
      BuildContext context, Map<String, dynamic> project,
      {bool active = false}) async {
    final instruction = TextEditingController();
    var budget = 250000;
    final accepted = await showDialog<bool>(
        context: context,
        builder: (dialog) => StatefulBuilder(
            builder: (dialog, setState) => AlertDialog(
                  title: Text(active ? 'Уточнить задачу' : 'Продолжить проект'),
                  content: SingleChildScrollView(
                      child: Column(mainAxisSize: MainAxisSize.min, children: [
                    TextField(
                        controller: instruction,
                        minLines: 3,
                        maxLines: 5,
                        maxLength: 8000,
                        decoration: const InputDecoration(
                            labelText: 'Что изменить',
                            hintText: 'Можно оставить пустым для продолжения')),
                    const SizedBox(height: 16),
                    DropdownButtonFormField<int>(
                        initialValue: budget,
                        decoration: const InputDecoration(
                            labelText: 'Дополнительный предел AI-токенов'),
                        items: const [
                          DropdownMenuItem(value: 50000, child: Text('50 000')),
                          DropdownMenuItem(
                              value: 100000, child: Text('100 000')),
                          DropdownMenuItem(
                              value: 250000, child: Text('250 000'))
                        ],
                        onChanged: (value) =>
                            setState(() => budget = value ?? 250000)),
                    const SizedBox(height: 12),
                    const Text(
                        'Спишется фактический расход из месячного остатка. Уже готовые файлы сохранятся.'),
                  ])),
                  actions: [
                    TextButton(
                        onPressed: () => Navigator.pop(dialog, false),
                        child: const Text('Отмена')),
                    FilledButton(
                        onPressed: () => Navigator.pop(dialog, true),
                        child: Text(
                            active ? 'Уточнить и продолжить' : 'Продолжить'))
                  ],
                )));
    final text = instruction.text.trim();
    instruction.dispose();
    if (accepted != true || !context.mounted) return;
    await _perform(
        context,
        () => active
            ? controller.clarifyProject(project, text, budget)
            : controller.resumeProject(project,
                instruction: text, budgetTokens: budget));
  }
}
