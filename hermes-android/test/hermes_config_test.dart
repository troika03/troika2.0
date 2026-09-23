import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:hermes_assistant/config/hermes_config.dart';
import 'package:hermes_assistant/services/hermes_api_service.dart';

void main() {
  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await HermesConfig.init();
  });

  test('does not ship a shared API key', () {
    expect(HermesConfig.defaultApiKey, isEmpty);
    expect(HermesConfig.wakeWordEnabled, isFalse);
  });

  test('product STT preserves HTTPS origin, prefix and port', () {
    HermesConfig.apiKey = 'trk_live_test';
    HermesConfig.serverUrl = 'https://example.test:9443/troika/';
    expect(HermesConfig.transcriptionUri.toString(),
        'https://example.test:9443/troika/v1/audio/transcriptions');
    HermesConfig.serverUrl = 'http://127.0.0.1:8765';
    expect(HermesConfig.transcriptionUri.port, 8765);
  });

  test('product account export uses authenticated server origin', () {
    HermesConfig.serverUrl = 'https://example.test:9443/troika';
    expect(HermesConfig.accountExportUrl,
        'https://example.test:9443/troika/v1/account/export');
    expect(HermesConfig.accountDevicesUrl,
        'https://example.test:9443/troika/v1/account/devices');
  });

  test('parses owner-visible device metadata without credentials', () {
    final device = AccountDevice.fromJson({
      'id': 'dev_test',
      'name': 'Телефон',
      'platform': 'android',
      'status': 'active',
      'created_at': 1.5,
      'current': true,
    });

    expect(device.id, 'dev_test');
    expect(device.name, 'Телефон');
    expect(device.active, isTrue);
    expect(device.current, isTrue);
    expect(device.createdAt.millisecondsSinceEpoch, 1500);
  });

  test('legacy STT keeps its local proxy port', () {
    HermesConfig.apiKey = 'legacy-test-key';
    HermesConfig.serverUrl = 'http://127.0.0.1:8642';
    expect(HermesConfig.transcriptionUri.port, 8643);
  });

  test('creates one private session identity for voice and text', () {
    expect(HermesConfig.sessionKey, startsWith('mobile-'));
    expect(HermesConfig.sessionId, HermesConfig.sessionKey);
    expect(
      HermesConfig.chatHeaders['X-Hermes-Session-Key'],
      HermesConfig.sessionKey,
    );
    expect(
      HermesConfig.chatHeaders['X-Hermes-Session-Id'],
      HermesConfig.sessionId,
    );
  });

  test('does not send device context without explicit consent', () async {
    expect(HermesConfig.locationContextEnabled, isFalse);
    await HermesConfig.setLocationContextEnabled(true);
    expect(HermesConfig.locationContextEnabled, isTrue);

    expect(HermesConfig.phoneControlEnabled, isFalse);
    await HermesConfig.setPhoneControlEnabled(true);
    expect(HermesConfig.phoneControlEnabled, isTrue);
  });

  test('clears deleted account credentials and rotates local session',
      () async {
    HermesConfig.apiKey = 'trk_live_private';
    HermesConfig.onboardingDone = true;
    await HermesConfig.setLocationContextEnabled(true);
    await HermesConfig.setPhoneControlEnabled(true);
    final previousSession = HermesConfig.sessionId;

    await HermesConfig.clearDeletedAccount();

    expect(HermesConfig.apiKey, isEmpty);
    expect(HermesConfig.onboardingDone, isFalse);
    expect(HermesConfig.locationContextEnabled, isFalse);
    expect(HermesConfig.phoneControlEnabled, isFalse);
    expect(HermesConfig.sessionId, isEmpty);

    await HermesConfig.init();
    expect(HermesConfig.sessionId, startsWith('mobile-'));
    expect(HermesConfig.sessionId, isNot(previousSession));
  });

  test('clears revoked device credentials and immediately rotates session',
      () async {
    await HermesConfig.saveAccount(
      email: 'owner@example.com',
      token: 'trk_live_private',
    );
    HermesConfig.onboardingDone = true;
    await HermesConfig.setLocationContextEnabled(true);
    await HermesConfig.setPhoneControlEnabled(true);
    final previousSession = HermesConfig.sessionId;

    await HermesConfig.clearRevokedDevice();

    expect(HermesConfig.signedIn, isFalse);
    expect(HermesConfig.accountEmail, isEmpty);
    expect(HermesConfig.apiKey, isEmpty);
    expect(HermesConfig.phoneControlEnabled, isFalse);
    expect(HermesConfig.onboardingDone, isTrue);
    expect(HermesConfig.locationContextEnabled, isTrue);
    expect(HermesConfig.sessionId, startsWith('mobile-'));
    expect(HermesConfig.sessionId, isNot(previousSession));
  });
}
