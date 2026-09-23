import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:troika_assistant/services/local_document_service.dart';

void main() {
  test('builds a DOCX archive with document content', () {
    final bytes = LocalDocumentService.buildDocumentBytes(
      'Тест',
      'Первая строка\nВторая строка',
    );

    expect(bytes.take(4), [0x50, 0x4b, 0x03, 0x04]);
    expect(_contains(bytes, 'word/document.xml'), isTrue);
    expect(_contains(bytes, utf8.encode('Первая строка')), isTrue);
  });

  test('builds a PPTX archive with every slide', () {
    final bytes = LocalDocumentService.buildPresentationBytes(
      'План',
      ['Первый\n- Пункт', 'Второй\n- Итог'],
    );

    expect(bytes.take(4), [0x50, 0x4b, 0x03, 0x04]);
    expect(_contains(bytes, 'ppt/slides/slide1.xml'), isTrue);
    expect(_contains(bytes, 'ppt/slides/slide2.xml'), isTrue);
    expect(_contains(bytes, utf8.encode('Итог')), isTrue);
  });
}

bool _contains(List<int> bytes, Object value) {
  final needle = value is String ? utf8.encode(value) : value as List<int>;
  for (var start = 0; start <= bytes.length - needle.length; start++) {
    var matches = true;
    for (var index = 0; index < needle.length; index++) {
      if (bytes[start + index] != needle[index]) {
        matches = false;
        break;
      }
    }
    if (matches) return true;
  }
  return false;
}
