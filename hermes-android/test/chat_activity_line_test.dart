import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/screens/chat_screen.dart';
import 'package:troika_assistant/services/assistant_service.dart';
import 'package:troika_assistant/services/troika_api_service.dart';

class _Assistant extends AssistantService {
  AssistantState current = AssistantState.processing;
  bool acting = true;
  final List<ChatMessage> _messages = [
    ChatMessage(role: 'user', text: 'Найди новости'),
    ChatMessage(role: 'assistant', pending: true),
  ];

  @override
  AssistantState get state => current;

  @override
  bool get isActing => acting;

  @override
  String get activityStatus => 'Ищу в интернете';

  @override
  List<ChatMessage> get messages => _messages;
}

Future<void> _pump(WidgetTester tester, AssistantService assistant) async {
  await tester.pumpWidget(
    ChangeNotifierProvider<AssistantService>.value(
      value: assistant,
      child: const MaterialApp(home: Scaffold(body: ChatScreen())),
    ),
  );
  await tester.pump();
}

void main() {
  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await TroikaConfig.init();
  });

  testWidgets('chat shows what Troika is doing while it works', (tester) async {
    final assistant = _Assistant();
    await _pump(tester, assistant);
    final line = find.byKey(const ValueKey('assistant-activity-line'));
    expect(line, findsOneWidget);
    expect(
      find.descendant(of: line, matching: find.text('Ищу в интернете…')),
      findsOneWidget,
    );

    assistant
      ..acting = false
      ..notifyListeners();
    await tester.pump();
    expect(
      find.descendant(of: line, matching: find.text('Думаю…')),
      findsOneWidget,
    );

    assistant
      ..current = AssistantState.idle
      ..notifyListeners();
    await tester.pump();
    expect(line, findsNothing);
  });
}
