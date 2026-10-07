import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:troika_assistant/services/web_sources.dart';
import 'package:troika_assistant/widgets/web_sources_view.dart';

void main() {
  test('search snippets never become read pages without an extract result', () {
    final trace = WebSourceTrace();
    trace.apply(WebSourceActivity.fromJson({
      'phase': 'found',
      'sources': [
        {'url': 'https://example.com/a', 'title': 'Example', 'status': 'found'}
      ],
    })!);
    trace.finish();
    expect(trace.sources.single.statusLabel, 'Найдено');
    trace.apply(WebSourceActivity('reading',
        [WebSource(Uri.parse('https://example.com/a'), 'Example', 'opening')]));
    trace.finish();
    expect(trace.sources.single.status, 'failed');
  });

  test('old server events and malformed URLs are ignored', () {
    expect(WebSourceActivity.fromJson(null), isNull);
    expect(
        WebSource.fromJson({'url': 'javascript:alert(1)', 'status': 'found'}),
        isNull);
    expect(
        WebSource.fromJson(
            {'url': 'https://user:secret@example.com', 'status': 'found'}),
        isNull);
  });

  test('new search does not downgrade a confirmed read page', () {
    final trace = WebSourceTrace();
    final uri = Uri.parse('https://example.com/a');
    trace.apply(WebSourceActivity('read', [WebSource(uri, 'Example', 'read')]));
    trace.apply(
        WebSourceActivity('found', [WebSource(uri, 'Example', 'found')]));
    expect(trace.sources.single.status, 'read');
  });

  testWidgets('source links and truthful status fit a narrow screen',
      (tester) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final trace = WebSourceTrace();
    trace.apply(WebSourceActivity('found', [
      WebSource(Uri.parse('https://example.com/a'),
          'Название источника с длинным заголовком', 'found'),
      WebSource(Uri.parse('https://example.org/b'), 'Вторая страница', 'read'),
    ]));
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: SingleChildScrollView(child: WebSourcesView(trace: trace)))));
    expect(find.text('Найдено 2 страницы'), findsOneWidget);
    expect(find.text('example.com · Найдено'), findsNothing);
    await tester.tap(find.text('Найдено 2 страницы'));
    await tester.pumpAndSettle();
    expect(find.text('example.com · Найдено'), findsOneWidget);
    expect(find.text('example.org · Прочитано'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
