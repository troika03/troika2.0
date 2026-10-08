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
  @override Future<void> recoverPending() async {}
  @override Future<List<TroikaFile>> localFiles() async => [];
}
class IdleAgent extends DevelopmentAgentService {
  @override Future<void> stop() async {}
}
class IdleRunner extends DevelopmentService {
  @override Future<void> stop() async {}
}
class AvailablePCs extends DevelopmentRemoteService {
  @override Future<List<DevelopmentTarget>> targets() async => List.generate(8, (i) => DevelopmentTarget('pc$i', 'Компьютер $i'));
  @override Future<void> stopOutgoing() async {}
  @override Future<void> disable() async {}
}
void main() {
  setUp(() async { SharedPreferences.setMockInitialValues({}); await TroikaConfig.init(); });
  testWidgets('phone asks where to check and scrolls all PCs at large text size', (tester) async {
    tester.view.physicalSize = const Size(375, 812);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize); addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(builder: (context, child) => MediaQuery(data: MediaQuery.of(context).copyWith(textScaler: const TextScaler.linear(1.4)), child: child!), home: DevelopmentScreen(files: EmptyFiles(), agent: IdleAgent(), runner: IdleRunner(), remote: AvailablePCs(), androidForTesting: true, windowsForTesting: false)));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), 'Создай калькулятор index.js');
    await tester.ensureVisible(find.text('Разработать проект')); await tester.tap(find.text('Разработать проект')); await tester.pump(); await tester.pump(const Duration(seconds: 1));
    expect(find.text('Где проверять код?'), findsOneWidget);
    expect(find.text('На этом телефоне'), findsOneWidget);
    expect(find.text('Компьютер 0'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.ensureVisible(find.text('Компьютер 7')); await tester.pump(const Duration(seconds: 1));
    await tester.tap(find.text('Компьютер 7')); await tester.pump(); await tester.pump(const Duration(seconds: 1));
    expect(find.text('Разрешить проверку и исправление?'), findsOneWidget);
    expect(find.textContaining('Исходники временно передаются выбранному ПК.'), findsOneWidget);
    await tester.tap(find.text('Отмена')); await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox()); await tester.pumpAndSettle();
  });
}
