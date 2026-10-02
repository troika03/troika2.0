import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/screens/chat_screen.dart';
import 'package:troika_assistant/screens/home_screen.dart';
import 'package:troika_assistant/screens/settings_overview_screen.dart';
import 'package:troika_assistant/services/assistant_service.dart';
import 'package:troika_assistant/services/assistant_result.dart';
import 'package:troika_assistant/services/troika_api_service.dart';
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
    expect(find.text('Готова'), findsOneWidget);
    expect(find.text('Нажми и скажи, что сделать'), findsOneWidget);
    expect(_orb(tester).state, VoiceOrbState.idle);
    expect(find.text('Текст'), findsOneWidget);
    expect(find.byType(ChatScreen), findsNothing);
    expect(find.text('Главная'), findsOneWidget);
    expect(find.text('Дела'), findsOneWidget);
    expect(find.text('Файлы'), findsOneWidget);
    expect(find.text('Профиль'), findsOneWidget);

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

  testWidgets('Windows switches between Command Center and Compact Assistant',
      (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final assistant = AssistantService();

    await tester.pumpWidget(_app(assistant, windowsShell: true));
    await tester.pump();

    expect(find.text('Главная'), findsOneWidget);
    expect(find.text('Дела'), findsOneWidget);
    expect(find.text('История'), findsOneWidget);
    expect(find.text('Память'), findsOneWidget);
    expect(find.text('Compact'), findsOneWidget);

    await tester.tap(find.text('Compact'));
    await tester.pump();

    expect(find.textContaining('Ctrl + Alt + Space'), findsOneWidget);
    expect(find.byTooltip('Command Center'), findsOneWidget);
    expect(find.byTooltip('Закрыть · Esc'), findsOneWidget);
    expect(find.byType(StatusOrb), findsOneWidget);

    await tester.tap(find.byTooltip('Command Center'));
    await tester.pump();
    expect(find.text('Compact'), findsOneWidget);

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
    expect(_orb(tester).state, VoiceOrbState.done);
    expect(
      tester.widget<FilledButton>(
        find.widgetWithText(FilledButton, 'Открыть файлы'),
      ),
      isNotNull,
    );

    await tester.pumpWidget(const SizedBox.shrink());
    assistant.dispose();
  });

  testWidgets('unconfirmed answer does not show the completed-action orb',
      (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final assistant = _ResultAssistant(
      AssistantResult.forTurn(
        response: 'Не удалось подтвердить выполнение просьбы.',
        successfulTools: const ['action'],
      ),
    );

    await tester.pumpWidget(_app(assistant));
    await tester.pump();

    expect(_orb(tester).state, VoiceOrbState.idle);
    expect(find.text('Готово'), findsNothing);
    expect(find.text('Результат сохранён ниже'), findsNothing);

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

  testWidgets('working state shows one assistant without internal routing',
      (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final assistant = _WorkingAssistant();

    await tester.pumpWidget(_app(assistant));
    await tester.pump();

    expect(find.text('Ищу источники'), findsWidgets);
    expect(_orb(tester).state, VoiceOrbState.acting);
    expect(find.textContaining('Ход мыслей'), findsNothing);
    expect(find.textContaining('инструмент'), findsNothing);
    expect(find.textContaining('модель'), findsNothing);

    await tester.tap(find.text('Текст'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));
    expect(find.textContaining('Ход мыслей'), findsNothing);
    expect(find.textContaining('secret-tool'), findsNothing);

    await tester.pumpWidget(const SizedBox.shrink());
    assistant.dispose();
  });

  testWidgets('normal settings stay small and hide technical connection fields',
      (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final assistant = AssistantService();

    await tester.pumpWidget(_app(assistant));
    await tester.tap(find.text('Профиль'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));

    expect(find.byType(SettingsOverviewScreen), findsOneWidget);
    expect(find.text('Голос'), findsOneWidget);
    expect(find.text('Аккаунт'), findsOneWidget);
    expect(find.text('Устройства'), findsOneWidget);
    expect(find.text('Память и приватность'), findsOneWidget);
    expect(find.text('Фоновое пробуждение'), findsOneWidget);
    expect(find.text('Выключено'), findsOneWidget);
    expect(find.text('Что помнит Тройка'), findsOneWidget);
    expect(find.text('URL сервера'), findsNothing);
    expect(find.text('API ключ'), findsNothing);

    await tester.tap(find.text('Этот телефон и разрешения'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));
    expect(find.text('Управление телефоном'), findsOneWidget);
    expect(find.text('URL сервера'), findsNothing);
    tester.state<NavigatorState>(find.byType(Navigator)).pop();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));

    await tester.scrollUntilVisible(
      find.text('Интерфейс'),
      250,
      scrollable: find.byType(Scrollable).last,
    );
    expect(find.text('Интерфейс'), findsOneWidget);
    expect(find.text('Дополнительно'), findsNothing);

    await tester.pumpWidget(const SizedBox.shrink());
    assistant.dispose();
  });

  testWidgets('sensitive action asks for one-time approval on home',
      (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final assistant = _ApprovalAssistant();

    await tester.pumpWidget(_app(assistant));
    await tester.pump();

    expect(find.text('Подтвердить важное действие'), findsOneWidget);
    expect(find.text('Нужно разрешение'), findsOneWidget);
    expect(find.text('Отправить сообщение контакту'), findsOneWidget);
    expect(find.text('Разрешить один раз'), findsOneWidget);
    expect(_orb(tester).state, VoiceOrbState.approval);

    await tester.tap(find.text('Разрешить один раз'));
    await tester.pump();
    expect(assistant.resolvedChoice, 'once');

    await tester.pumpWidget(const SizedBox.shrink());
    assistant.dispose();
  });

  testWidgets('listening shows animated orb and one-line transcript',
      (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final assistant = _ListeningAssistant();

    await tester.pumpWidget(_app(assistant));
    await tester.pump();

    expect(_orb(tester).state, VoiceOrbState.listening);
    expect(find.text('Слушаю'), findsWidgets);
    expect(find.text('“Создай отчёт к пятнице”'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('voice-live-transcript')),
      findsOneWidget,
    );

    await tester.pumpWidget(const SizedBox.shrink());
    assistant.dispose();
  });

  testWidgets('thinking and speaking have distinct orb states', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final thinking = _ThinkingAssistant();
    await tester.pumpWidget(_app(thinking));
    await tester.pump();
    expect(_orb(tester).state, VoiceOrbState.thinking);
    expect(find.text('Разбираюсь…'), findsWidgets);

    await tester.pumpWidget(const SizedBox.shrink());
    thinking.dispose();

    final speaking = _SpeakingAssistant();
    await tester.pumpWidget(_app(speaking));
    await tester.pump();
    expect(_orb(tester).state, VoiceOrbState.speaking);
    expect(find.text('Отвечаю'), findsWidgets);
    expect(find.text('Нажми, чтобы прервать ответ'), findsWidgets);

    await tester.pumpWidget(const SizedBox.shrink());
    speaking.dispose();
  });

  test('light alternative keeps Troika accent and readable contrast', () {
    final theme = buildTroikaLightTheme();

    expect(theme.brightness, Brightness.light);
    expect(theme.colorScheme.primary, TroikaColors.brandDeep);
    expect(theme.scaffoldBackgroundColor, TroikaLightColors.bg);
    expect(theme.textTheme.bodyLarge?.color, TroikaLightColors.text);
  });

  test('tool names become concrete user-safe activity statuses', () {
    expect(
      AssistantService.safeActivityStatusForTool('web_research'),
      'Ищу источники',
    );
    expect(
      AssistantService.safeActivityStatusForTool('troika_create_docx'),
      'Создаю документ',
    );
    expect(
      AssistantService.safeActivityStatusForTool('android_open_app'),
      'Открываю приложение',
    );
    expect(
      AssistantService.safeActivityStatusForTool('secret_internal_tool'),
      'Выполняю задачу',
    );
  });
}

