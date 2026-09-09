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
  });
}
