import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';

import 'troika_api_service.dart';

class ReminderDeliveryStatus {
  final bool notificationsEnabled;
  final bool exactAlarms;
  const ReminderDeliveryStatus(this.notificationsEnabled, this.exactAlarms);
}

/// Sync server-owned reminder IDs to Android's persistent alarm scheduler.
/// A failed fetch preserves the last successful snapshot for offline delivery.
class ReminderDeliveryService {
  ReminderDeliveryService({
    Future<Map<String, dynamic>> Function()? fetch,
    MethodChannel? channel,
    bool? supported,
  })  : _fetch = fetch ?? TroikaApiService().reminderDeliveryPlan,
        _channel =
            channel ?? const MethodChannel('com.troika.hermes/background'),
        _supported = supported ?? Platform.isAndroid;

  static final instance = ReminderDeliveryService();
  final Future<Map<String, dynamic>> Function() _fetch;
  final MethodChannel _channel;
  final bool _supported;
  Future<ReminderDeliveryStatus?>? _inFlight;
  int _generation = 0;

  Future<ReminderDeliveryStatus?> sync() async {
    if (!_supported) return null;
    if (_inFlight != null) return _inFlight;
    final operation = _sync();
    _inFlight = operation;
    try {
      return await operation;
    } finally {
      _inFlight = null;
    }
  }

  Future<ReminderDeliveryStatus?> _sync() async {
    final generation = _generation;
    try {
      final snapshot = await _fetch();
      if (generation != _generation) return null;
      final status = await _channel.invokeMapMethod<String, dynamic>(
          'syncReminders', {'snapshot': jsonEncode(snapshot)});
      return ReminderDeliveryStatus(status?['notifications_enabled'] == true,
          status?['exact_alarms'] == true);
    } on TroikaApiException catch (error) {
      if (error.statusCode == 401) await clear();
      return null;
    } catch (_) {
      return null;
    }
  }

  Future<void> clear() async {
    _generation++;
    if (!_supported) return;
    try {
      await _channel.invokeMethod<void>('clearReminders');
    } catch (_) {}
  }

  Future<void> requestExactAlarms() async {
    if (!_supported) return;
    await _channel.invokeMethod<void>('requestExactReminderAlarms');
  }
}
