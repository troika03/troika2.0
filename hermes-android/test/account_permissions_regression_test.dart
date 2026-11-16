import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/screens/auth_screen.dart';
import 'package:troika_assistant/screens/settings_screen.dart';
import 'package:troika_assistant/services/assistant_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const hosted = String.fromEnvironment('TROIKA_SERVER_URL');
  const server = 'https://account.example.test';

  test(
    'repairs a damaged hosted address without removing the session',
    () async {
      SharedPreferences.setMockInitialValues({
        'troika_server_url': '$hosted:8642',
        'troika_hosted_endpoint_migration_version': 2,
        'troika_api_key': 'trk_live_example',
        'troika_account_email': 'owner@example.test',
        'troika_onboarding_done': true,
        'troika_session_id': 'ses_account',
        'troika_session_key': 'ses_account',
      });
      await TroikaConfig.init();
      await TroikaConfig.init();

      expect(TroikaConfig.serverUrl, hosted);
      expect(TroikaConfig.signedIn, isTrue);
      expect(TroikaConfig.onboardingDone, isTrue);
      expect(TroikaConfig.sessionId, 'ses_account');
    },
    skip: hosted.isEmpty ? 'requires TROIKA_SERVER_URL build define' : false,
  );

  test('only a bare local IP gets the local gateway port', () {
    expect(TroikaConfig.normalizeServerInput('$server/'), server);
    expect(
      TroikaConfig.normalizeServerInput('192.168.1.5'),
      'http://192.168.1.5:8642',
    );
    expect(
      TroikaConfig.normalizeServerInput('http://192.168.1.5:9000'),
      'http://192.168.1.5:9000',
    );
  });

  testWidgets('permissions can open without checking or losing the account', (
    tester,
  ) async {
    SharedPreferences.setMockInitialValues({
      'troika_server_url': server,
      'troika_api_key': 'trk_live_example',
      'troika_account_email': 'owner@example.test',
    });
    await TroikaConfig.init();
    var accountRequests = 0;
    var signedOut = false;
    await http.runWithClient(
      () async {
        await tester.pumpWidget(
          ChangeNotifierProvider(
            create: (_) => AssistantService(),
            child: MaterialApp(
              home: SettingsScreen(
                section: SettingsSection.permissions,
                onSignedOut: () => signedOut = true,
              ),
            ),
          ),
        );
        await tester.pump();
        final settingsList = tester.state<ScrollableState>(
          find.byType(Scrollable).first,
        );
        settingsList.position.jumpTo(settingsList.position.maxScrollExtent);
        await tester.pump(const Duration(milliseconds: 300));
      },
      () => MockClient((_) async {
        accountRequests++;
        return http.Response('{}', 401);
      }),
    );

    expect(accountRequests, 0);
    expect(find.text('Сохранить'), findsNothing);
    expect(TroikaConfig.signedIn, isTrue);
    expect(signedOut, isFalse);
  });

  testWidgets('returning devices open the sign-in form', (tester) async {
    SharedPreferences.setMockInitialValues({
      'troika_server_url': server,
      'troika_onboarding_done': true,
    });
    await TroikaConfig.init();

    await tester.pumpWidget(
      MaterialApp(home: AuthScreen(onAuthenticated: () {})),
    );

    expect(find.widgetWithText(FilledButton, 'Войти'), findsOneWidget);
  });

  testWidgets('an existing registration switches to sign-in', (tester) async {
    SharedPreferences.setMockInitialValues({'troika_server_url': server});
    await TroikaConfig.init();
    final attemptedPaths = <String>[];

    await http.runWithClient(
      () async {
        await tester.pumpWidget(
          MaterialApp(home: AuthScreen(onAuthenticated: () {})),
        );
        await tester.enterText(
          find.byType(TextField).at(0),
          'owner@example.test',
        );
        await tester.enterText(find.byType(TextField).at(1), 'test-password');
        await tester.tap(
          find.widgetWithText(FilledButton, 'Зарегистрироваться'),
        );
        await tester.pumpAndSettle();
      },
      () => MockClient((request) async {
        attemptedPaths.add(request.url.path);
        return http.Response(
          '{"error":{"message":"Account already exists"}}',
          409,
        );
      }),
    );

    expect(attemptedPaths, ['/v1/auth/register']);
    expect(find.widgetWithText(FilledButton, 'Войти'), findsOneWidget);
    expect(
      find.text('Аккаунт с этой почтой уже есть. Нажмите «Войти».'),
      findsOneWidget,
    );
  });
}
