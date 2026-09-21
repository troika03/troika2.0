import 'package:flutter_test/flutter_test.dart';
import 'package:hermes_assistant/services/local_command_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('presentation request opens local presentation builder', () async {
    final result = await LocalCommandService().execute(
      'Создай презентацию на любую тему',
    );

    expect(result.handled, isTrue);
    expect(result.uiAction, 'create_presentation');
  });

  test('presentation request tolerates common spelling mistakes', () async {
    final result = await LocalCommandService().execute(
      'Прошу создать презинтачия',
    );

    expect(result.handled, isTrue);
    expect(result.uiAction, 'create_presentation');
  });

  test('document request opens local document builder', () async {
    final result = await LocalCommandService().execute(
      'Сделай документ про отпуск',
    );

    expect(result.handled, isTrue);
    expect(result.uiAction, 'create_document');
  });
}
