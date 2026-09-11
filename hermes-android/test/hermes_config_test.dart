import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:hermes_assistant/config/hermes_config.dart';

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
}
