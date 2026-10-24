import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/services/assistant_result.dart';
import 'package:troika_assistant/services/assistant_service.dart';
import 'package:troika_assistant/services/reminder_delivery_service.dart';
import 'package:troika_assistant/services/streaming_speech.dart';

const _answer = 'Синтетический ответ.';
const _background = MethodChannel('com.troika.hermes/background');

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  final channels = <MethodChannel>[];
  var reminderInstalls = 0;

  void mock(
    MethodChannel channel,
    Future<Object?> Function(MethodCall) handler,
  ) {
    channels.add(channel);
    messenger.setMockMethodCallHandler(channel, handler);
  }

  test(
    'short spoken reply reaches TTS while reminder GET is pending',
    () async {
      final pending = Completer<http.Response>();
      final requested = Completer<void>();
      final speechRequested = Completer<void>();
      final assistant = AssistantService(
        replyDelivery: ReminderDeliveryService(supported: true),
      );
      addTearDown(() async {
        assistant.dispose();
        await Future<void>.delayed(Duration.zero);
      });
      await http.runWithClient(() async {
        final turn = assistant.sendTextQuery(
          'Почему у дневного неба синий цвет?',
          speak: true,
        );
        try {
          await requested.future.timeout(const Duration(seconds: 2));
          await speechRequested.future.timeout(const Duration(seconds: 2));
          await turn.timeout(const Duration(seconds: 2));
          expect(pending.isCompleted, isFalse);
          expect(assistant.state, AssistantState.idle);
          expect(assistant.lastTroikaText, _answer);
          expect(assistant.messages.last.pending, isFalse);
          expect(assistant.messages.last.text, _answer);
          expect(
            assistant.errorMessage,
            'Ответ получен. Голос сейчас недоступен.',
          );
        } finally {
          pending.complete(
            http.Response(
              jsonEncode({'owner_id': 'usr_synthetic', 'reminders': []}),
              200,
            ),
          );
          await turn;
          await Future<void>.delayed(Duration.zero);
        }
        expect(reminderInstalls, 1);
      }, () => _client(pending, requested, speechRequested: speechRequested));
    },
    skip: !(Platform.isWindows || Platform.isAndroid),
  );

  setUp(() async {
    reminderInstalls = 0;
    SharedPreferences.setMockInitialValues({
      'troika_server_url': 'https://reply.example.invalid',
      'troika_account_email': 'synthetic@example.invalid',
      'troika_api_key': 'trk_live_synthetic',
      'troika_access_token_expires_at': DateTime.now()
          .add(const Duration(days: 1))
          .millisecondsSinceEpoch,
      'troika_session_id': 'ses_synthetic',
      'troika_session_key': 'ses_synthetic',
      'troika_local_mode': 'normal',
      'troika_wake_word_enabled': false,
    });
    mock(_background, (call) async {
      if (call.method == 'getRefreshToken') return 'trk_refresh_synthetic';
      if (call.method == 'ensureFreshAccountSession') return true;
      if (call.method == 'syncReminders') {
        reminderInstalls++;
        return {'notifications_enabled': true, 'exact_alarms': true};
      }
      return null;
    });
    for (final name in [
      'com.llfbandit.record/messages',
      'flutter_tts',
      'xyz.luan/audioplayers.global',
      'xyz.luan/audioplayers.global/events',
    ]) {
      mock(MethodChannel(name), (_) async => null);
    }
    mock(const MethodChannel('xyz.luan/audioplayers'), (call) async {
      if (call.method == 'create') {
        final player = (call.arguments as Map)['playerId'];
        mock(
          MethodChannel('xyz.luan/audioplayers/events/$player'),
          (_) async => null,
        );
      }
      return null;
    });
    await TroikaConfig.init();
  });

  tearDown(() {
    for (final channel in channels) {
      messenger.setMockMethodCallHandler(channel, null);
    }
    channels.clear();
  });

  for (final reminderStatus in [200, 503]) {
    test(
      'ordinary reply completes while reminder GET is pending ($reminderStatus)',
      () async {
        final pending = Completer<http.Response>();
        final requested = Completer<void>();
        final assistant = AssistantService(
          replyDelivery: ReminderDeliveryService(supported: true),
        );
        addTearDown(() async {
          assistant.dispose();
          await Future<void>.delayed(Duration.zero);
        });
        await http.runWithClient(() async {
          final turn = assistant.sendTextQuery(
            'Почему у дневного неба синий цвет?',
            speak: false,
          );
          try {
            await requested.future.timeout(const Duration(seconds: 2));
            await Future<void>.delayed(Duration.zero);
            expect(pending.isCompleted, isFalse);
            expect(assistant.state, AssistantState.idle);
            expect(assistant.lastTroikaText, _answer);
            expect(assistant.messages.last.pending, isFalse);
            expect(assistant.messages.last.text, _answer);
            expect(assistant.errorMessage, isEmpty);
          } finally {
            pending.complete(
              http.Response(
                jsonEncode({'owner_id': 'usr_synthetic', 'reminders': []}),
                reminderStatus,
              ),
            );
            await turn;
            await Future<void>.delayed(Duration.zero);
          }
          expect(assistant.state, AssistantState.idle);
          expect(assistant.lastTroikaText, _answer);
          expect(assistant.errorMessage, isEmpty);
          expect(reminderInstalls, reminderStatus == 200 ? 1 : 0);
        }, () => _client(pending, requested));
      },
      skip: !(Platform.isWindows || Platform.isAndroid),
    );
  }

  test(
    'reminder receipt still waits for delivery before completing the turn',
    () async {
      final pending = Completer<http.Response>();
      final requested = Completer<void>();
      final assistant = AssistantService(
        replyDelivery: ReminderDeliveryService(supported: true),
      );
      addTearDown(() async {
        assistant.dispose();
        await Future<void>.delayed(Duration.zero);
      });
      var completed = false;
      await http.runWithClient(() async {
        final turn = assistant
            .sendTextQuery('Напомни о синтетической проверке.', speak: false)
            .then((_) => completed = true);
        try {
          await requested.future.timeout(const Duration(seconds: 2));
          await Future<void>.delayed(Duration.zero);
          expect(completed, isFalse);
          expect(assistant.state, AssistantState.processing);
          expect(assistant.messages.last.pending, isTrue);
          expect(reminderInstalls, 0);
        } finally {
          pending.complete(
            http.Response(
              jsonEncode({'owner_id': 'usr_synthetic', 'reminders': []}),
              200,
            ),
          );
          await turn;
        }
        expect(reminderInstalls, 1);
        expect(assistant.state, AssistantState.idle);
        expect(assistant.messages.last.pending, isFalse);
        expect(assistant.lastTroikaText, _answer);
        expect(assistant.lastResult?.kind, AssistantResultKind.saved);
      }, () => _client(pending, requested, reminder: true));
    },
    skip: !(Platform.isWindows || Platform.isAndroid),
  );

  test(
    'finish flushes a short reply ending with a period exactly once',
    () async {
      final prepared = <String>[];
      final played = <String>[];
      final queue = StreamingSpeech<String>(
        prepare: (text) async {
          prepared.add(text);
          return text;
        },
        play: (text) async {
          played.add(text);
        },
        discard: (_) {},
      );
      queue.add(_answer);
      await Future<void>.delayed(Duration.zero);
      expect(prepared, isEmpty);
      await queue.finish();
      await queue.finish();
      expect(prepared, [_answer]);
      expect(played, [_answer]);
    },
  );

  test('cancel never flushes a buffered short reply into speech', () async {
    final prepared = <String>[];
    final played = <String>[];
    final queue = StreamingSpeech<String>(
      prepare: (text) async {
        prepared.add(text);
        return text;
      },
      play: (text) async {
        played.add(text);
      },
      discard: (_) {},
    );
    queue.add(_answer);
    queue.cancel();
    await queue.finish();
    expect(prepared, isEmpty);
    expect(played, isEmpty);
  });
}

