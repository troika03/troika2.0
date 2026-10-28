import 'dart:async';
import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/services/account_service.dart';
import 'package:troika_assistant/services/request_identity.dart';
import 'package:troika_assistant/services/troika_api_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('com.troika.hermes/background');

  setUp(() async {
    SharedPreferences.setMockInitialValues({
      'troika_server_url': 'https://first.example.test',
      'troika_api_key': 'local_gateway',
      'troika_session_id': 'ses_first',
      'troika_session_key': 'ses_first',
    });
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          if (call.method == 'storeRefreshToken') return true;
          return null;
        });
    await TroikaConfig.init();
  });
  tearDown(
    () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null),
  );

  test('account credentials never follow an HTTP redirect', () async {
    await http.runWithClient(
      () async {
        await expectLater(
          AccountService().login(
            email: 'synthetic@example.test',
            password: 'synthetic-test-password',
          ),
          throwsA(isA<AccountException>()),
        );
      },
      () => MockClient((request) async {
        expect(request.followRedirects, isFalse);
        return http.Response(
          '{}',
          307,
          headers: {'location': 'https://other.example.test'},
        );
      }),
    );
    expect(TroikaConfig.signedIn, isFalse);
  });

  test(
    'account response cannot sign in after connection identity changes',
    () async {
      final entered = Completer<void>();
      final release = Completer<void>();
      await http.runWithClient(
        () async {
          final login = AccountService().login(
            email: 'synthetic@example.test',
            password: 'synthetic-test-password',
          );
          final rejected = expectLater(
            login,
            throwsA(isA<RequestIdentityChanged>()),
          );
          await entered.future;
          TroikaConfig.serverUrl = 'https://other.example.test';
          release.complete();
          await rejected;
        },
        () => MockClient((request) async {
          entered.complete();
          await release.future;
          return http.Response(
            jsonEncode({
              'token': 'trk_live_synthetic',
              'refresh_token': 'trk_refresh_synthetic',
              'access_expires_at':
                  DateTime.now().millisecondsSinceEpoch / 1000 + 86400,
              'home_session_id': 'ses_synthetic',
            }),
            200,
          );
        }),
      );
      expect(TroikaConfig.signedIn, isFalse);
    },
  );

  test('late reminder snapshot cannot cross a changed origin', () async {
    final entered = Completer<void>();
    final release = Completer<void>();
    var requests = 0;
    await http.runWithClient(
      () async {
        final plan = TroikaApiService().reminderDeliveryPlan();
        final rejected = expectLater(
          plan,
          throwsA(isA<RequestIdentityChanged>()),
        );
        await entered.future;
        TroikaConfig.serverUrl = 'https://other.example.test';
        release.complete();
        await rejected;
      },
      () => MockClient((request) async {
        requests++;
        expect(request.url.host, 'first.example.test');
        entered.complete();
        await release.future;
        return http.Response(
          '{"owner_id":"usr_synthetic","reminders":[]}',
          200,
        );
      }),
    );
    expect(requests, 1);
  });
}
