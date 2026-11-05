import 'package:flutter/services.dart';

class OwnerVoiceStatus {
  final bool supported;
  final bool enrolled;
  final bool enabled;
  final int samples;

  const OwnerVoiceStatus({
    this.supported = true,
    this.enrolled = false,
    this.enabled = false,
    this.samples = 0,
  });

  factory OwnerVoiceStatus.fromMap(Map<Object?, Object?> value) {
    final count = value['samples'];
    return OwnerVoiceStatus(
      supported: value['supported'] != false,
      enrolled: value['enrolled'] == true,
      enabled: value['enabled'] == true,
      samples: count is num ? count.toInt().clamp(0, 3) : 0,
    );
  }
}

/// The native implementation stores only a protected, device-local voice profile.
class OwnerVoiceService {
  static const _channel = MethodChannel('com.troika.hermes/owner_voice');

  Future<OwnerVoiceStatus> _status(String method, [Object? arguments]) async {
    final value = await _channel.invokeMapMethod<Object?, Object?>(
      method,
      arguments,
    );
    if (value == null) {
      throw PlatformException(
        code: 'owner_voice_unavailable',
        message: 'Проверка голоса недоступна в этой версии приложения.',
      );
    }
    return OwnerVoiceStatus.fromMap(value);
  }

  Future<OwnerVoiceStatus> status() async {
    try {
      return await _status('status');
    } on MissingPluginException {
      return const OwnerVoiceStatus(supported: false);
    }
  }

  Future<OwnerVoiceStatus> enroll() => _status('enroll');

  Future<OwnerVoiceStatus> setEnabled(bool enabled) =>
      _status('setEnabled', {'enabled': enabled});

  Future<OwnerVoiceStatus> delete() => _status('delete');

  Future<void> cancel() => _channel.invokeMethod<void>('cancel');
}
