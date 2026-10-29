import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/services/request_identity.dart';
import 'package:troika_assistant/services/troika_api_service.dart';
import 'package:troika_assistant/services/tts_service.dart';

class _Requests {
  final rows = <Map<String, String>>[];
  final approvalChoices = <String>[];
  Future<void>? capabilitiesGate;
  Completer<void>? capabilitiesEntered;
  bool retryStart = false, emptyEvents = false;
  Future<void>? fallbackGate;
  Completer<void>? fallbackEntered;
  Future<void>? tokenResponseGate;
  Completer<void>? tokenResponseEntered;
  String events =
      'data: {"event":"message.delta","delta":"Synthetic answer"}\n\n'
      'data: {"event":"run.completed"}\n\n';

  late final client = MockClient.streaming((request, body) async {
    final payload = await body.bytesToString();
    rows.add({
      'host': request.url.host,
      'path': request.url.path,
      'authorization': request.headers['Authorization'] ?? '',
      'body': payload,
    });
    http.StreamedResponse jsonResponse(Object value, [int status = 200]) =>
        http.StreamedResponse(
          Stream.value(utf8.encode(jsonEncode(value))),
          status,
          headers: {'content-type': 'application/json'},
        );
    switch (request.url.path) {
      case '/v1/auth/refresh':
        if (!(tokenResponseEntered?.isCompleted ?? true)) {
          tokenResponseEntered!.complete();
        }
        if (tokenResponseGate != null) await tokenResponseGate;
        return jsonResponse({
          'access_token': 'trk_live_synthetic_rotated',
          'refresh_token': 'trk_refresh_synthetic_rotated',
          'access_expires_at':
              DateTime.now().millisecondsSinceEpoch / 1000 + 86400,
          'home_session_id': 'session_original',
        });
      case '/v1/capabilities':
        if (!(capabilitiesEntered?.isCompleted ?? true)) {
          capabilitiesEntered!.complete();
        }
        if (capabilitiesGate != null) await capabilitiesGate;
        return jsonResponse({
          'features': {'device_file_delivery': true},
        });
      case '/v1/runs':
        if (retryStart) {
          retryStart = false;
          TroikaConfig.serverUrl = 'https://other.example.invalid';
          throw const HandshakeException(
            'Synthetic pre-send handshake failure',
          );
        }
        return jsonResponse({'run_id': 'run_synthetic'}, 202);
      case '/v1/runs/run_synthetic/events':
        return http.StreamedResponse(
          Stream.value(utf8.encode(emptyEvents ? '' : events)),
          200,
          headers: {'content-type': 'text/event-stream'},
        );
      case '/v1/runs/run_synthetic/approval':
        approvalChoices.add(jsonDecode(payload)['choice'] as String);
        return jsonResponse({});
      case '/v1/runs/run_synthetic':
        if (!(fallbackEntered?.isCompleted ?? true)) {
          fallbackEntered!.complete();
        }
        if (fallbackGate != null) await fallbackGate;
        return jsonResponse({
          'status': 'completed',
          'output': 'Synthetic fallback',
        });
      case '/v1/chat/completions':
        return jsonResponse({
          'choices': [
            {
              'message': {'content': 'Synthetic answer'},
            },
          ],
        });
      default:
        throw StateError('Unexpected synthetic request route');
    }
  });

