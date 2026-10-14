import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../lib/services/own_api_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('personal credentials are account bound and never written to preferences', () async {
    SharedPreferences.setMockInitialValues({});
    await OwnApiService.connect('a@example.invalid', 'openrouter', 'own/model', 'personal-fixture-key-12345');
    expect((await OwnApiService.headers('a@example.invalid'))['X-Troika-Provider-Key'], 'personal-fixture-key-12345');
    expect(await OwnApiService.headers('b@example.invalid'), isEmpty);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getKeys().map((k) => prefs.get(k).toString()).join(), isNot(contains('personal-fixture-key-12345')));
    await OwnApiService.disconnect();
    expect(await OwnApiService.headers('a@example.invalid'), isEmpty);
  });
  test('remembered personal mode without its key refuses company fallback', () async {
    SharedPreferences.setMockInitialValues({'troika_personal_provider_enabled': true,
      'troika_personal_provider_owner': 'restored@example.invalid'});
    await expectLater(OwnApiService.headers('restored@example.invalid'), throwsStateError);
  });
}
