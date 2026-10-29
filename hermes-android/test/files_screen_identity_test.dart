import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/screens/files_screen.dart';
import 'package:troika_assistant/services/files_service.dart';

class _Files extends FilesService {
  final oldOpen = Completer<String?>();
  final currentOpen = Completer<String?>();
  final opened = <String>[];

  @override
  Future<List<TroikaFile>> list() async => [
    TroikaFile(
      id: TroikaConfig.accountEmail,
      name: '${TroikaConfig.accountEmail}.pdf',
      size: 10,
      created: 1,
      ext: 'pdf',
      mimeType: 'application/pdf',
    ),
  ];

  @override
  Future<String?> openFile(TroikaFile file) {
    opened.add(file.id);
    return opened.length == 1 ? oldOpen.future : currentOpen.future;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() async {
    SharedPreferences.setMockInitialValues({
      'troika_server_url': 'https://files.example.test',
      'troika_account_email': 'first@example.test',
      'troika_api_key': 'trk_live_synthetic_first',
      'troika_session_id': 'ses_first',
      'troika_session_key': 'ses_first',
    });
    await TroikaConfig.init();
  });

  testWidgets(
    'old file completion cannot replace the new account busy state or show its error',
    (tester) async {
      final files = _Files();
      await tester.pumpWidget(MaterialApp(home: FilesScreen(files: files)));
      await tester.pumpAndSettle();
      await tester.tap(find.text('first@example.test.pdf'));
      await tester.pump();
      await TroikaConfig.saveAccount(
        email: 'second@example.test',
        token: 'trk_live_synthetic_second',
        homeSessionId: 'ses_second',
        replaceIdentity: true,
      );
      await tester.pumpAndSettle();
      expect(find.text('first@example.test.pdf'), findsNothing);
      await tester.tap(find.text('second@example.test.pdf'));
      await tester.pump();
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      files.oldOpen.complete('Синтетическая ошибка старого аккаунта');
      await tester.pump();
      expect(find.text('Синтетическая ошибка старого аккаунта'), findsNothing);
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      files.currentOpen.complete(null);
      await tester.pumpAndSettle();
      expect(find.byType(CircularProgressIndicator), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );
}
