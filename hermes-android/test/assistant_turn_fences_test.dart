import 'dart:async';
import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/services/assistant_service.dart';
import 'package:troika_assistant/services/reminder_delivery_service.dart';

class _Api {
  _Api({
    this.holdStart = false,
    this.holdStop = false,
    this.holdHistory = false,
  });
  final bool holdStart, holdStop;
  final bool holdHistory;
  final historyEntered = Completer<void>(), releaseHistory = Completer<void>();
  final startBodies = <Map<String, dynamic>>[];
  List<Map<String, dynamic>> history = [];
  Map<String, dynamic> runStatus = {'status': 'running'};
  int historyRequests = 0;
  final firstStart = Completer<void>(), releaseStart = Completer<void>();
  final stopEntered = Completer<void>(), releaseStop = Completer<void>();
  final events = <int, StreamController<List<int>>>{};
  final eventStarts = <int, Completer<void>>{};
  final stops = <String>[];
  final approvalChoices = <String>[];
  final approvalEntered = Completer<void>();
  int starts = 0, speechRequests = 0, stopStatus = 200;
  late final client = MockClient.streaming((request, body) async {
    expect(request.url.host, 'turn.example.invalid');
    final payload = await body.bytesToString();
    http.StreamedResponse response(String text, int status) =>
        http.StreamedResponse(
          Stream.value(utf8.encode(text)),
          status,
          headers: {'content-type': 'application/json'},
        );
    if (request.url.path == '/v1/capabilities') {
      return response('{"features":{"device_file_delivery":true}}', 200);
    }
    if (request.url.path == '/v1/runs') {
      startBodies.add(jsonDecode(payload) as Map<String, dynamic>);
      final number = ++starts;
      if (!firstStart.isCompleted) firstStart.complete();
      if (holdStart && number == 1) await releaseStart.future;
      return response(jsonEncode({'run_id': 'run_$number'}), 202);
    }
    if (request.url.path.startsWith('/v1/sessions/') &&
        request.url.path.endsWith('/messages')) {
      final snapshot = List<Map<String, dynamic>>.of(history);
      historyRequests++;
      if (!historyEntered.isCompleted) historyEntered.complete();
      if (holdHistory && historyRequests == 1) await releaseHistory.future;
      return response(jsonEncode({'messages': snapshot}), 200);
    }
    if (RegExp(r'^/v1/runs/run_[0-9]+$').hasMatch(request.url.path)) {
      return response(jsonEncode(runStatus), 200);
    }
    if (request.url.path.endsWith('/events')) {
      final number = int.parse(request.url.path.split('/')[3].substring(4));
      final stream = StreamController<List<int>>();
      events[number] = stream;
      (eventStarts[number] ??= Completer<void>()).complete();
      return http.StreamedResponse(
        stream.stream,
        200,
        headers: {'content-type': 'text/event-stream; charset=utf-8'},
      );
    }
    if (request.url.path.endsWith('/stop')) {
      stops.add(request.url.path.split('/')[3]);
      if (!stopEntered.isCompleted) stopEntered.complete();
      if (holdStop) await releaseStop.future;
      return response('{}', stopStatus);
    }
    if (request.url.path.endsWith('/approval')) {
      approvalChoices.add(jsonDecode(payload)['choice'] as String);
      if (!approvalEntered.isCompleted) approvalEntered.complete();
      return response('{}', 200);
    }
    if (request.url.path == '/v1/audio/speech') {
      speechRequests++;
      return response('{}', 503);
    }
    if (request.url.path == '/v1/assistant/reminders') {
      return response('{"owner_id":"usr_synthetic","reminders":[]}', 200);
    }
    throw StateError('Unexpected synthetic route.');
  });

  Future<void> waitEvents(int number) =>
      (eventStarts[number] ??= Completer<void>()).future.timeout(
        const Duration(seconds: 2),
      );
  void delta(int number, String text) => events[number]!.add(
    utf8.encode(
      'data: ${jsonEncode({'event': 'message.delta', 'delta': text})}\n\n',
    ),
  );
  Future<void> finish(int number) async {
    final stream = events[number]!;
    if (!stream.isClosed) {
      stream.add(utf8.encode('data: {"event":"run.completed"}\n\n'));
      await stream.close();
    }
  }