  void expectOriginalOriginOnly() => expect(
    rows.where((row) => row['host'] != 'original.example.invalid'),
    isEmpty,
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  const background = MethodChannel('com.troika.hermes/background');
  Future<void>? refreshGate;
  Completer<void>? refreshEntered;

  setUp(() async {
    refreshGate = null;
    refreshEntered = null;
    SharedPreferences.setMockInitialValues({
      'troika_server_url': 'https://original.example.invalid',
      'troika_account_email': 'original@example.invalid',
      'troika_api_key': 'trk_live_synthetic_original',
      'troika_access_token_expires_at': DateTime.now()
          .add(const Duration(days: 1))
          .millisecondsSinceEpoch,
      'troika_session_id': 'session_original',
      'troika_session_key': 'session_original',
    });
    messenger.setMockMethodCallHandler(background, (call) async {
      if (call.method == 'getRefreshToken') {
        if (!(refreshEntered?.isCompleted ?? true)) refreshEntered!.complete();
        if (refreshGate != null) await refreshGate;
        return 'trk_refresh_synthetic_original';
      }
      return true;
    });
    messenger.setMockMethodCallHandler(
      const MethodChannel('flutter_tts'),
      (_) async => 1,
    );
    await TroikaConfig.init();
  });
  tearDown(() {
    messenger.setMockMethodCallHandler(background, null);
    messenger.setMockMethodCallHandler(
      const MethodChannel('flutter_tts'),
      null,
    );
  });

  Future<void> changeIdentity(String kind) async {
    if (kind == 'endpoint') {
      TroikaConfig.serverUrl = 'https://other.example.invalid';
      await Future<void>.delayed(Duration.zero);
    } else {
      await TroikaConfig.saveAccount(
        email: 'other@example.invalid',
        token: 'trk_live_synthetic_other',
        homeSessionId: 'session_other',
      );
    }
  }

  Future<String> send(TroikaApiService service, String mode) => mode == 'stream'
      ? service.streamMessage(
          ChatMessage(role: 'user', text: 'Synthetic private input'),
        )
      : service.sendMessage(
          ChatMessage(role: 'user', text: 'Synthetic private input'),
        );

  for (final mode in ['stream', 'buffered']) {
    for (final phase in ['refresh', 'capabilities', 'headers']) {
      for (final transition in ['endpoint', 'owner']) {
        test(
          '$mode $transition during $phase sends no request in a new identity',
          () async {
            final requests = _Requests();
            final entered = Completer<void>(), release = Completer<void>();
            if (phase == 'refresh') {
              refreshEntered = entered;
              refreshGate = release.future;
              final prefs = await SharedPreferences.getInstance();
              await prefs.setInt('troika_access_token_expires_at', 0);
            }
            if (phase == 'capabilities') {
              requests.capabilitiesEntered = entered;
              requests.capabilitiesGate = release.future;
            }
            final service = TroikaApiService(
              chatHeaders: () async {
                final captured = TroikaConfig.chatHeaders;
                if (phase == 'headers') {
                  entered.complete();
                  await release.future;
                }
                return captured;
              },
            );
            try {
              await http.runWithClient(() async {
                final assertion = expectLater(
                  send(service, mode),
                  throwsA(isA<RequestIdentityChanged>()),
                );
                await entered.future.timeout(const Duration(seconds: 2));
                await changeIdentity(transition);
                release.complete();
                await assertion;
                requests.expectOriginalOriginOnly();
                expect(
                  requests.rows.where(
                    (row) => row['path'] != '/v1/capabilities',
                  ),
                  isEmpty,
                );
                if (phase == 'refresh') expect(requests.rows, isEmpty);
              }, () => requests.client);
            } finally {
              if (!release.isCompleted) release.complete();
            }
          },
        );
      }
    }
  }

  test(
    'same-owner refresh updates authorization without changing the request origin',
    () async {
      final requests = _Requests();
      final service = TroikaApiService(
        chatHeaders: () async {
          final captured = TroikaConfig.chatHeaders;
          await TroikaConfig.saveAccount(
            email: TroikaConfig.accountEmail,
            token: 'trk_live_synthetic_rotated',
            homeSessionId: TroikaConfig.sessionId,
          );
          return captured;
        },
      );
      await http.runWithClient(() async {
        expect(await send(service, 'stream'), 'Synthetic answer');
        requests.expectOriginalOriginOnly();
        final start = requests.rows.singleWhere(
          (row) => row['path'] == '/v1/runs',
        );
        expect(start['authorization'], 'Bearer trk_live_synthetic_rotated');
        expect(jsonDecode(start['body']!)['session_id'], 'session_original');
      }, () => requests.client);
    },
  );

  test('same-owner actual refresh retains its request identity', () async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt('troika_access_token_expires_at', 0);
    final requests = _Requests();
    await http.runWithClient(() async {
      expect(await send(TroikaApiService(), 'stream'), 'Synthetic answer');
      expect(TroikaConfig.apiKey, 'trk_live_synthetic_rotated');
      final start = requests.rows.singleWhere(
        (row) => row['path'] == '/v1/runs',
      );
      expect(start['authorization'], 'Bearer trk_live_synthetic_rotated');
      requests.expectOriginalOriginOnly();
    }, () => requests.client);
  });

