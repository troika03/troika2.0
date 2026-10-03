import 'dart:async';
import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:troika_assistant/services/reminder_delivery_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('reminder-test');
  final calls = <MethodCall>[];
  setUp(() {
    calls.clear();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      calls.add(call);
      return call.method == 'syncReminders'
          ? {'notifications_enabled': true, 'exact_alarms': true}
          : null;
    });
  });
  tearDown(() => TestDefaultBinaryMessengerBinding
      .instance.defaultBinaryMessenger
      .setMockMethodCallHandler(channel, null));

  test('sync preserves account ownership and complete server snapshot',
      () async {
    final snapshot = {
      'owner_id': 'usr_test',
      'reminders_enabled': true,
      'reminders': [
        {'id': 'msg_test', 'title': 'Вода', 'fire_at': 120}
      ]
    };
    final service = ReminderDeliveryService(
        fetch: () async => snapshot, channel: channel, supported: true);
    final status = await service.sync();
    expect(status?.exactAlarms, true);
    expect(jsonDecode(calls.single.arguments['snapshot']), snapshot);
  });

  test('offline fetch failure does not erase scheduled reminders', () async {
    final service = ReminderDeliveryService(
        fetch: () async => throw Exception('offline'),
        channel: channel,
        supported: true);
    expect(await service.sync(), null);
    expect(calls, isEmpty);
  });

  test('logout invalidates an in-flight snapshot before it can restore alarms',
      () async {
    final snapshot = Completer<Map<String, dynamic>>();
    final service = ReminderDeliveryService(
        fetch: () => snapshot.future, channel: channel, supported: true);
    final pending = service.sync();
    await service.clear();
    snapshot.complete({'owner_id': 'old-owner', 'reminders': []});
    expect(await pending, null);
    expect(calls.map((call) => call.method), ['clearReminders']);
  });
}
