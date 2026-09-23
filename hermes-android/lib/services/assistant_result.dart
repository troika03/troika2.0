import 'package:flutter/foundation.dart';

enum AssistantResultKind { answer, action, file, saved }

@immutable
class AssistantResult {
  final AssistantResultKind kind;
  final String title;
  final String summary;
  final String resourceId;

  const AssistantResult({
    required this.kind,
    required this.title,
    required this.summary,
    this.resourceId = '',
  });

  factory AssistantResult.fromJson(Map<String, dynamic> json) {
    final rawKind = (json['kind'] ?? '').toString();
    final kind = AssistantResultKind.values.firstWhere(
      (value) => value.name == rawKind,
      orElse: () => AssistantResultKind.answer,
    );
    return AssistantResult(
      kind: kind,
      title: (json['title'] ?? '').toString(),
      summary: (json['summary'] ?? '').toString(),
      resourceId: (json['resource_id'] ?? '').toString(),
    );
  }

  Map<String, dynamic> toJson() => {
        'kind': kind.name,
        'title': title,
        'summary': summary,
        'resource_id': resourceId,
      };

  factory AssistantResult.forTurn({
    required String response,
    Iterable<String> successfulTools = const <String>[],
    String structuredKind = '',
    String structuredTitle = '',
    String resourceId = '',
  }) {
    final tools =
        successfulTools.where((tool) => tool.trim().isNotEmpty).toSet();
    final summary = _shortSummary(response);

    if (structuredKind.isNotEmpty) {
      final kind = switch (structuredKind) {
        'file' => AssistantResultKind.file,
        'task' || 'reminder' || 'saved' => AssistantResultKind.saved,
        _ => AssistantResultKind.action,
      };
      final fallbackTitle = switch (structuredKind) {
        'file' => 'Файл создан',
        'task' => 'Задача сохранена',
        'reminder' => 'Напоминание сохранено',
        _ => 'Результат сохранён',
      };
      return AssistantResult(
        kind: kind,
        title: structuredTitle.trim().isEmpty
            ? fallbackTitle
            : structuredTitle.trim(),
        summary: summary.isEmpty ? fallbackTitle : summary,
        resourceId: resourceId,
      );
    }

    if (tools.any((tool) => tool.startsWith('troika_create_'))) {
      return AssistantResult(
        kind: AssistantResultKind.file,
        title: 'Файл создан',
        summary:
            summary.isEmpty ? 'Файл сохранён в личных файлах Тройки.' : summary,
        resourceId: resourceId,
      );
    }
    if (tools.contains('troika_assistant')) {
      return AssistantResult(
        kind: AssistantResultKind.saved,
        title: 'Результат сохранён',
        summary: summary.isEmpty ? 'Изменения сохранены.' : summary,
        resourceId: resourceId,
      );
    }
    if (tools.isNotEmpty) {
      return AssistantResult(
        kind: AssistantResultKind.action,
        title: 'Готово',
        summary: summary.isEmpty ? 'Действие выполнено.' : summary,
        resourceId: resourceId,
      );
    }
    return AssistantResult(
      kind: AssistantResultKind.answer,
      title: 'Ответ готов',
      summary: summary,
      resourceId: resourceId,
    );
  }

  static String _shortSummary(String value) {
    final compact = value.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (compact.length <= 140) return compact;
    return '${compact.substring(0, 139)}…';
  }
}
