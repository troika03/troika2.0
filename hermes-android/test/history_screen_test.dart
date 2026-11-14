import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/screens/history_screen.dart';
import 'package:troika_assistant/services/troika_api_service.dart';

class _FakeApi extends TroikaApiService {
  final List<SessionSummary> sessions;
  final calls = <String>[];
  _FakeApi(this.sessions);

  @override
  Future<List<SessionSummary>> listSessions({
    int limit = 50,
    int offset = 0,
  }) async => List.of(sessions);

  @override
  Future<String?> renameSession(String sessionId, String title) async {
    calls.add('rename:$sessionId:$title');
    final i = sessions.indexWhere((s) => s.id == sessionId);
    sessions[i] = SessionSummary(
      id: sessionId,
      messageCount: sessions[i].messageCount,
      title: title,
      preview: sessions[i].preview,
      lastActive: sessions[i].lastActive,
    );
    return title;
  }

  @override
  Future<void> deleteSession(String sessionId) async {
    calls.add('delete:$sessionId');
    sessions.removeWhere((s) => s.id == sessionId);
  }
}

void main() {
  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await TroikaConfig.init();
  });

  SessionSummary summary(String id, String preview) => SessionSummary(
    id: id,
    messageCount: 2,
    preview: preview,
    lastActive: DateTime.now().millisecondsSinceEpoch / 1000,
  );

  testWidgets('history renames and deletes one whole conversation', (
    tester,
  ) async {
    final api = _FakeApi([
      summary('home', 'Первый разговор'),
      summary('desktop-2', 'Второй разговор'),
    ]);
    await tester.pumpWidget(MaterialApp(home: HistoryScreen(api: api)));
    await tester.pumpAndSettle();
    expect(find.text('Первый разговор'), findsOneWidget);

    await tester.tap(find.byTooltip('Действия с разговором').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Переименовать'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).last, '  Проект  ');
    await tester.tap(find.text('Сохранить'));
    await tester.pumpAndSettle();
    expect(api.calls, ['rename:home:Проект']);
    expect(find.text('Проект'), findsOneWidget);

    await tester.tap(find.byTooltip('Действия с разговором').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Удалить'));
    await tester.pumpAndSettle();
    // Destructive action needs explicit confirmation.
    expect(api.calls.length, 1);
    await tester.tap(find.widgetWithText(FilledButton, 'Удалить'));
    await tester.pumpAndSettle();
    expect(api.calls.last, 'delete:desktop-2');
    expect(find.text('Второй разговор'), findsNothing);
    expect(find.text('Проект'), findsOneWidget);
  });
}
