import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/services/troika_api_service.dart';

void main() {
  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await TroikaConfig.init();
  });

  test('does not ship a shared API key', () {
    expect(TroikaConfig.defaultApiKey, isEmpty);
    expect(TroikaConfig.wakeWordEnabled, isFalse);
    expect(TroikaConfig.developerDiagnosticsEnabled, isFalse);
    expect(TroikaConfig.screenSnapshotBetaEnabled, isFalse);
  });

  test('migrates legacy preferences without losing account or consent',
      () async {
    SharedPreferences.setMockInitialValues({
      'hermes_server_url': 'https://legacy.example.test',
      'hermes_api_key': 'trk_live_legacy',
      'troika_account_email': 'owner@example.com',
      'hermes_wake_word_enabled': true,
      'hermes_onboarding_done': true,
      'hermes_session_key': 'mobile-legacy-session',
      'hermes_session_id': 'mobile-legacy-session',
      'hermes_location_context_enabled': true,
      'hermes_phone_control_enabled': true,
    });

    await TroikaConfig.init();

    expect(TroikaConfig.serverUrl, 'https://legacy.example.test');
    expect(TroikaConfig.apiKey, 'trk_live_legacy');
    expect(TroikaConfig.signedIn, isTrue);
    expect(TroikaConfig.wakeWordEnabled, isTrue);
    expect(TroikaConfig.onboardingDone, isTrue);
    expect(TroikaConfig.sessionId, 'mobile-legacy-session');
    expect(TroikaConfig.locationContextEnabled, isTrue);
    expect(TroikaConfig.phoneControlEnabled, isTrue);

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('troika_server_url'), 'https://legacy.example.test');
    expect(prefs.getString('troika_api_key'), 'trk_live_legacy');
    expect(prefs.getString('troika_session_id'), 'mobile-legacy-session');
    expect(prefs.getBool('troika_wake_word_enabled'), isTrue);
    expect(prefs.getBool('troika_location_context_enabled'), isTrue);
    expect(prefs.getBool('troika_phone_control_enabled'), isTrue);
    expect(prefs.getInt('troika_brand_migration_version'), 1);
  });

  test(
    'hosted build migrates local beta account without clearing local data',
    () async {
      SharedPreferences.setMockInitialValues({
        'troika_server_url': '',
        'troika_api_key': 'trk_live_old_beta',
        'troika_account_email': 'phone@beta.troika.local',
        'troika_phone_control_enabled': true,
        'troika_location_context_enabled': true,
        'troika_wake_word_enabled': true,
        'troika_onboarding_done': true,
        'troika_theme_mode': 'dark',
      });

      await TroikaConfig.init();

      const hostedEndpoint = String.fromEnvironment('TROIKA_SERVER_URL');
      expect(TroikaConfig.serverUrl, hostedEndpoint);
      expect(TroikaConfig.signedIn, isFalse);
      expect(TroikaConfig.phoneControlEnabled, isFalse);
      expect(TroikaConfig.locationContextEnabled, isFalse);
      expect(TroikaConfig.wakeWordEnabled, isFalse);
      expect(TroikaConfig.onboardingDone, isTrue);
      expect(TroikaConfig.themeMode, 'dark');
      expect(TroikaConfig.sessionId, startsWith('mobile-'));
    },
    skip: const String.fromEnvironment('TROIKA_SERVER_URL').isEmpty
        ? 'requires TROIKA_SERVER_URL build define'
        : false,
  );

  test('product STT preserves HTTPS origin, prefix and port', () {
    TroikaConfig.apiKey = 'trk_live_test';
    TroikaConfig.serverUrl = 'https://example.test:9443/troika/';
    expect(TroikaConfig.transcriptionUri.toString(),
        'https://example.test:9443/troika/v1/audio/transcriptions');
    TroikaConfig.serverUrl = 'http://127.0.0.1:8765';
    expect(TroikaConfig.transcriptionUri.port, 8765);
  });

  test('product account export uses authenticated server origin', () {
    TroikaConfig.serverUrl = 'https://example.test:9443/troika';
    expect(TroikaConfig.accountExportUrl,
        'https://example.test:9443/troika/v1/account/export');
    expect(TroikaConfig.accountDevicesUrl,
        'https://example.test:9443/troika/v1/account/devices');
    expect(TroikaConfig.subscriptionUrl,
        'https://example.test:9443/troika/v1/subscription');
  });

  test('parses owner-visible subscription status', () {
    final subscription = AccountSubscription.fromJson({
      'plan': 'plus',
      'status': 'active',
      'daily_limit': 100,
      'used': 12,
      'remaining': 88,
      'quota_enforced': true,
    });

    expect(subscription.plan, 'plus');
    expect(subscription.status, 'active');
    expect(subscription.dailyLimit, 100);
    expect(subscription.used, 12);
    expect(subscription.remaining, 88);
    expect(subscription.quotaEnforced, isTrue);
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
    TroikaConfig.apiKey = 'legacy-test-key';
    TroikaConfig.serverUrl = 'http://127.0.0.1:8642';
    expect(TroikaConfig.transcriptionUri.port, 8643);
  });

  test('creates one private session identity for voice and text', () {
    expect(TroikaConfig.sessionKey, startsWith('mobile-'));
    expect(TroikaConfig.sessionId, TroikaConfig.sessionKey);
    expect(
      TroikaConfig.chatHeaders['X-Hermes-Session-Key'],
      TroikaConfig.sessionKey,
    );
    expect(
      TroikaConfig.chatHeaders['X-Hermes-Session-Id'],
      TroikaConfig.sessionId,
    );
  });

  test('does not send device context without explicit consent', () async {
    expect(TroikaConfig.locationContextEnabled, isFalse);
    await TroikaConfig.setLocationContextEnabled(true);
    expect(TroikaConfig.locationContextEnabled, isTrue);

    expect(TroikaConfig.phoneControlEnabled, isFalse);
    await TroikaConfig.setPhoneControlEnabled(true);
    expect(TroikaConfig.phoneControlEnabled, isTrue);
  });

  test('clears deleted account credentials and rotates local session',
      () async {
    TroikaConfig.apiKey = 'trk_live_private';
    TroikaConfig.onboardingDone = true;
    await TroikaConfig.setLocationContextEnabled(true);
    await TroikaConfig.setPhoneControlEnabled(true);
    final previousSession = TroikaConfig.sessionId;

    await TroikaConfig.clearDeletedAccount();

    expect(TroikaConfig.apiKey, isEmpty);
    expect(TroikaConfig.onboardingDone, isFalse);
    expect(TroikaConfig.locationContextEnabled, isFalse);
    expect(TroikaConfig.phoneControlEnabled, isFalse);
    expect(TroikaConfig.sessionId, isEmpty);

    await TroikaConfig.init();
    expect(TroikaConfig.sessionId, startsWith('mobile-'));
    expect(TroikaConfig.sessionId, isNot(previousSession));
  });

  test('clears revoked device credentials and immediately rotates session',
      () async {
    await TroikaConfig.saveAccount(
      email: 'owner@example.com',
      token: 'trk_live_private',
    );
    TroikaConfig.onboardingDone = true;
    await TroikaConfig.setLocationContextEnabled(true);
    await TroikaConfig.setPhoneControlEnabled(true);
    final previousSession = TroikaConfig.sessionId;

    await TroikaConfig.clearRevokedDevice();

    expect(TroikaConfig.signedIn, isFalse);
    expect(TroikaConfig.accountEmail, isEmpty);
    expect(TroikaConfig.apiKey, isEmpty);
    expect(TroikaConfig.phoneControlEnabled, isFalse);
    expect(TroikaConfig.onboardingDone, isTrue);
    expect(TroikaConfig.locationContextEnabled, isFalse);
    expect(TroikaConfig.sessionId, startsWith('mobile-'));
    expect(TroikaConfig.sessionId, isNot(previousSession));
  });
}
