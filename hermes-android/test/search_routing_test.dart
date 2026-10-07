import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/services/local_command_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final launches = <MethodCall>[];
  const launcher = MethodChannel('plugins.flutter.io/url_launcher');

  setUp(() {
    launches.clear();
    SharedPreferences.setMockInitialValues({});
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(launcher, (call) async {
      launches.add(call);
      return true;
    });
  });
  tearDown(() => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
      .setMockMethodCallHandler(launcher, null));

  test('search requests reach the assistant without opening a browser', () async {
    final service = LocalCommandService(windowsForTesting: true);
    for (final phrase in [
      'Найди официальный сайт SearXNG',
      'Ищи источники про космос',
      'Поищи свежие новости',
      'Загугли погоду в Москве',
      'Погугли историю города',
      'Объясни поиск информации',
      'Пожалуйста, найди полезные ссылки',
    ]) {
      final result = await service.execute(phrase, preferAgentConversation: true);
      expect(result.handled, isFalse, reason: phrase);
    }
    expect(launches, isEmpty);
  });

  test('explicit open-browser command still opens the browser', () async {
    final result = await LocalCommandService(windowsForTesting: true)
        .execute('Открой браузер');
    expect(result.handled, isTrue);
    expect(launches, hasLength(1));
  });
}
