import 'package:flutter_test/flutter_test.dart';
import 'package:hermes_assistant/services/hermes_api_service.dart';

void main() {
  test('parses owner memory returned by product API', () {
    final memory = TroikaMemory.fromJson({
      'id': 'mem_123',
      'kind': 'preference',
      'title': 'Формат ответов',
      'content': 'Коротко и по-русски.',
      'created_at': '2026-09-14T10:00:00Z',
      'updated_at': '2026-09-14T11:00:00Z',
    });

    expect(memory.id, 'mem_123');
    expect(memory.kind, 'preference');
    expect(memory.title, 'Формат ответов');
    expect(memory.content, 'Коротко и по-русски.');
    expect(memory.updatedAt, '2026-09-14T11:00:00Z');
  });
}