StatusOrb _orb(WidgetTester tester) {
  return tester.widget<StatusOrb>(find.byType(StatusOrb));
}

class _ResultAssistant extends AssistantService {
  final AssistantResult result;

  _ResultAssistant(this.result);

  @override
  AssistantResult get lastResult => result;
}

class _WorkingAssistant extends AssistantService {
  final List<ChatMessage> _workingMessages = [
    ChatMessage(
      role: 'assistant',
      pending: true,
      thoughts: [ThoughtStep(ThoughtKind.toolStart, 'secret-tool')],
    ),
  ];

  @override
  AssistantState get state => AssistantState.processing;

  @override
  bool get isActing => true;

  @override
  String get activityStatus => 'Ищу источники';

  @override
  List<ChatMessage> get messages => _workingMessages;
}

class _ListeningAssistant extends AssistantService {
  @override
  AssistantState get state => AssistantState.recording;

  @override
  String get liveTranscript => 'Создай отчёт к пятнице';
}

class _ThinkingAssistant extends AssistantService {
  @override
  AssistantState get state => AssistantState.processing;
}

class _SpeakingAssistant extends AssistantService {
  @override
  AssistantState get state => AssistantState.speaking;
}

class _ApprovalAssistant extends AssistantService {
  RunApprovalRequest? request = const RunApprovalRequest(
    action: 'send_message',
    description: 'Отправить сообщение контакту',
    choices: ['once', 'deny'],
  );
  String? resolvedChoice;

  @override
  RunApprovalRequest? get pendingApproval => request;

  @override
  void resolvePendingApproval(String choice) {
    resolvedChoice = choice;
    request = null;
    notifyListeners();
  }
}

Widget _app(AssistantService assistant, {bool windowsShell = false}) {
  return ChangeNotifierProvider.value(
    value: assistant,
    child: MaterialApp(
      theme: buildTroikaTheme(),
      home: HomeScreen(windowsShellOverride: windowsShell),
    ),
  );
}