  Future<void> terminate(int number, String? terminal) async {
    final stream = events[number]!;
    if (terminal != null) {
      stream.add(utf8.encode('data: ${jsonEncode({'event': terminal})}\n\n'));
    }
    await stream.close();
  }

  void approval(int number) => events[number]!.add(
    utf8.encode(
      'data: ${jsonEncode({
        'event': 'approval.request',
        'action': 'Synthetic action',
        'description': 'Synthetic approval only',
        'choices': ['once', 'deny'],
      })}\n\n',
    ),
  );

  Future<void> dispose() async {
    if (!releaseStart.isCompleted) releaseStart.complete();
    if (!releaseStop.isCompleted) releaseStop.complete();
    if (!releaseHistory.isCompleted) releaseHistory.complete();
    for (final stream in events.values) {
      if (!stream.isClosed) await stream.close();
    }
    client.close();
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  final channels = <MethodChannel>[];
  void mock(String name, Future<Object?> Function(MethodCall) handler) {
    final channel = MethodChannel(name);
    channels.add(channel);
    messenger.setMockMethodCallHandler(channel, handler);
  }

  setUp(() async {
    SharedPreferences.setMockInitialValues({
      'troika_server_url': 'https://turn.example.invalid',
      'troika_account_email': 'synthetic@example.invalid',
      'troika_api_key': 'trk_live_synthetic',
      'troika_access_token_expires_at': DateTime.now()
          .add(const Duration(days: 1))
          .millisecondsSinceEpoch,
      'troika_session_id': 'ses_synthetic',
      'troika_session_key': 'ses_synthetic',
      'troika_wake_word_enabled': false,
    });
    mock(
      'com.troika.hermes/background',
      (call) async =>
          call.method == 'getRefreshToken' ? 'trk_refresh_synthetic' : null,
    );
    for (final name in [
      'flutter_tts',
      'com.llfbandit.record/messages',
      'xyz.luan/audioplayers.global',
      'xyz.luan/audioplayers.global/events',
    ]) {
      mock(name, (_) async => null);
    }
    mock('xyz.luan/audioplayers', (call) async {
      if (call.method == 'create') {
        final id = (call.arguments as Map)['playerId'];
        mock('xyz.luan/audioplayers/events/$id', (_) async => null);
      }
      return null;
    });
    await TroikaConfig.init();
  });
  tearDown(() async {
    // AudioRecorder.dispose completes platform cleanup asynchronously.
    await Future<void>.delayed(Duration.zero);
    for (final channel in channels) {
      messenger.setMockMethodCallHandler(channel, null);
    }
    channels.clear();
  });

  AssistantService assistant() => AssistantService(
    replyDelivery: ReminderDeliveryService(supported: false),
  );

  test('late old SSE cannot speak or finish a newer query', () async {
    final api = _Api(), service = assistant();
    try {
      await http.runWithClient(() async {
        final old = service.sendTextQuery(
          'Почему у дневного неба синий цвет?',
          speak: true,
        );
        await api.waitEvents(1);
        api.delta(1, 'Начало старого ответа');
        await Future<void>.delayed(const Duration(milliseconds: 20));
        final current = service.sendTextQuery(
          'Почему вечером небо красное?',
          speak: true,
        );
        await api.waitEvents(2);
        api.delta(1, ' Поздняя старая фраза!');
        await api.finish(1);
        await old.timeout(const Duration(seconds: 2));
        expect(service.state, AssistantState.processing);
        expect(service.messages.last.pending, isTrue);
        expect(service.lastTroikaText, isEmpty);
        expect(api.speechRequests, 0);
        api.delta(2, 'Новый синтетический ответ.');
        await api.finish(2);
        await current.timeout(const Duration(seconds: 2));
        expect(service.lastTroikaText, 'Новый синтетический ответ.');
        expect(service.messages.last.text, 'Новый синтетический ответ.');
        expect(service.state, AssistantState.idle);
        expect(api.speechRequests, 1);
        expect(api.stops, ['run_1']);
      }, () => api.client);
    } finally {
      service.dispose();
      await api.dispose();
    }
  });

  test(
    'Stop before run ID stops late owned run without subscribing SSE',
    () async {
      final api = _Api(holdStart: true), service = assistant();
      try {
        await http.runWithClient(() async {
          final turn = service.sendTextQuery(
            'Почему у дневного неба синий цвет?',
            speak: true,
          );
          await api.firstStart.future.timeout(const Duration(seconds: 2));
          await service.interrupt();
          expect(service.state, AssistantState.idle);
          api.releaseStart.complete();
          await turn.timeout(const Duration(seconds: 2));
          expect(api.stops, ['run_1']);
          expect(api.events, isEmpty);
          expect(api.speechRequests, 0);
          expect(service.lastTroikaText, isEmpty);
        }, () => api.client);
      } finally {
        service.dispose();
        await api.dispose();
      }
    },
  );

  test(
    'Stop invalidates before native await and preserves a newer query',
    () async {
      final native = Completer<void>();
      mock('com.troika.hermes/background', (call) async {
        if (call.method == 'interruptTts') await native.future;
        return call.method == 'getRefreshToken'
            ? 'trk_refresh_synthetic'
            : null;
      });
      final api = _Api(), service = assistant();
      try {
        await http.runWithClient(() async {
          final old = service.sendTextQuery(
            'Почему у дневного неба синий цвет?',
            speak: true,
          );
          await api.waitEvents(1);
          final stopping = service.interrupt();
          expect(service.state, AssistantState.idle);
          final current = service.sendTextQuery('Почему вечером небо красное?');
          await api.waitEvents(2);
          native.complete();
          await stopping;
          expect(service.state, AssistantState.processing);
          api.delta(1, 'Поздний старый ответ!');
          await api.finish(1);
          await old;
          expect(service.messages.last.pending, isTrue);
          api.delta(2, 'Новый синтетический текст.');
          await api.finish(2);
          await current;
          expect(service.lastTroikaText, 'Новый синтетический текст.');
          expect(api.speechRequests, 0);
          expect(api.stops, ['run_1']);
        }, () => api.client);
      } finally {
        if (!native.isCompleted) native.complete();
        service.dispose();
        await api.dispose();
      }
    },
  );

  test(
    'late old Stop failure cannot overwrite a newer completed result',
    () async {
      final api = _Api(holdStop: true)..stopStatus = 503;
      final service = assistant();
      try {
        await http.runWithClient(() async {
          final old = service.sendTextQuery(
            'Почему у дневного неба синий цвет?',
          );
          await api.waitEvents(1);
          final current = service.sendTextQuery('Почему вечером небо красное?');
          await api.waitEvents(2);
          await api.stopEntered.future.timeout(const Duration(seconds: 1));
          api.delta(1, 'Поздний старый текст!');
          await api.finish(1);
          await old;
          api.delta(2, 'Новый синтетический результат.');
          await api.finish(2);
          await current;
          final errorBefore = service.errorMessage;
          api.releaseStop.complete();
          await Future<void>.delayed(const Duration(milliseconds: 20));
          expect(service.errorMessage, errorBefore);
          expect(service.lastTroikaText, 'Новый синтетический результат.');
          expect(service.state, AssistantState.idle);
        }, () => api.client);
      } finally {
        service.dispose();
        await api.dispose();
      }
    },
  );

  for (final interruption in ['Stop', 'new query']) {
    test(
      '$interruption denies pending approval without stale voice or UI',
      () async {
        final api = _Api(), service = assistant();
        try {
          await http.runWithClient(() async {
            final old = service.sendTextQuery(
              'Почему у дневного неба синий цвет?',
              speak: true,
            );
            await api.waitEvents(1);
            api.approval(1);
            for (
              var index = 0;
              index < 100 && service.pendingApproval == null;
              index++
            ) {
              await Future<void>.delayed(const Duration(milliseconds: 10));
            }
            expect(service.pendingApproval, isNotNull);
            Future<void>? current;
            if (interruption == 'Stop') {
              await service.interrupt();
            } else {
              current = service.sendTextQuery('Почему вечером небо красное?');
              await api.waitEvents(2);
            }
            service.resolvePendingApproval('once');
            await api.approvalEntered.future.timeout(
              const Duration(seconds: 2),
            );
            expect(api.approvalChoices, ['deny']);
            expect(service.pendingApproval, isNull);
            api.delta(1, 'Поздняя старая фраза!');
            await api.finish(1);
            await old.timeout(const Duration(seconds: 2));
            expect(api.speechRequests, 0);
            expect(
              service.state,
              interruption == 'Stop'
                  ? AssistantState.idle
                  : AssistantState.processing,
            );
            if (current != null) {
              api.delta(2, 'Новый синтетический результат.');
              await api.finish(2);
              await current;
              expect(service.lastTroikaText, 'Новый синтетический результат.');
            }
          }, () => api.client);
        } finally {
          service.dispose();
          await api.dispose();
        }
      },
    );
  }

  for (final transition in [
    'logout',
    'owner',
    'endpoint',
    'credential',
    'dispose',
  ]) {
    test(
      '$transition fences a late run ID without redirecting Stop credentials',
      () async {
        final api = _Api(holdStart: true), service = assistant();
        try {
          await http.runWithClient(() async {
            final turn = service.sendTextQuery(
              'Почему у дневного неба синий цвет?',
              speak: true,
            );
            await api.firstStart.future.timeout(const Duration(seconds: 2));
            switch (transition) {
              case 'logout':
                await TroikaConfig.signOut();
              case 'owner':
                await TroikaConfig.saveAccount(
                  email: 'other@example.invalid',
                  token: 'trk_live_other',
                  homeSessionId: 'ses_other',
                );
              case 'endpoint':
                TroikaConfig.serverUrl = 'https://other.example.invalid';
              case 'credential':
                TroikaConfig.apiKey = 'trk_live_replaced';
              case 'dispose':
                service.dispose();
            }
            api.releaseStart.complete();
            await turn.timeout(const Duration(seconds: 2));
            expect(api.stops, transition == 'dispose' ? ['run_1'] : isEmpty);
            expect(api.events, isEmpty);
            expect(api.speechRequests, 0);
            expect(service.lastTroikaText, isEmpty);
          }, () => api.client);
        } finally {
          service.dispose();
          await api.dispose();
        }
      },
    );
  }

  test(
    'same-owner token refresh preserves pending request and speech',
    () async {
      final api = _Api(holdStart: true), service = assistant();
      try {
        await http.runWithClient(() async {
          final turn = service.sendTextQuery(
            'Почему у дневного неба синий цвет?',
            speak: true,
          );
          await api.firstStart.future.timeout(const Duration(seconds: 2));
          await TroikaConfig.saveAccount(
            email: TroikaConfig.accountEmail,
            token: 'trk_live_refreshed',
            homeSessionId: TroikaConfig.sessionId,
          );
          api.releaseStart.complete();
          await api.waitEvents(1);
          api.delta(1, 'Синтетический ответ после обновления.');
          await api.finish(1);
          await turn.timeout(const Duration(seconds: 2));
          expect(
            service.lastTroikaText,
            'Синтетический ответ после обновления.',
          );
          expect(api.speechRequests, 1);
          expect(api.stops, isEmpty);
        }, () => api.client);
      } finally {
        service.dispose();
        await api.dispose();
      }
    },
  );

  test(
    'late history cannot overwrite a newer completed conversation',
    () async {
      final api = _Api(holdHistory: true)
        ..history = [
          {'role': 'assistant', 'content': 'Старый синтетический архив'},
        ];
      final service = assistant();
      try {
        await http.runWithClient(() async {
          final oldHistory = service.loadHistory();
          await api.historyEntered.future;
          final turn = service.sendTextQuery('Почему вечером небо красное?');
          await api.waitEvents(1);
          api.delta(1, 'Актуальный синтетический ответ');
          await api.finish(1);
          await turn;
          api.releaseHistory.complete();
          await oldHistory;
          expect(service.messages.map((m) => m.text), [
            'Почему вечером небо красное?',
            'Актуальный синтетический ответ',
          ]);
        }, () => api.client);
      } finally {
        service.dispose();
        await api.dispose();
      }
    },
  );

  test(
    'a newer history snapshot wins over an older simultaneous load',
    () async {
      final api = _Api(holdHistory: true)
        ..history = [
          {'role': 'assistant', 'content': 'Старый архив'},
        ];
      final service = assistant();
      try {
        await http.runWithClient(() async {
          final oldHistory = service.loadHistory();
          await api.historyEntered.future;
          api.history = [
            {'role': 'assistant', 'content': 'Новый архив'},
          ];
          await service.loadHistory();
          api.releaseHistory.complete();
          await oldHistory;
          expect(service.messages.single.text, 'Новый архив');
        }, () => api.client);
      } finally {
        service.dispose();
        await api.dispose();
      }
    },
  );

  test(
    'identity replacement clears old text, result and next-turn context',
    () async {
      final api = _Api()
        ..history = [
          {'role': 'assistant', 'content': 'Синтетический контекст A'},
        ];
      final service = assistant();
      try {
        await http.runWithClient(() async {
          await service.loadHistory();
          final first = service.sendTextQuery(
            'Почему у дневного неба синий цвет?',
          );
          await api.waitEvents(1);
          api.delta(1, 'Синтетический ответ A');
          await api.finish(1);
          await first;
          expect(service.lastResult, isNotNull);
          await TroikaConfig.saveAccount(
            email: 'other@example.invalid',
            token: 'trk_live_other',
            homeSessionId: 'ses_other',
            replaceIdentity: true,
          );
          expect(service.messages, isEmpty);
          expect(service.lastUserText, isEmpty);
          expect(service.lastTroikaText, isEmpty);
          expect(service.lastResult, isNull);
          final second = service.sendTextQuery('Почему вечером небо красное?');
          await api.waitEvents(2);
          expect(api.startBodies.last['conversation_history'], isNull);
          api.delta(2, 'Синтетический ответ B');
          await api.finish(2);
          await second;
        }, () => api.client);
      } finally {
        service.dispose();
        await api.dispose();
      }
    },
  );

  for (final terminal in ['run.failed', 'run.cancelled', null]) {
    test(
      'partial text with terminal $terminal never becomes a successful result',
      () async {
        final api = _Api(), service = assistant();
        try {
          await http.runWithClient(() async {
            final turn = service.sendTextQuery(
              'Почему у дневного неба синий цвет?',
            );
            await api.waitEvents(1);
            api.delta(1, 'Незавершённая синтетическая часть');
            await api.terminate(1, terminal);
            await turn.timeout(const Duration(seconds: 2));
            expect(service.state, AssistantState.error);
            expect(service.lastResult, isNull);
            expect(service.lastTroikaText, isEmpty);
            expect(service.messages.where((m) => !m.isUser), isEmpty);
            expect(service.errorMessage, isNotEmpty);
          }, () => api.client);
        } finally {
          service.dispose();
          await api.dispose();
        }
      },
    );
  }

  test(
    'EOF recovers canonical output only after completed server status',
    () async {
      final api = _Api()
        ..runStatus = {
          'status': 'completed',
          'output': 'Полный канонический ответ',
        };
      final service = assistant();
      try {
        await http.runWithClient(() async {
          final turn = service.sendTextQuery('Почему вечером небо красное?');
          await api.waitEvents(1);
          api.delta(1, 'Обрезанная часть');
          await api.terminate(1, null);
          await turn;
          expect(service.lastTroikaText, 'Полный канонический ответ');
          expect(service.state, AssistantState.idle);
        }, () => api.client);
      } finally {
        service.dispose();
        await api.dispose();
      }
    },
  );

  test(
    'an unscoped legacy result is never restored for another account',
    () async {
      await TroikaConfig.signOut();
      final prefs = await SharedPreferences.getInstance();
      final legacy = jsonEncode({
        'kind': 'file',
        'title': 'Синтетический документ прежнего владельца',
        'summary': 'Синтетические данные',
        'resource_id': 'legacy',
      });
      await prefs.setString('troika_last_action_result', legacy);
      final api = _Api(), service = assistant();
      try {
        await http.runWithClient(() async {
          await service.init();
          await service.loadHistory();
          expect(service.lastResult, isNull);
          expect(prefs.getString('troika_last_action_result'), legacy);
        }, () => api.client);
      } finally {
        service.dispose();
        await api.dispose();
      }
    },
  );
}
