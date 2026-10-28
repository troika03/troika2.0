import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/screens/assistant_hub_screen.dart';
import 'package:troika_assistant/services/reminder_delivery_service.dart';

const _background = MethodChannel('com.troika.hermes/background');
const _owner = 'usr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final events = <String>[];
  var taskStatus = 'open';
  var read = false;

  Map<String, dynamic> task() => {
    'id': 'tsk_synthetic',
    'project_id': 'prj_synthetic',
    'title': 'Проверить задачу',
    'status': taskStatus,
  };

  http.Response reply(Object body) => http.Response(
    jsonEncode(body),
    200,
    headers: {'content-type': 'application/json; charset=utf-8'},
  );

  MockClient client() => MockClient((request) async {
    final path = request.url.path;
    if (path == '/v1/assistant/reminders') {
      events.add('snapshot');
      return reply({
        'owner_id': _owner,
        'reminders_enabled': true,
        'reminders': const [],
      });
    }
    if (path == '/v1/assistant/tasks' && request.method == 'POST') {
      events.add('create');
      return reply({'task': task()});
    }
    if (path == '/v1/assistant/tasks/tsk_synthetic' &&
        request.method == 'PATCH') {
      taskStatus = jsonDecode(request.body)['status'] as String;
      events.add(taskStatus);
      return reply({'task': task()});
    }
    if (path == '/v1/assistant/inbox/msg_synthetic/read') {
      read = true;
      events.add('read');
      return reply({});
    }
    if (path == '/v1/assistant/projects') {
      return reply({
        'projects': [
          {
            'id': 'prj_synthetic',
            'name': 'Синтетический проект',
            'is_active': true,
            'status': 'active',
          },
        ],
      });
    }
    if (path == '/v1/assistant/tasks') {
      return reply({
        'tasks': [task()],
      });
    }
    if (path == '/v1/assistant/inbox') {
      return reply({
        'messages': [
          {
            'id': 'msg_synthetic',
            'kind': 'reminder',
            'title': 'Проверить напоминание',
            'body': 'Синтетическая проверка.',
            'read_at': read ? '2026-10-28T12:00:00Z' : null,
          },
        ],
      });
    }
    if (path == '/v1/notification-preferences') {
      return reply({
        'reminders_enabled': true,
        'proactive_enabled': false,
        'quiet_hours_enabled': false,
        'timezone': 'Europe/Moscow',
        'quiet_start': '22:00',
        'quiet_end': '08:00',
      });
    }
    throw StateError('Unexpected test request: ${request.method} $path');
  });

  setUp(() async {
    events.clear();
    taskStatus = 'open';
    read = false;
    SharedPreferences.setMockInitialValues({
      'troika_server_url': 'https://reminder.example.invalid',
      'troika_account_email': 'synthetic@example.invalid',
      'troika_api_key': 'trk_live_synthetic',
      'troika_access_token_expires_at': DateTime.now()
          .add(const Duration(days: 1))
          .millisecondsSinceEpoch,
      'troika_session_id': 'ses_synthetic',
      'troika_session_key': 'ses_synthetic',
    });
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_background, (call) async {
          if (call.method == 'syncReminders') {
            expect(jsonDecode(call.arguments['snapshot'])['owner_id'], _owner);
            events.add('installed');
            return {'notifications_enabled': true, 'exact_alarms': true};
          }
          if (call.method == 'getRefreshToken') return 'trk_refresh_synthetic';
          if (call.method == 'ensureFreshAccountSession') return true;
          return null;
        });
    await TroikaConfig.init();
  });

  tearDown(
    () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_background, null),
  );

  Future<void> open(WidgetTester tester) async {
    tester.view.physicalSize = const Size(1200, 2200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        home: AssistantHubScreen(
          reminderDelivery: ReminderDeliveryService(
            supported: true,
            naturalVoice: false,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  for (final status in ['completed', 'cancelled']) {
    testWidgets('$status task refreshes the installed reminder snapshot', (
      tester,
    ) async {
      await http.runWithClient(() async {
        await open(tester);
        await tester.tap(find.byTooltip('Изменить статус'));
        await tester.pumpAndSettle();
        await tester.tap(
          find.text(status == 'completed' ? 'Завершена' : 'Отменена'),
        );
        await tester.pumpAndSettle();
        expect(events, [status, 'snapshot', 'installed']);
      }, client);
    });
  }

  testWidgets('reading a reminder retracts its installed snapshot', (
    tester,
  ) async {
    await http.runWithClient(() async {
      await open(tester);
      await tester.tap(find.text('Проверить напоминание'));
      await tester.pumpAndSettle();
      expect(events, ['read', 'snapshot', 'installed']);
    }, client);
  });

  testWidgets(
    'creating a task refreshes reminders after the successful write',
    (tester) async {
      await http.runWithClient(() async {
        await open(tester);
        await tester.tap(find.byIcon(Icons.add_task));
        await tester.pumpAndSettle();
        await tester.enterText(find.byType(TextField).first, 'Новое дело');
        await tester.tap(find.text('Сохранить'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Без срока'));
        await tester.pumpAndSettle();
        expect(events, ['create', 'snapshot', 'installed']);
      }, client);
    },
  );
}
