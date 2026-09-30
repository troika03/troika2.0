import 'package:flutter_test/flutter_test.dart';
import 'package:troika_assistant/services/local_command_service.dart';
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

  test('Windows screenshot requires the one-time Vision UI action', () async {
    final result = await LocalCommandService(windowsForTesting: true).execute(
      'Сделай снимок экрана',
    );

    expect(result.handled, isTrue);
    expect(result.uiAction, 'capture_screen_for_vision');
    expect(result.response, contains('подтвердить'));
  });

  test('basic conversation works locally on Android and Windows', () async {
    final service = LocalCommandService();

    final hello = await service.execute('Тройка, привет!');
    final bye = await service.execute('Пока');
    final thanks = await service.execute('Спасибо большое');

    expect(hello.handled, isTrue);
    expect(hello.response, contains('Привет'));
    expect(bye.handled, isTrue);
    expect(bye.response, contains('Пока'));
    expect(thanks.response, 'Пожалуйста.');
  });

  test('help and identity commands do not use cloud AI', () async {
    final service = LocalCommandService(windowsForTesting: true);

    final identity = await service.execute('Кто ты?');
    final help = await service.execute('Что ты умеешь?');

    expect(identity.response, contains('Тройка'));
    expect(help.handled, isTrue);
    expect(help.response, contains('Без интернета'));
    expect(help.response, contains('калькулятор'));
  });

  test('date, weekday and arithmetic work in shared local layer', () async {
    final service = LocalCommandService(
      nowForTesting: () => DateTime(2026, 9, 27, 8, 5),
    );

    final time = await service.execute('Который час');
    final date = await service.execute('Какая дата');
    final weekday = await service.execute('Какой сегодня день');
    final naturalDate = await service.execute('Сегодня какое число?');
    final naturalWeekday = await service.execute('Что сегодня за день?');
    final calculation = await service.execute('Посчитай 12,5 умножить на 4');
    final zeroDivision = await service.execute('Сколько будет 7 делить на 0');

    expect(time.response, 'Сейчас 08:05');
    expect(date.response, 'Сегодня 27.09.2026');
    expect(weekday.response, 'Сегодня воскресенье');
    expect(naturalDate.response, 'Сегодня 27.09.2026');
    expect(naturalWeekday.response, 'Сегодня воскресенье');
    expect(calculation.response, 'Ответ: 50');
    expect(zeroDivision.response, 'На ноль делить нельзя.');
  });

  test('Windows window and browser controls use fixed allowlisted keys',
      () async {
    final keys = <String>[];
    final service = LocalCommandService(
      windowsForTesting: true,
      windowsKeySenderForTesting: (key) async => keys.add(key),
    );

    final switchWindow = await service.execute('Переключи окно');
    final refresh = await service.execute('Обнови страницу');
    final fullScreen = await service.execute('Во весь экран');

    expect(switchWindow.response, 'Переключаю окно');
    expect(refresh.response, 'Обновляю страницу');
    expect(fullScreen.response, 'Переключаю полноэкранный режим');
    expect(keys, ['%{TAB}', '{F5}', '{F11}']);
  });
}
