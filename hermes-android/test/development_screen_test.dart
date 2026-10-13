import 'dart:convert';
import 'dart:typed_data';
import 'package:archive/archive.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/screens/development_screen.dart';
import 'package:troika_assistant/services/development_agent_service.dart';
import 'package:troika_assistant/services/development_remote_service.dart';
import 'package:troika_assistant/services/development_service.dart';
import 'package:troika_assistant/services/files_service.dart';

class EmptyFiles extends FilesService {
  @override
  Future<void> recoverPending() async {}
  @override
  Future<List<TroikaFile>> localFiles() async => [];
}

class IdleAgent extends DevelopmentAgentService {
  String? prompt;
  @override
  Future<GeneratedProject> generate(String input,
      {void Function(String)? onStatus}) async {
    prompt = input;
    final archive = Archive();
    for (final entry in {
      'troika-project.json': json.encode({
        'version': 1,
        'files': ['MODEL_REVIEW.md'],
        'review': {
          'method': 'api_model_review',
          'status': 'passed',
          'execution': 'not_run'
        }
      }),
      'MODEL_REVIEW.md': 'Модель проверила исходники. Тесты не запускались.',
    }.entries) {
      final bytes = utf8.encode(entry.value);
      archive.addFile(ArchiveFile(entry.key, bytes.length, bytes));
    }
    return GeneratedProject(
        TroikaFile(
            id: 'project',
            name: 'project.zip',
            size: 100,
            created: 1,
            ext: 'zip',
            mimeType: 'application/zip',
            localPath: '/test/project.zip'),
        Uint8List.fromList(ZipEncoder().encode(archive)));
  }

  @override
  Future<void> stop() async {}
}

class IdleRunner extends DevelopmentService {
  @override
  Future<void> stop() async {}
}

class AvailablePCs extends DevelopmentRemoteService {
  @override
  Future<List<DevelopmentTarget>> targets() async =>
      List.generate(8, (i) => DevelopmentTarget('pc$i', 'Компьютер $i'));
  @override
  Future<void> stopOutgoing() async {}
  @override
  Future<void> disable() async {}
}

void main() {
  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await TroikaConfig.init();
  });
  testWidgets(
      'model review is default and creates a project without device selection',
      (tester) async {
    final agent = IdleAgent();
    await tester.pumpWidget(MaterialApp(
        home: DevelopmentScreen(
            files: EmptyFiles(),
            agent: agent,
            runner: IdleRunner(),
            remote: AvailablePCs(),
            androidForTesting: true,
            windowsForTesting: false)));
    await tester.pumpAndSettle();
    expect(find.text('Модель: ревью и исправление'), findsOneWidget);
    await tester.enterText(
        find.byType(TextField), 'Создай сайт для подсчёта калорий');
    tester.testTextInput.hide();
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Разработать проект'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Разработать проект'));
    await tester.pumpAndSettle();
    expect(agent.prompt, contains('troika_create_project с title и task'));
    expect(agent.prompt, contains('Создай сайт для подсчёта калорий'));
    expect(find.text('Где проверять код?'), findsNothing);
    expect(find.text('Разрешить проверку и исправление?'), findsNothing);
    expect(
        find.text(
            'Проект сохранён. Модель проверила исходники. Тесты не запускались.'),
        findsOneWidget);
    expect(find.text('Ревью модели'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();
  });
  testWidgets(
      'phone asks where to check and scrolls all PCs at large text size',
      (tester) async {
    tester.view.physicalSize = const Size(375, 812);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(
        builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context)
                .copyWith(textScaler: const TextScaler.linear(1.4)),
            child: child!),
        home: DevelopmentScreen(
            files: EmptyFiles(),
            agent: IdleAgent(),
            runner: IdleRunner(),
            remote: AvailablePCs(),
            androidForTesting: true,
            windowsForTesting: false)));
    await tester.pumpAndSettle();
    await tester.tap(find.byType(DropdownButtonFormField<String>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Python: тесты unittest').last);
    await tester.pumpAndSettle();
    await tester.enterText(
        find.byType(TextField), 'Создай калькулятор index.js');
    tester.testTextInput.hide();
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Разработать проект'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Разработать проект'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(find.text('Где проверять код?'), findsOneWidget);
    expect(find.text('На этом телефоне'), findsOneWidget);
    expect(find.text('Компьютер 0'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.ensureVisible(find.text('Компьютер 7'));
    await tester.pump(const Duration(seconds: 1));
    await tester.tap(find.text('Компьютер 7'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(find.text('Разрешить проверку и исправление?'), findsOneWidget);
    expect(find.textContaining('Исходники временно передаются выбранному ПК.'),
        findsOneWidget);
    await tester.tap(find.text('Отмена'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();
  });
}
