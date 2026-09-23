import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/screens/chat_screen.dart';
import 'package:troika_assistant/screens/home_screen.dart';
import 'package:troika_assistant/services/assistant_service.dart';
import 'package:troika_assistant/services/assistant_result.dart';
import 'package:troika_assistant/theme/troika_theme.dart';
import 'package:troika_assistant/widgets/status_orb.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() async {
    SharedPreferences.setMockInitialValues({
      'troika_server_url': '',
      'troika_local_mode': 'normal',
    });
    await TroikaConfig.init();
  });

  testWidgets('mobile home is voice-first and chat is secondary',
      (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final assistant = AssistantService();

    await tester.pumpWidget(_app(assistant));
    await tester.pump();

    expect(find.byType(StatusOrb), findsOneWidget);
    expect(find.text('Что сделать?'), findsOneWidget);
    expect(find.text('Нажми и скажи, что сделать'), findsOneWidget);
    expect(find.text('Текст'), findsOneWidget);
    expect(find.byType(ChatScreen), findsNothing);
    expect(find.text('Команды'), findsOneWidget);
    expect(find.text('Документы'), findsOneWidget);
    expect(find.text('Настройки'), findsOneWidget);

    await tester.tap(find.text('Текст'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));

    expect(find.byType(ChatScreen), findsOneWidget);
    expect(find.text('Сообщение…'), findsOneWidget);

    await tester.pumpWidget(const SizedBox.shrink());
    assistant.dispose();
  });

  testWidgets('wide home keeps voice orb as primary content', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final assistant = AssistantService();

    await tester.pumpWidget(_app(assistant));
    await tester.pump();

    expect(find.byType(StatusOrb), findsOneWidget);
    expect(find.text('Что сделать?'), findsOneWidget);
    expect(find.text('Текст'), findsOneWidget);
    expect(find.byType(ChatScreen), findsNothing);
    expect(find.byType(NavigationBar), findsNothing);

    await tester.pumpWidget(const SizedBox.shrink());
    assistant.dispose();
  });

  testWidgets('home prioritizes a completed file over the long answer',
      (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final assistant = _ResultAssistant(
      const AssistantResult(
        kind: AssistantResultKind.file,
        title: 'Отчёт.pdf',
        summary: 'Файл готов и сохранён.',
        resourceId: 'art_123',
      ),
    );

    await tester.pumpWidget(_app(assistant));
    await tester.pump();

    expect(find.text('Отчёт.pdf'), findsOneWidget);
    expect(find.text('Файл готов и сохранён.'), findsOneWidget);
    expect(find.text('Открыть файлы'), findsOneWidget);

    await tester.pumpWidget(const SizedBox.shrink());
    assistant.dispose();
  });

  testWidgets('saved task opens the task surface instead of chat',
      (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final assistant = _ResultAssistant(
      const AssistantResult(
        kind: AssistantResultKind.saved,
        title: 'Проверить релиз',
        summary: 'Задача добавлена на завтра.',
        resourceId: 'task_123',
      ),
    );

    await tester.pumpWidget(_app(assistant));
    await tester.pump();

    expect(find.text('Проверить релиз'), findsOneWidget);
    expect(find.text('Открыть задачи'), findsOneWidget);
    expect(find.text('Открыть текст'), findsNothing);

    await tester.pumpWidget(const SizedBox.shrink());
    assistant.dispose();
  });
}

class _ResultAssistant extends AssistantService {
  final AssistantResult result;

  _ResultAssistant(this.result);

  @override
  AssistantResult get lastResult => result;
}

Widget _app(AssistantService assistant) {
  return ChangeNotifierProvider.value(
    value: assistant,
    child: MaterialApp(
      theme: buildTroikaTheme(),
      home: const HomeScreen(),
    ),
  );
}
