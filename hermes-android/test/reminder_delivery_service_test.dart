import 'dart:async';
import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:troika_assistant/services/reminder_delivery_service.dart';
import 'package:troika_assistant/services/troika_api_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('reminder-test');
  final calls = <MethodCall>[];
  List<String> missing = [];
  setUp(() {
    calls.clear();
    missing = [];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          calls.add(call);
          return call.method == 'syncReminders'
              ? {
                  'notifications_enabled': true,
                  'exact_alarms': true,
                  'voice_missing': missing,
                }
              : null;
        });
  });
  tearDown(
    () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null),
  );

  test(
    'sync preserves account ownership and complete server snapshot',
    () async {
      final snapshot = {
        'owner_id': 'usr_test',
        'reminders_enabled': true,
        'reminders': [
          {'id': 'msg_test', 'title': 'Вода', 'fire_at': 120},
        ],
      };
      final service = ReminderDeliveryService(
        fetch: () async => snapshot,
        channel: channel,
        supported: true,
      );
      final status = await service.sync();
      expect(status?.exactAlarms, true);
      expect(jsonDecode(calls.single.arguments['snapshot']), snapshot);
    },
  );

  test('offline fetch failure does not erase scheduled reminders', () async {
    final service = ReminderDeliveryService(
      fetch: () async => throw Exception('offline'),
      channel: channel,
      supported: true,
    );
    expect(await service.sync(), null);
    expect(calls, isEmpty);
  });

  test('quiet-hour snapshot waits for the device time-zone update', () async {
    final timezone = Completer<bool>();
    var fetches = 0;
    final service = ReminderDeliveryService(
      fetch: () async {
        fetches++;
        return {'owner_id': 'usr_test', 'reminders': []};
      },
      syncTimeZone: () => timezone.future,
      channel: channel,
      supported: true,
    );
    final pending = service.syncWithDeviceTimeZone();
    await Future<void>.delayed(Duration.zero);
    expect(fetches, 0);
    timezone.complete(true);
    expect((await pending)?.notificationsEnabled, true);
    expect(fetches, 1);
  });

  test('logout while updating time zone cannot reinstall a schedule', () async {
    final timezone = Completer<bool>();
    var fetches = 0;
    final service = ReminderDeliveryService(
      fetch: () async {
        fetches++;
        return {};
      },
      syncTimeZone: () => timezone.future,
      channel: channel,
      supported: true,
    );
    final pending = service.syncWithDeviceTimeZone();
    await service.clear();
    timezone.complete(true);
    expect(await pending, null);
    expect(fetches, 0);
    expect(calls.map((call) => call.method), ['clearReminders']);
  });

  test(
    'time-zone update fetches again after an older snapshot completes',
    () async {
      final old = Completer<Map<String, dynamic>>();
      var fetches = 0;
      final service = ReminderDeliveryService(
        fetch: () => ++fetches == 1
            ? old.future
            : Future.value({'owner_id': 'usr_test', 'reminders': []}),
        syncTimeZone: () async => true,
        channel: channel,
        supported: true,
      );
      final first = service.sync();
      final updated = service.syncWithDeviceTimeZone();
      await Future<void>.delayed(Duration.zero);
      expect(fetches, 1);
      old.complete({'owner_id': 'usr_test', 'reminders': []});
      await first;
      await updated;
      expect(fetches, 2);
    },
  );

  for (final disabled in [false, true]) {
    test(
      'late prepared voice is rejected after ${disabled ? 'disable' : 'retract'}',
      () async {
        missing = ['msg_test'];
        final audio = Completer<List<int>>();
        final preparing = Completer<void>();
        var first = true;
        final service = ReminderDeliveryService(
          fetch: () async => {
            'owner_id': 'usr_test',
            'reminders_enabled': !disabled || first,
            'reminders': first
                ? [
                    {
                      'id': 'msg_test',
                      'body': 'Synthetic test',
                      'available_at': 'test',
                    },
                  ]
                : [],
          },
          channel: channel,
          supported: true,
          naturalVoice: true,
          prepareSpeech: (_) {
            preparing.complete();
            return audio.future;
          },
        );
        await service.sync();
        await preparing.future;
        first = false;
        await service.sync(refresh: true);
        audio.complete([1, 2, 3]);
        await Future<void>.delayed(Duration.zero);
        expect(calls.map((call) => call.method), [
          'syncReminders',
          'syncReminders',
        ]);
      },
    );
  }

  test(
    'stale authentication failure cannot clear a newer account schedule',
    () async {
      final old = Completer<Map<String, dynamic>>();
      final service = ReminderDeliveryService(
        fetch: () => old.future,
        channel: channel,
        supported: true,
      );
      final pending = service.sync();
      await service.clear();
      old.completeError(TroikaApiException('expired', statusCode: 401));
      await pending;
      expect(calls.map((call) => call.method), ['clearReminders']);
    },
  );

  test(
    'post-write refresh waits for an older snapshot and fetches again',
    () async {
      final old = Completer<Map<String, dynamic>>();
      var fetches = 0;
      final service = ReminderDeliveryService(
        fetch: () {
          fetches++;
          return fetches == 1
              ? old.future
              : Future.value({
                  'owner_id': 'usr_test',
                  'reminders': ['new'],
                });
        },
        channel: channel,
        supported: true,
      );
      final first = service.sync();
      final afterWrite = service.sync(refresh: true);
      old.complete({'owner_id': 'usr_test', 'reminders': []});
      await first;
      await afterWrite;
      expect(fetches, 2);
      expect(jsonDecode(calls.last.arguments['snapshot'])['reminders'], [
        'new',
      ]);
    },
  );

  test(
    'Android post-write refresh rejects an older native snapshot ticket',
    () async {
      final old = Completer<Map<String, dynamic>>();
      final entered = Completer<void>();
      final installed = <int>[];
      var latestTicket = 0;
      var fetches = 0;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (call) async {
            if (call.method == 'beginReminderSync') return ++latestTicket;
            if (call.method == 'syncReminders') {
              final ticket = call.arguments['ticket'] as int;
              if (ticket != latestTicket) return null;
              installed.add(ticket);
              return {'notifications_enabled': true, 'exact_alarms': true};
            }
            return null;
          });
      final service = ReminderDeliveryService(
        fetch: () {
          fetches++;
          if (fetches == 1) {
            entered.complete();
            return old.future;
          }
          return Future.value({'owner_id': 'usr_test', 'reminders': []});
        },
        channel: channel,
        supported: true,
        nativeSyncTickets: true,
      );
      final first = service.sync();
      await entered.future;
      final afterWrite = service.sync(refresh: true);
      await Future<void>.delayed(Duration.zero);
      old.complete({
        'owner_id': 'usr_test',
        'reminders': ['cancelled'],
      });
      expect(await first, null);
      expect((await afterWrite)?.exactAlarms, true);
      expect(fetches, 2);
      expect(installed, [latestTicket]);
    },
  );

  test(
    'logout cancels a queued refresh as well as the running fetch',
    () async {
      final old = Completer<Map<String, dynamic>>();
      var fetches = 0;
      final service = ReminderDeliveryService(
        fetch: () {
          fetches++;
          return old.future;
        },
        channel: channel,
        supported: true,
      );
      final first = service.sync();
      final queued = service.sync(refresh: true);
      await service.clear();
      old.complete({'owner_id': 'old-owner', 'reminders': []});
      expect(await first, null);
      expect(await queued, null);
      expect(fetches, 1);
      expect(calls.map((call) => call.method), ['clearReminders']);
    },
  );

  test(
    'logout invalidates an in-flight snapshot before it can restore alarms',
    () async {
      final snapshot = Completer<Map<String, dynamic>>();
      final service = ReminderDeliveryService(
        fetch: () => snapshot.future,
        channel: channel,
        supported: true,
      );
      final pending = service.sync();
      await service.clear();
      snapshot.complete({'owner_id': 'old-owner', 'reminders': []});
      expect(await pending, null);
      expect(calls.map((call) => call.method), ['clearReminders']);
    },
  );

  test(
    'voice preparation never delays scheduling and logout rejects its result',
    () async {
      missing = ['msg_test'];
      final audio = Completer<List<int>>();
      final preparing = Completer<void>();
      final service = ReminderDeliveryService(
        fetch: () async => {
          'owner_id': 'usr_test',
          'reminders_enabled': true,
          'reminders': [
            {
              'id': 'msg_test',
              'body': 'Synthetic test',
              'available_at': 'test',
            },
          ],
        },
        channel: channel,
        supported: true,
        naturalVoice: true,
        prepareSpeech: (_) {
          preparing.complete();
          return audio.future;
        },
      );
      expect((await service.sync())?.notificationsEnabled, true);
      await preparing.future;
      expect(calls.map((call) => call.method), ['syncReminders']);
      await service.clear();
      audio.complete([1, 2, 3]);
      await Future<void>.delayed(Duration.zero);
      expect(calls.map((call) => call.method), [
        'syncReminders',
        'clearReminders',
      ]);
    },
  );

  test(
    'prepared voice preserves owner, deadline and wording across duplicate sync',
    () async {
      missing = ['msg_test'];
      final audio = Completer<List<int>>();
      var preparations = 0;
      var polls = 0;
      final service = ReminderDeliveryService(
        fetch: () async => {
          'owner_id': 'usr_test',
          'reminders_enabled': true,
          'reminders': [
            {
              'id': 'msg_test',
              'body': 'Synthetic test',
              'available_at': 'test',
              'fire_at': ++polls,
            },
          ],
        },
        channel: channel,
        supported: true,
        naturalVoice: true,
        prepareSpeech: (_) {
          preparations++;
          return audio.future;
        },
      );
      await service.sync();
      await service.sync();
      expect(preparations, 1);
      audio.complete([1, 2, 3]);
      await Future<void>.delayed(Duration.zero);
      final clip = jsonDecode(calls.last.arguments['snapshot']);
      expect(calls.last.method, 'cacheReminderSpeech');
      expect(clip, {
        'owner_id': 'usr_test',
        'id': 'msg_test',
        'available_at': 'test',
        'body': 'Synthetic test',
        'audio': base64Encode([1, 2, 3]),
      });
    },
  );
}
