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
    final terminal =
        ['completed', 'failed', 'cancelled'].contains(project['status']);
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
                  ],
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
}
