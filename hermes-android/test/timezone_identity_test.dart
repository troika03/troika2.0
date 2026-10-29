import 'dart:async';
import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/services/troika_api_service.dart';

const _preferences = {
  'reminders_enabled': false,
  'proactive_enabled': true,
  'quiet_hours_enabled': true,
  'timezone': 'UTC',
  'quiet_start': '21:30',
  'quiet_end': '07:45',
};

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('com.troika.hermes/background');
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

  setUp(() async {
    SharedPreferences.setMockInitialValues({
      'troika_server_url': 'https://first.example.test',
      'troika_account_email': 'first@example.test',
      'troika_api_key': 'trk_live_first',
      'troika_session_id': 'ses_first',
      'troika_session_key': 'ses_first',
    });
    messenger.setMockMethodCallHandler(channel, (_) async => true);
    await TroikaConfig.init();
  });
  tearDown(() => messenger.setMockMethodCallHandler(channel, null));

  Future<void> changeIdentity(String transition) async {
    if (transition == 'origin') {
      TroikaConfig.serverUrl = 'https://second.example.test';
      await Future<void>.delayed(Duration.zero);
    } else {
      await TroikaConfig.saveAccount(
        email: 'second@example.test',
        token: 'trk_live_second',
        homeSessionId: 'ses_second',
      );
    }
  }

  for (final transition in ['account', 'origin']) {
    for (final phase in ['device zone', 'preferences GET']) {
      test(
        '$transition during $phase cannot update another identity',
        () async {
          final entered = Completer<void>(), release = Completer<void>();
          final requests = <http.Request>[];
          await http.runWithClient(
            () async {
              final sync = TroikaApiService().syncDeviceTimeZone(
                readTimeZone: () async {
                  if (phase == 'device zone') {
                    entered.complete();
                    await release.future;
                  }
                  return 'Europe/Moscow';
                },
              );
              await entered.future.timeout(const Duration(seconds: 2));
              await changeIdentity(transition);
              release.complete();
              expect(await sync, isFalse);
            },
            () => MockClient((request) async {
              requests.add(request);
              expect(request.url.host, 'first.example.test');
              expect(request.headers['Authorization'], 'Bearer trk_live_first');
              expect(request.method, 'GET');
              entered.complete();
              await release.future;
              return http.Response(jsonEncode(_preferences), 200);
            }),
          );
          expect(requests, phase == 'device zone' ? isEmpty : hasLength(1));
        },
      );
    }
  }

  test('timezone update preserves consent and quiet-hour settings', () async {
    final requests = <http.Request>[];
    await http.runWithClient(
      () async {
        expect(
          await TroikaApiService().syncDeviceTimeZone(
            readTimeZone: () async => 'Europe/Moscow',
          ),
          isTrue,
        );
      },
      () => MockClient((request) async {
        requests.add(request);
        expect(request.url.host, 'first.example.test');
        expect(request.headers['Authorization'], 'Bearer trk_live_first');
        expect(request.url.path, '/v1/notification-preferences');
        if (request.method == 'GET') {
          return http.Response(jsonEncode(_preferences), 200);
        }
        expect(request.method, 'PUT');
        expect(jsonDecode(request.body), {
          ..._preferences,
          'timezone': 'Europe/Moscow',
        });
        return http.Response('{}', 200);
      }),
    );
    expect(requests.map((request) => request.method), ['GET', 'PUT']);
  });

  for (final redirectMethod in ['GET', 'PUT']) {
    test(
      '$redirectMethod preferences redirect never forwards credentials',
      () async {
        final methods = <String>[];
        await http.runWithClient(
          () async {
            expect(
              await TroikaApiService().syncDeviceTimeZone(
                readTimeZone: () async => 'Europe/Moscow',
              ),
              isFalse,
            );
          },
          () => MockClient((request) async {
            methods.add(request.method);
            expect(request.url.host, 'first.example.test');
            expect(request.followRedirects, isFalse);
            if (request.method == redirectMethod) {
              return http.Response(
                '{}',
                307,
                headers: {
                  'location': 'https://external.example.test/preferences',
                },
              );
            }
            return http.Response(jsonEncode(_preferences), 200);
          }),
        );
        expect(methods, redirectMethod == 'GET' ? ['GET'] : ['GET', 'PUT']);
      },
    );
  }

  test('oversize streamed preferences are rejected before PUT', () async {
    final methods = <String>[];
    await http.runWithClient(
      () async {
        expect(
          await TroikaApiService().syncDeviceTimeZone(
            readTimeZone: () async => 'Europe/Moscow',
          ),
          isFalse,
        );
      },
      () => MockClient.streaming((request, body) async {
        methods.add(request.method);
        return http.StreamedResponse(
          Stream.fromIterable([
            List<int>.filled(64 * 1024, 32),
            utf8.encode(jsonEncode(_preferences)),
          ]),
          200,
        );
      }),
    );
    expect(methods, ['GET']);
  });

  test('account switch during body read never starts PUT', () async {
    final entered = Completer<void>();
    final body = StreamController<List<int>>(onListen: entered.complete);
    final methods = <String>[];
    await http.runWithClient(
      () async {
        final sync = TroikaApiService().syncDeviceTimeZone(
          readTimeZone: () async => 'Europe/Moscow',
        );
        await entered.future.timeout(const Duration(seconds: 2));
        await changeIdentity('account');
        body.add(utf8.encode(jsonEncode(_preferences)));
        await body.close();
        expect(await sync, isFalse);
      },
      () => MockClient.streaming((request, _) async {
        methods.add(request.method);
        return http.StreamedResponse(body.stream, 200);
      }),
    );
    expect(methods, ['GET']);
  });

  test(
    'late PUT response cannot report success for a changed identity',
    () async {
      final entered = Completer<void>(), release = Completer<void>();
      await http.runWithClient(
        () async {
          final sync = TroikaApiService().syncDeviceTimeZone(
            readTimeZone: () async => 'Europe/Moscow',
          );
          await entered.future.timeout(const Duration(seconds: 2));
          await changeIdentity('account');
          release.complete();
          expect(await sync, isFalse);
        },
        () => MockClient((request) async {
          if (request.method == 'GET') {
            return http.Response(jsonEncode(_preferences), 200);
          }
          expect(request.url.host, 'first.example.test');
          expect(request.headers['Authorization'], 'Bearer trk_live_first');
          entered.complete();
          await release.future;
          return http.Response('{}', 200);
        }),
      );
    },
  );
}
