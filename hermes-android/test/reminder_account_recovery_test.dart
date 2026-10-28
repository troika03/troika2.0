import 'dart:async';
import 'dart:convert';
import 'dart:io';

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
      'troika_server_url': 'https://reminder.test',
      'troika_account_email': 'synthetic@example.test',
      'troika_api_key': 'trk_live_old',
      'troika_access_token_expires_at': DateTime.now()
          .add(const Duration(days: 1))
          .millisecondsSinceEpoch,
      'troika_session_id': 'ses_test',
      'troika_session_key': 'ses_test',
    });
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          if (call.method == 'getRefreshToken') return 'trk_refresh_test';
          if (call.method == 'storeRefreshToken') return true;
          return null;
        });
    await TroikaConfig.init();
  });
  tearDown(
    () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null),
  );

  test(
    'rejected access token refreshes once before cancelling reminders',
    () async {
      var reads = 0;
      var refreshes = 0;
      await http.runWithClient(
        () async {
          final plan = await TroikaApiService().reminderDeliveryPlan();
          expect(plan['owner_id'], 'usr_test');
        },
        () => MockClient((request) async {
          if (request.url.path.endsWith('/reminders')) {
            reads++;
            expect(
              request.headers['Authorization'],
              reads == 1 ? 'Bearer trk_live_old' : 'Bearer trk_live_new',
            );
            return reads == 1
                ? http.Response('{}', 401)
                : http.Response('{"owner_id":"usr_test","reminders":[]}', 200);
          }
          refreshes++;
          expect(jsonDecode(request.body)['refresh_token'], 'trk_refresh_test');
          return http.Response(
            jsonEncode({
              'access_token': 'trk_live_new',
              'refresh_token': 'trk_refresh_new',
              'access_expires_at':
                  DateTime.now().millisecondsSinceEpoch / 1000 + 86400,
              'home_session_id': 'ses_test',
            }),
            200,
          );
        }),
      );
      expect(reads, 2);
      expect(refreshes, 1);
    },
    skip: !Platform.isWindows,
  );

  test(
    'revoked refresh credential does not retry or restore delivery',
    () async {
      var calls = 0;
      await http.runWithClient(
        () async {
          await expectLater(
            TroikaApiService().reminderDeliveryPlan(),
            throwsA(
              isA<TroikaApiException>().having(
                (error) => error.statusCode,
                'status',
                401,
              ),
            ),
          );
        },
        () => MockClient((request) async {
          calls++;
          return http.Response('{}', 401);
        }),
      );
      expect(calls, 2);
    },
    skip: !Platform.isWindows,
  );

  test(
    'temporary refresh failure preserves the offline account and alarms',
    () async {
      var clears = 0;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (call) async {
            if (call.method == 'getRefreshToken') return 'trk_refresh_test';
            if (call.method == 'clearReminders') clears++;
            return null;
          });
      await http.runWithClient(
        () async {
          await expectLater(
            TroikaApiService().reminderDeliveryPlan(),
            throwsA(
              isA<TroikaApiException>().having(
                (e) => e.statusCode,
                'status',
                503,
              ),
            ),
          );
        },
        () => MockClient(
          (request) async => http.Response(
            '{}',
            request.url.path.endsWith('/reminders') ? 401 : 503,
          ),
        ),
      );
      expect(TroikaConfig.apiKey, 'trk_live_old');
      expect(TroikaConfig.signedIn, true);
      expect(clears, 0);
    },
    skip: !Platform.isWindows,
  );

  test(
    'reminder credentials do not follow an HTTP redirect',
    () async {
      await http.runWithClient(
        () async {
          await expectLater(
            TroikaApiService().reminderDeliveryPlan(),
            throwsA(
              isA<TroikaApiException>().having(
                (e) => e.statusCode,
                'status',
                307,
              ),
            ),
          );
        },
        () => MockClient((request) async {
          expect(request.followRedirects, false);
          return http.Response(
            '{}',
            307,
            headers: {'location': 'https://other.example.test'},
          );
        }),
      );
    },
    skip: !Platform.isWindows,
  );

  test(
    'forced recovery is not swallowed by a pending ordinary freshness check',
    () async {
      final entered = Completer<void>();
      final release = Completer<String>();
      var reads = 0, refreshes = 0;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (call) async {
            if (call.method == 'getRefreshToken') {
              if (++reads == 1) {
                entered.complete();
                return release.future;
              }
              return 'trk_refresh_test';
            }
            if (call.method == 'storeRefreshToken') return true;
            return null;
          });
      await http.runWithClient(
        () async {
          final ordinary = AccountService().ensureFreshSession();
          await entered.future;
          final forced = AccountService().ensureFreshSession(force: true);
          release.complete('trk_refresh_test');
          expect(await ordinary, true);
          expect(await forced, true);
        },
        () => MockClient((request) async {
          refreshes++;
          return http.Response(
            jsonEncode({
              'access_token': 'trk_live_new',
              'refresh_token': 'trk_refresh_new',
              'access_expires_at':
                  DateTime.now().millisecondsSinceEpoch / 1000 + 86400,
              'home_session_id': 'ses_test',
            }),
            200,
          );
        }),
      );
      expect(refreshes, 1);
      expect(TroikaConfig.apiKey, 'trk_live_new');
    },
    skip: !Platform.isWindows,
  );

  test(
    'new account does not inherit an older account refresh failure',
    () async {
      final entered = Completer<void>();
      final release = Completer<String>();
      var reads = 0;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (call) async {
            if (call.method == 'getRefreshToken') {
              if (++reads == 1) {
                entered.complete();
                return release.future;
              }
              return 'trk_refresh_second';
            }
            if (call.method == 'storeRefreshToken') return true;
            return null;
          });
      final old = AccountService().ensureFreshSession();
      final rejected = expectLater(old, throwsA(isA<RequestIdentityChanged>()));
      await entered.future;
      await TroikaConfig.saveAccount(
        email: 'second@example.test',
        token: 'trk_live_second',
        refreshToken: 'trk_refresh_second',
        accessExpiresAt: DateTime.now().millisecondsSinceEpoch / 1000 + 86400,
        homeSessionId: 'ses_second',
      );
      final current = AccountService().ensureFreshSession();
      release.complete('trk_refresh_test');
      await rejected;
      expect(await current, true);
      expect(TroikaConfig.apiKey, 'trk_live_second');
    },
    skip: !Platform.isWindows,
  );

  test(
    'startup refresh adopts a successfully migrated home conversation',
    () async {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('troika_session_id', 'mobile_legacy');
      await prefs.setString('troika_session_key', 'mobile_legacy');
      await TroikaConfig.reloadAccountSession();
      await http.runWithClient(
        () async {
          expect(await AccountService().ensureFreshSession(force: true), true);
        },
        () => MockClient(
          (request) async => http.Response(
            jsonEncode({
              'access_token': 'trk_live_upgraded',
              'refresh_token': 'trk_refresh_upgraded',
              'access_expires_at':
                  DateTime.now().millisecondsSinceEpoch / 1000 + 86400,
              'home_session_id': 'ses_home',
            }),
            200,
          ),
        ),
      );
      expect(TroikaConfig.sessionId, 'ses_home');
      expect(TroikaConfig.voiceSessionAvailable, true);
    },
    skip: !Platform.isWindows,
  );
}