http.Client _client(
  Completer<http.Response> reminderResponse,
  Completer<void> reminderRequested, {
  bool reminder = false,
  Completer<void>? speechRequested,
}) => MockClient((request) async {
  expect(request.url.host, 'reply.example.invalid');
  switch (request.url.path) {
    case '/v1/capabilities':
      return http.Response('{"features":{"device_file_delivery":true}}', 200);
    case '/v1/runs':
      expect(request.method, 'POST');
      return http.Response('{"run_id":"run_synthetic"}', 202);
    case '/v1/runs/run_synthetic/events':
      final events = <Map<String, dynamic>>[
        if (reminder)
          {
            'event': 'tool.completed',
            'tool': 'troika_reminder',
            'result': {
              'kind': 'reminder',
              'id': 'reminder_synthetic',
              'title': 'Синтетическая проверка',
            },
          },
        {'event': 'message.delta', 'delta': _answer},
        {'event': 'run.completed'},
      ];
      return http.Response(
        events.map((event) => 'data: ${jsonEncode(event)}\n\n').join(),
        200,
        headers: {'content-type': 'text/event-stream; charset=utf-8'},
      );
    case '/v1/assistant/reminders':
      expect(request.method, 'GET');
      expect(reminderRequested.isCompleted, isFalse);
      reminderRequested.complete();
      return reminderResponse.future;
    case '/v1/audio/speech':
      expect(request.method, 'POST');
      expect(jsonDecode(request.body)['input'], _answer);
      expect(speechRequested, isNotNull);
      speechRequested!.complete();
      return http.Response('{}', 503);
    default:
      throw StateError('Unexpected synthetic route: ${request.url.path}');
  }
});
