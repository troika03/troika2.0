import 'package:flutter_test/flutter_test.dart';
import 'package:troika_assistant/services/assistant_result.dart';

void main() {
  test('completed document tool becomes a file result', () {
    final result = AssistantResult.forTurn(
      response: 'Презентация готова и сохранена.',
      successfulTools: const ['troika_create_pptx'],
    );

    expect(result.kind, AssistantResultKind.file);
    expect(result.title, 'Файл создан');
    expect(result.summary, 'Презентация готова и сохранена.');
  });

  test('structured task result keeps its user-facing title and id', () {
    final result = AssistantResult.forTurn(
      response: 'Добавила задачу на завтра.',
      structuredKind: 'task',
      structuredTitle: 'Проверить релиз',
      resourceId: 'task_123',
    );

    expect(result.kind, AssistantResultKind.saved);
    expect(result.title, 'Проверить релиз');
    expect(result.resourceId, 'task_123');

    final restored = AssistantResult.fromJson(result.toJson());
    expect(restored.kind, AssistantResultKind.saved);
    expect(restored.title, 'Проверить релиз');
    expect(restored.resourceId, 'task_123');
  });

  test('assistant storage operation becomes a saved result', () {
    final result = AssistantResult.forTurn(
      response: 'Задача добавлена на завтра.',
      successfulTools: const ['troika_assistant'],
    );

    expect(result.kind, AssistantResultKind.saved);
    expect(result.title, 'Результат сохранён');
  });

  test('generic completed tool becomes action without internal tool name', () {
    final result = AssistantResult.forTurn(
      response: 'Будильник установлен на 7:30.',
      successfulTools: const ['phone_control_internal'],
    );

    expect(result.kind, AssistantResultKind.action);
    expect(result.title, 'Готово');
    expect(result.summary, isNot(contains('phone_control_internal')));
  });

  test('plain response stays secondary and is shortened', () {
    final result = AssistantResult.forTurn(response: 'а' * 200);

    expect(result.kind, AssistantResultKind.answer);
    expect(result.title, 'Ответ готов');
    expect(result.summary.length, 140);
    expect(result.summary, endsWith('…'));
  });
}
