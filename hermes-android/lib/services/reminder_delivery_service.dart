import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';

import 'troika_api_service.dart';

class ReminderDeliveryStatus {
  final bool notificationsEnabled;
  final bool exactAlarms;
  const ReminderDeliveryStatus(this.notificationsEnabled, this.exactAlarms);
}

/// Sync server-owned reminder IDs to the device's persistent scheduler.
/// A failed fetch preserves the last successful snapshot for offline delivery.
class ReminderDeliveryService {
  ReminderDeliveryService({
    Future<Map<String, dynamic>> Function()? fetch,
    MethodChannel? channel,
    bool? supported,
    bool? naturalVoice,
    Future<List<int>> Function(String)? prepareSpeech,
    Future<bool> Function()? syncTimeZone,
    bool? nativeSyncTickets,
  }) : _fetch = fetch ?? TroikaApiService().reminderDeliveryPlan,
       _channel =
           channel ?? const MethodChannel('com.troika.hermes/background'),
       _supported = supported ?? (Platform.isAndroid || Platform.isWindows),
       _naturalVoice = naturalVoice ?? Platform.isWindows,
       _prepareSpeech = prepareSpeech ?? TroikaApiService().reminderSpeech,
       _syncTimeZone = syncTimeZone ?? TroikaApiService().syncDeviceTimeZone,
       _nativeSyncTickets = nativeSyncTickets ?? Platform.isAndroid;

  static final instance = ReminderDeliveryService();
  final Future<Map<String, dynamic>> Function() _fetch;
  final MethodChannel _channel;
  final bool _supported;
  final bool _naturalVoice;
  final Future<List<int>> Function(String) _prepareSpeech;
  final Future<bool> Function() _syncTimeZone;
  final bool _nativeSyncTickets;
  Future<void> _voiceQueue = Future.value();
  final Set<String> _voicePending = {};
  String? _speechOwner;
  String? _speechSnapshot;
  int _voiceGeneration = 0;
  Future<ReminderDeliveryStatus?>? _inFlight;
  int _generation = 0;

  /// Finish the time-zone update before fetching the server's quiet-hour plan.
  Future<ReminderDeliveryStatus?> syncWithDeviceTimeZone() async {
    if (!_supported) return null;
    final generation = _generation;
    try {
      await _syncTimeZone();
    } catch (_) {
      // A temporary failure preserves the server's last known time zone.
    }
    if (generation != _generation) return null;
    return sync(refresh: true);
  }

  Future<ReminderDeliveryStatus?> sync({bool refresh = false}) async {
    if (!_supported) return null;
    final generation = _generation;
    // A post-write refresh invalidates an older Android fetch before waiting.
    if (refresh && _nativeSyncTickets) {
      try {
        await _channel.invokeMethod<int>('beginReminderSync');
      } catch (_) {
        return null;
      }
      if (generation != _generation) return null;
    }
    while (_inFlight != null) {
      final pending = _inFlight!;
      if (!refresh) return pending;
      await pending;
      if (generation != _generation) return null;
    }
    final operation = _sync();
    _inFlight = operation;
    try {
      return await operation;
    } finally {
      if (identical(_inFlight, operation)) _inFlight = null;
    }
  }

  Future<ReminderDeliveryStatus?> _sync() async {
    final generation = _generation;
    int? ticket;
    try {
      ticket = _nativeSyncTickets
          ? await _channel.invokeMethod<int>('beginReminderSync')
          : null;
      if (generation != _generation || (_nativeSyncTickets && ticket == null)) {
        return null;
      }
      final snapshot = await _fetch();
      if (generation != _generation) return null;
      final status = await _channel.invokeMapMethod<String, dynamic>(
        'syncReminders',
        {
          'snapshot': jsonEncode(snapshot),
          if (_nativeSyncTickets) 'ticket': ticket,
        },
      );
      if (status == null || generation != _generation) return null;
      _invalidateChangedSpeech(snapshot);
      if (_naturalVoice && generation == _generation) {
        _queueSpeech(snapshot, status['voice_missing'], generation);
      }
      return ReminderDeliveryStatus(
        status['notifications_enabled'] == true,
        status['exact_alarms'] == true,
      );
    } on TroikaApiException catch (error) {
      if (error.statusCode == 401 && generation == _generation) {
        if (_nativeSyncTickets) {
          if (ticket != null) {
            try {
              await _channel.invokeMethod<bool>('rejectReminderSync', {
                'ticket': ticket,
              });
            } catch (_) {}
          }
        } else {
          await clear();
        }
      }
      return null;
    } catch (_) {
      return null;
    }
  }

  void _invalidateChangedSpeech(Map<String, dynamic> snapshot) {
    final reminders =
        (snapshot['reminders'] as List? ?? const [])
            .whereType<Map>()
            .map(
              (row) => {
                'id': row['id'],
                'available_at': row['available_at'],
                'text': row['body'] ?? row['title'],
              },
            )
            .toList()
          ..sort((a, b) => a['id'].toString().compareTo(b['id'].toString()));
    final signature = jsonEncode({
      'owner_id': snapshot['owner_id'],
      'reminders_enabled': snapshot['reminders_enabled'],
      'reminders': reminders,
    });
    if (_speechSnapshot != signature) {
      _speechSnapshot = signature;
      _voiceGeneration++;
    }
  }

  void _queueSpeech(
    Map<String, dynamic> snapshot,
    dynamic missing,
    int generation,
  ) {
    if (missing is! List || snapshot['reminders_enabled'] != true) return;
    final owner = snapshot['owner_id']?.toString();
    if (_speechOwner != owner) {
      _speechOwner = owner;
      _voiceGeneration++;
    }
    final voiceGeneration = _voiceGeneration;
    for (final value in (snapshot['reminders'] as List? ?? const [])) {
      if (value is! Map || !missing.contains(value['id'])) continue;
      final text = (value['body'] ?? value['title'])?.toString() ?? '';
      if (text.isEmpty || text.length > 1000) continue;
      final payload = {
        'owner_id': snapshot['owner_id'],
        'id': value['id'],
        'available_at': value['available_at'],
        'body': text,
      };
      final key = '$generation:$voiceGeneration:${jsonEncode(payload)}';
      if (!_voicePending.add(key)) continue;
      _voiceQueue = _voiceQueue.then((_) async {
        try {
          if (generation != _generation ||
              voiceGeneration != _voiceGeneration) {
            return;
          }
          final bytes = await _prepareSpeech(text);
          if (generation != _generation ||
              voiceGeneration != _voiceGeneration) {
            return;
          }
          await _channel.invokeMethod<bool>('cacheReminderSpeech', {
            'snapshot': jsonEncode({...payload, 'audio': base64Encode(bytes)}),
          });
        } catch (_) {
          // Scheduling already succeeded. The notification survives a voice failure.
        } finally {
          _voicePending.remove(key);
        }
      });
    }
  }

  void invalidate() {
    _generation++;
    _voiceGeneration++;
    _speechOwner = null;
    _speechSnapshot = null;
  }

  Future<void> clear() async {
    invalidate();
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