  test('late refresh response cannot overwrite a newer account', () async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt('troika_access_token_expires_at', 0);
    final entered = Completer<void>(), release = Completer<void>();
    final requests = _Requests()
      ..tokenResponseEntered = entered
      ..tokenResponseGate = release.future;
    await http.runWithClient(() async {
      final assertion = expectLater(
        send(TroikaApiService(), 'stream'),
        throwsA(isA<RequestIdentityChanged>()),
      );
      await entered.future.timeout(const Duration(seconds: 2));
      await changeIdentity('owner');
      release.complete();
      await assertion;
      expect(TroikaConfig.accountEmail, 'other@example.invalid');
      expect(TroikaConfig.apiKey, 'trk_live_synthetic_other');
      expect(TroikaConfig.sessionId, 'session_other');
      expect(requests.rows, hasLength(1));
      requests.expectOriginalOriginOnly();
    }, () => requests.client);
  });

  for (final transition in ['endpoint', 'owner']) {
    test(
      '$transition while approval is pending cannot forward the old run or decision',
      () async {
        final requests = _Requests()
          ..events =
              'data: {"event":"approval.request","choices":["once","deny"]}\n\n';
        final entered = Completer<void>(), release = Completer<String>();
        await http.runWithClient(() async {
          final assertion = expectLater(
            TroikaApiService().streamMessage(
              ChatMessage(role: 'user', text: 'Synthetic private input'),
              onApproval: (_) {
                entered.complete();
                return release.future;
              },
            ),
            throwsA(isA<RequestIdentityChanged>()),
          );
          await entered.future.timeout(const Duration(seconds: 2));
          await changeIdentity(transition);
          release.complete('once');
          await assertion;
          expect(requests.approvalChoices, isEmpty);
          requests.expectOriginalOriginOnly();
        }, () => requests.client);
      },
    );
  }

  test('same-identity cancelled approval still sends deny', () async {
    final requests = _Requests()
      ..events =
          'data: {"event":"approval.request","choices":["once","deny"]}\n\n'
          'data: {"event":"message.delta","delta":"Synthetic answer"}\n\n'
          'data: {"event":"run.completed"}\n\n';
    await http.runWithClient(() async {
      expect(
        await TroikaApiService().streamMessage(
          ChatMessage(role: 'user', text: 'Synthetic input'),
          onApproval: (_) async =>
              throw StateError('Synthetic turn cancellation'),
        ),
        'Synthetic answer',
      );
      expect(requests.approvalChoices, ['deny']);
      requests.expectOriginalOriginOnly();
    }, () => requests.client);
  });

  test(
    'TLS retry checks identity again before building another request',
    () async {
      final requests = _Requests()..retryStart = true;
      await http.runWithClient(() async {
        await expectLater(
          send(TroikaApiService(), 'stream'),
          throwsA(isA<RequestIdentityChanged>()),
        );
        requests.expectOriginalOriginOnly();
        expect(
          requests.rows.where((row) => row['path'] == '/v1/runs'),
          hasLength(1),
        );
      }, () => requests.client);
    },
  );

  test(
    'synchronous web callback cannot deliver a delta after identity change',
    () async {
      final requests = _Requests()
        ..events =
            'data: {"event":"message.delta","delta":"Synthetic old data",'
            '"web_activity":{"phase":"found","sources":[]}}\n\n';
      var deltas = 0;
      await http.runWithClient(() async {
        await expectLater(
          TroikaApiService().streamMessage(
            ChatMessage(role: 'user', text: 'Synthetic input'),
            onWebActivity: (_) {
              TroikaConfig.serverUrl = 'https://other.example.invalid';
            },
            onDelta: (_) => deltas++,
          ),
          throwsA(isA<RequestIdentityChanged>()),
        );
        expect(deltas, 0);
        requests.expectOriginalOriginOnly();
      }, () => requests.client);
    },
  );

  test(
    'synchronous tool callback cannot deliver a result after identity change',
    () async {
      final requests = _Requests()
        ..events =
            'data: {"event":"tool.completed","tool":"synthetic",'
            '"result":{"kind":"note","id":"synthetic","title":"Synthetic"}}\n\n';
      var results = 0;
      await http.runWithClient(() async {
        await expectLater(
          TroikaApiService().streamMessage(
            ChatMessage(role: 'user', text: 'Synthetic input'),
            onToolDone: (_, _) {
              TroikaConfig.serverUrl = 'https://other.example.invalid';
            },
            onResult: (_) {
              results++;
            },
          ),
          throwsA(isA<RequestIdentityChanged>()),
        );
        expect(results, 0);
        requests.expectOriginalOriginOnly();
      }, () => requests.client);
    },
  );

  test(
    'fallback response after identity change cannot start another status request',
    () async {
      final entered = Completer<void>(), release = Completer<void>();
      final requests = _Requests()
        ..emptyEvents = true
        ..fallbackEntered = entered
        ..fallbackGate = release.future;
      await http.runWithClient(() async {
        final assertion = expectLater(
          send(TroikaApiService(), 'stream'),
          throwsA(isA<RequestIdentityChanged>()),
        );
        await entered.future.timeout(const Duration(seconds: 2));
        await changeIdentity('endpoint');
        release.complete();
        await assertion;
        requests.expectOriginalOriginOnly();
        expect(
          requests.rows.where((row) => row['path'] == '/v1/runs/run_synthetic'),
          hasLength(1),
        );
      }, () => requests.client);
    },
  );

  test(
    'speech refresh preflight cannot forward a refresh token after endpoint change',
    () async {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setInt('troika_access_token_expires_at', 0);
      final entered = Completer<void>(), release = Completer<void>();
      refreshEntered = entered;
      refreshGate = release.future;
      final requests = _Requests(), service = TtsService(progressive: true);
      try {
        await http.runWithClient(() async {
          final reply = service.beginReply()..add('Synthetic phrase!');
          final finished = reply.finish();
          await entered.future.timeout(const Duration(seconds: 2));
          await changeIdentity('endpoint');
          release.complete();
          await finished;
          await Future<void>.delayed(Duration.zero);
          expect(requests.rows, isEmpty);
        }, () => requests.client);
      } finally {
        if (!release.isCompleted) release.complete();
        await service.stop();
        service.dispose();
      }
    },
  );
}
