import 'dart:io';

import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

import 'custom_command_store.dart';

class LocalCommandResult {
  final bool handled;
  final String response;
  final String heard;
  final String uiAction;

  const LocalCommandResult({
    required this.handled,
    this.response = '',
    this.heard = '',
    this.uiAction = '',
  });

  factory LocalCommandResult.fromMap(Map<Object?, Object?> value) {
    return LocalCommandResult(
      handled: value['handled'] == true,
      response: value['response']?.toString() ?? '',
      heard: value['heard']?.toString() ?? '',
      uiAction: value['uiAction']?.toString() ?? '',
    );
  }
}

/// Executes the small, deterministic command set that needs no Troika server.
///
/// Android delegates to the existing native [PhoneCommands] implementation.
/// Windows uses a strict allowlist. User text is never passed to a shell.
class LocalCommandService {
  final bool? windowsForTesting;
  final DateTime Function()? nowForTesting;
  final Future<void> Function(String key)? windowsKeySenderForTesting;

  LocalCommandService({
    this.windowsForTesting,
    this.nowForTesting,
    this.windowsKeySenderForTesting,
  });

  static const _platform = MethodChannel('com.troika.hermes/background');
  static const _modeKey = 'troika_local_mode';

  static const Map<String, String> _windowsApps = {
    'блокнот': 'notepad.exe',
    'notepad': 'notepad.exe',
    'калькулятор': 'calc.exe',
    'calculator': 'calc.exe',
    'проводник': 'explorer.exe',
    'файлы': 'explorer.exe',
    'диспетчер задач': 'taskmgr.exe',
    'task manager': 'taskmgr.exe',
    'настройки': 'ms-settings:',
    'settings': 'ms-settings:',
    'браузер': 'https://www.google.com/',
    'edge': 'msedge.exe',
    'хром': 'chrome.exe',
    'chrome': 'chrome.exe',
    'paint': 'mspaint.exe',
    'паинт': 'mspaint.exe',
    'word': 'winword.exe',
    'ворд': 'winword.exe',
    'excel': 'excel.exe',
    'эксель': 'excel.exe',
    'powerpoint': 'powerpnt.exe',
    'презентацию': 'powerpnt.exe',
    'телеграм': 'telegram.exe',
    'telegram': 'telegram.exe',
    'spotify': 'spotify.exe',
    'спотифай': 'spotify.exe',
    'ютуб': 'https://www.youtube.com/',
    'youtube': 'https://www.youtube.com/',
    'почту': 'https://mail.google.com/',
    'gmail': 'https://mail.google.com/',
    'камера': 'microsoft.windows.camera:',
    'camera': 'microsoft.windows.camera:',
    'карты': 'https://www.google.com/maps',
    'google maps': 'https://www.google.com/maps',
  };

  Future<LocalCommandResult> execute(
    String text, {
    bool preferAgentConversation = false,
  }) async {
    final clean = text.trim();
    if (clean.isEmpty) return const LocalCommandResult(handled: false);
    final direct = await _modeCommand(clean);
    if (direct != null) return direct;
    final custom = await _customAction(clean);
    final command = custom ?? clean;
    final mappedMode = await _modeCommand(command);
    if (mappedMode != null) return mappedMode;
    if (preferAgentConversation && _isConversation(command)) {
      return const LocalCommandResult(handled: false);
    }
    final common = _commonCommand(command);
    if (common != null) return common;
    final workspace = _workspaceCommand(command);
    if (workspace != null) return workspace;

    if (Platform.isAndroid) {
      try {
        final value = await _platform.invokeMethod<Map<Object?, Object?>>(
          'executeLocalCommand',
          {
            'text': command,
            'preferAgentConversation': preferAgentConversation,
          },
        );
        return value == null
            ? const LocalCommandResult(handled: false)
            : LocalCommandResult.fromMap(value);
      } on PlatformException {
        return const LocalCommandResult(handled: false);
      }
    }

    if (windowsForTesting ?? Platform.isWindows) {
      return _executeWindows(command);
    }
    return const LocalCommandResult(handled: false);
  }

  Future<LocalCommandResult> recognizeAndExecute({
    bool preferAgentConversation = false,
  }) async {
    if (!Platform.isAndroid) {
      return const LocalCommandResult(handled: false);
    }
    try {
      final value = await _platform.invokeMethod<Map<Object?, Object?>>(
        'recognizeLocalCommand',
        {'preferAgentConversation': preferAgentConversation},
      );
      final result = value == null
          ? const LocalCommandResult(handled: false)
          : LocalCommandResult.fromMap(value);
      if (!result.handled && result.heard.trim().isNotEmpty) {
        final retried = await execute(
          result.heard,
          preferAgentConversation: preferAgentConversation,
        );
        return LocalCommandResult(
          handled: retried.handled,
          response: retried.response,
          heard: result.heard,
          uiAction: retried.uiAction,
        );
      }
      return result;
    } on PlatformException catch (e) {
      return LocalCommandResult(
        handled: true,
        response: e.message ?? 'Не удалось распознать команду.',
      );
    }
  }

  Future<String?> _customAction(String text) async {
    final normalized = _normalize(text);
    final commands = await CustomCommandStore.load();
    for (final command in commands) {
      if (_normalize(command.phrase) == normalized) return command.action;
    }
    return null;
  }

  Future<LocalCommandResult?> _modeCommand(String text) async {
    final normalized = _normalize(text);
    String? mode;
    String? response;
    if (normalized == 'режим протокол' || normalized == 'включи протокол') {
      mode = 'protocol';
      response =
          'Режим «Протокол» включён. Команды фиксируются в диалоге кратко.';
    } else if (normalized == 'режим отдых' ||
        normalized == 'включи режим отдых' ||
        normalized == 'режим отдыха') {
      mode = 'rest';
      response = 'Режим «Отдых» включён. Голосовые ответы отключены.';
    } else if (normalized == 'обычный режим' ||
        normalized == 'выключи режим отдых' ||
        normalized == 'режим обычный') {
      mode = 'normal';
      response = 'Обычный режим включён.';
    }
    if (mode == null) return null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_modeKey, mode);
    return LocalCommandResult(handled: true, response: response!);
  }

  static Future<String> currentMode() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_modeKey) ?? 'normal';
  }

  LocalCommandResult? _commonCommand(String text) {
    final normalized = _withoutAssistantAddress(_normalize(text));
    final now = nowForTesting?.call() ?? DateTime.now();

    if (const {
      'привет',
      'приветик',
      'здравствуй',
      'здравствуйте',
      'доброе утро',
      'добрый день',
      'добрый вечер',
    }.contains(normalized)) {
      return const LocalCommandResult(
        handled: true,
        response: 'Привет! Я рядом. Что сделать?',
      );
    }
    if (const {
      'пока',
      'до свидания',
      'до встречи',
      'увидимся',
      'спокойной ночи',
    }.contains(normalized)) {
      return const LocalCommandResult(
        handled: true,
        response: 'Пока! Позови, когда понадоблюсь.',
      );
    }
    if (const {
      'спасибо',
      'благодарю',
      'спасибо большое',
      'большое спасибо',
    }.contains(normalized)) {
      return const LocalCommandResult(
        handled: true,
        response: 'Пожалуйста.',
      );
    }
    if (const {
      'как дела',
      'как ты',
      'ты тут',
      'ты здесь',
      'ты работаешь',
    }.contains(normalized)) {
      return const LocalCommandResult(
        handled: true,
        response: 'Я на связи и готова помочь.',
      );
    }
    if (const {
      'кто ты',
      'как тебя зовут',
      'представься',
    }.contains(normalized)) {
      return const LocalCommandResult(
        handled: true,
        response: 'Я Тройка.',
      );
    }
    if (const {
      'помощь',
      'помоги',
      'команды',
      'список команд',
      'покажи команды',
      'что ты умеешь',
      'что умеешь',
      'что ты можешь',
      'что можешь',
      'твои возможности',
      'что я могу сказать',
    }.contains(normalized)) {
      return LocalCommandResult(
        handled: true,
        response: _helpText(),
      );
    }

    if (normalized.contains('который час') ||
        normalized.contains('каторый час') ||
        normalized == 'время' ||
        normalized.contains('сколько времени')) {
      final hh = now.hour.toString().padLeft(2, '0');
      final mm = now.minute.toString().padLeft(2, '0');
      return LocalCommandResult(handled: true, response: 'Сейчас $hh:$mm');
    }
    if (normalized.contains('какая дата') ||
        normalized.contains('какая сегодня дата') ||
        normalized.contains('сегодняшняя дата') ||
        normalized == 'дата' ||
        normalized.contains('какое сегодня число') ||
        normalized.contains('сегодня какое число')) {
      return LocalCommandResult(
        handled: true,
        response: 'Сегодня ${now.day.toString().padLeft(2, '0')}.'
            '${now.month.toString().padLeft(2, '0')}.${now.year}',
      );
    }
    if (normalized.contains('день недели') ||
        normalized == 'какой сегодня день' ||
        normalized == 'сегодня какой день' ||
        normalized == 'какой день сегодня' ||
        normalized == 'какой сейчас день' ||
        normalized == 'что сегодня за день') {
      const weekdays = [
        'понедельник',
        'вторник',
        'среда',
        'четверг',
        'пятница',
        'суббота',
        'воскресенье',
      ];
      return LocalCommandResult(
        handled: true,
        response: 'Сегодня ${weekdays[now.weekday - 1]}',
      );
    }

    return _calculationCommand(normalized);
  }

  String _helpText() {
    if (windowsForTesting ?? Platform.isWindows) {
      return 'Могу открыть приложение, переключить окно или помочь создать '
          'документ. Попробуй: «открой калькулятор» или «создай презентацию».';
    }
    if (Platform.isAndroid) {
      return 'Могу открыть приложение, поставить таймер или включить фонарик. '
          'Попробуй: «таймер на пять минут» или «включи фонарик».';
    }
    return 'Могу подсказать время, посчитать или помочь создать документ. '
        'Попробуй: «сколько будет 12 плюс 8».';
  }

  // Only exact conversational phrases bypass the deterministic action layer.
  static bool _isConversation(String text) {
    final normalized = _withoutAssistantAddress(_normalize(text));
    return const {
      'привет',
      'приветик',
      'здравствуй',
      'здравствуйте',
      'доброе утро',
      'добрый день',
      'добрый вечер',
      'пока',
      'до свидания',
      'до встречи',
      'увидимся',
      'спокойной ночи',
      'спасибо',
      'благодарю',
      'спасибо большое',
      'большое спасибо',
      'как дела',
      'как ты',
      'ты тут',
      'ты здесь',
      'ты работаешь',
      'кто ты',
      'как тебя зовут',
      'представься',
      'помоги',
      'что ты умеешь',
      'что умеешь',
      'что ты можешь',
      'что можешь',
      'твои возможности',
    }.contains(normalized);
  }

  static LocalCommandResult? _calculationCommand(String normalized) {
    final match = RegExp(
      r'^(?:сколько будет|посчитай|вычисли|рассчитай)\s+'
      r'(-?\d+(?:[\.,]\d+)?)\s*'
      r'(плюс|минус|умножить на|умножь на|делить на|разделить на|[+\-*/xх])\s*'
      r'(-?\d+(?:[\.,]\d+)?)$',
    ).firstMatch(normalized);
    if (match == null) return null;
    final left = double.parse(match.group(1)!.replaceAll(',', '.'));
    final operator = match.group(2)!;
    final right = double.parse(match.group(3)!.replaceAll(',', '.'));
    if ((operator == '/' ||
            operator == 'делить на' ||
            operator == 'разделить на') &&
        right == 0) {
      return const LocalCommandResult(
        handled: true,
        response: 'На ноль делить нельзя.',
      );
    }
    final value = switch (operator) {
      'плюс' || '+' => left + right,
      'минус' || '-' => left - right,
      'умножить на' || 'умножь на' || '*' || 'x' || 'х' => left * right,
      _ => left / right,
    };
    var answer = value.toStringAsFixed(6);
    answer = answer.replaceFirst(RegExp(r'\.?0+$'), '');
    return LocalCommandResult(handled: true, response: 'Ответ: $answer');
  }

  static String _withoutAssistantAddress(String normalized) {
    var value = normalized;
    for (final prefix in ['эй тройка ', 'слушай тройка ', 'тройка ']) {
      if (value.startsWith(prefix)) {
        value = value.substring(prefix.length).trim();
        break;
      }
    }
    if (value.endsWith(' тройка')) {
      value = value.substring(0, value.length - ' тройка'.length).trim();
    }
    return value;
  }

  static LocalCommandResult? _workspaceCommand(String text) {
    final normalized = _normalize(text);
    final create = normalized.contains('создай') ||
        normalized.contains('сделай') ||
        normalized.contains('создать');
    final presentation = [
      'презентац',
      'презентач',
      'презинтац',
      'презинтач',
      'призентац',
      'призентач',
    ].any(normalized.contains);
    if (create && presentation) {
      return const LocalCommandResult(
        handled: true,
        response: 'Открываю создание презентации.',
        uiAction: 'create_presentation',
      );
    }
    if (create &&
        (normalized.contains('документ') || normalized.contains('docx'))) {
      return const LocalCommandResult(
        handled: true,
        response: 'Открываю создание документа.',
        uiAction: 'create_document',
      );
    }
    return null;
  }

  Future<LocalCommandResult> _executeWindows(String text) async {
    final norm = _normalize(text);

    if (norm.contains('покажи рабочий стол') ||
        norm.contains('сверни все окна') ||
        norm.contains('сверни всё')) {
      await _runAllowed(
        'powershell.exe',
        const [
          '-NoProfile',
          '-NonInteractive',
          '-Command',
          '(New-Object -ComObject Shell.Application).ToggleDesktop()',
        ],
      );
      return const LocalCommandResult(
        handled: true,
        response: 'Показываю рабочий стол',
      );
    }

    if (norm.contains('следующее окно') ||
        norm.contains('переключи окно') ||
        norm.contains('переключись на другое окно')) {
      await _sendWindowsKey('%{TAB}');
      return const LocalCommandResult(
        handled: true,
        response: 'Переключаю окно',
      );
    }
    if (norm.contains('предыдущее окно')) {
      await _sendWindowsKey('+%{TAB}');
      return const LocalCommandResult(
        handled: true,
        response: 'Переключаю на предыдущее окно',
      );
    }
    if (norm.contains('обнови страницу') || norm == 'обновить страницу') {
      await _sendWindowsKey('{F5}');
      return const LocalCommandResult(
        handled: true,
        response: 'Обновляю страницу',
      );
    }
    if (norm.contains('полный экран') || norm.contains('во весь экран')) {
      await _sendWindowsKey('{F11}');
      return const LocalCommandResult(
        handled: true,
        response: 'Переключаю полноэкранный режим',
      );
    }

    if (norm.contains('заблокируй компьютер') || norm == 'заблокируй пк') {
      await _runAllowed(
        'rundll32.exe',
        const ['user32.dll,LockWorkStation'],
      );
      return const LocalCommandResult(
        handled: true,
        response: 'Компьютер заблокирован',
      );
    }

    final mediaKey = _mediaKey(norm);
    if (mediaKey != null) {
      await _sendWindowsKey(mediaKey.$1);
      return LocalCommandResult(handled: true, response: mediaKey.$2);
    }

    final settingsUri = _windowsSettings(norm);
    if (settingsUri != null) {
      await launchUrl(
        Uri.parse(settingsUri.$1),
        mode: LaunchMode.externalApplication,
      );
      return LocalCommandResult(handled: true, response: settingsUri.$2);
    }

    if (norm.contains('сделай скриншот') || norm.contains('снимок экрана')) {
      return const LocalCommandResult(
        handled: true,
        response: 'Нужно подтвердить снимок экрана.',
        uiAction: 'capture_screen_for_vision',
      );
    }

    if (norm.contains('закрой окно') || norm.contains('закрой это окно')) {
      await _sendWindowsKey('%{F4}');
      return const LocalCommandResult(
        handled: true,
        response: 'Закрываю активное окно',
      );
    }

    if (norm.contains('заряд') || norm.contains('батаре')) {
      final result = await Process.run(
        'powershell.exe',
        const [
          '-NoProfile',
          '-NonInteractive',
          '-Command',
          r'(Get-CimInstance Win32_Battery | Select-Object -First 1 -ExpandProperty EstimatedChargeRemaining)',
        ],
        runInShell: false,
      );
      final value = result.stdout.toString().trim();
      return LocalCommandResult(
        handled: true,
        response:
            value.isEmpty ? 'Данные о батарее недоступны' : 'Заряд $value%',
      );
    }

    final folder = _windowsFolder(norm);
    if (folder != null) {
      await _runAllowed('explorer.exe', [folder]);
      return const LocalCommandResult(
        handled: true,
        response: 'Открываю папку',
      );
    }

    final app = _requestedApp(norm);
    if (app != null) {
      if (app.startsWith('http') ||
          app.startsWith('ms-settings:') ||
          app.startsWith('microsoft.windows.camera:')) {
        await launchUrl(Uri.parse(app), mode: LaunchMode.externalApplication);
      } else {
        await _runAllowed(app, const []);
      }
      return const LocalCommandResult(
        handled: true,
        response: 'Открываю',
      );
    }

    return const LocalCommandResult(handled: false);
  }

  static String _normalize(String text) => text
      .toLowerCase()
      .replaceAll('ё', 'е')
      .replaceAllMapped(
        RegExp(r'(\d),(\d)'),
        (match) => '${match.group(1)}.${match.group(2)}',
      )
      .replaceAll(RegExp(r'[^a-zа-я0-9:+*/\-\.\s]'), ' ')
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();

  static String? _requestedApp(String norm) {
    const verbs = ['открой ', 'запусти ', 'покажи ', 'включи '];
    String? requested;
    for (final verb in verbs) {
      final index = norm.indexOf(verb);
      if (index >= 0) {
        requested = norm.substring(index + verb.length).trim();
        break;
      }
    }
    if (requested == null || requested.isEmpty) return null;
    for (final entry in _windowsApps.entries) {
      if (requested == entry.key || requested.contains(entry.key)) {
        return entry.value;
      }
    }
    return null;
  }

  static String? _windowsFolder(String norm) {
    final home = Platform.environment['USERPROFILE'];
    if (home == null || home.isEmpty) return null;
    if (!norm.contains('открой') && !norm.contains('покажи')) return null;
    if (norm.contains('загрузк')) return '$home\\Downloads';
    if (norm.contains('документ')) return '$home\\Documents';
    if (norm.contains('изображен') || norm.contains('картин')) {
      return '$home\\Pictures';
    }
    if (norm.contains('музык')) return '$home\\Music';
    if (norm.contains('видео')) return '$home\\Videos';
    if (norm.contains('рабочий стол')) return '$home\\Desktop';
    return null;
  }

  static (String, String)? _mediaKey(String norm) {
    if (norm.contains('громче') || norm.contains('увеличь громкость')) {
      return (String.fromCharCode(175), 'Делаю громче');
    }
    if (norm.contains('тише') || norm.contains('уменьши громкость')) {
      return (String.fromCharCode(174), 'Делаю тише');
    }
    if (norm.contains('выключи звук') || norm == 'без звука') {
      return (String.fromCharCode(173), 'Переключаю звук');
    }
    if (norm.contains('пауза') || norm.contains('продолжи музыку')) {
      return (String.fromCharCode(179), 'Готово');
    }
    if (norm.contains('следующий трек') || norm.contains('следующая песня')) {
      return (String.fromCharCode(176), 'Следующий трек');
    }
    if (norm.contains('предыдущий трек') || norm.contains('предыдущая песня')) {
      return (String.fromCharCode(177), 'Предыдущий трек');
    }
    return null;
  }

  static (String, String)? _windowsSettings(String norm) {
    if (!norm.contains('настройк')) return null;
    if (norm.contains('wi-fi') ||
        norm.contains('вайфай') ||
        norm.contains('сети')) {
      return ('ms-settings:network-wifi', 'Открываю настройки Wi-Fi');
    }
    if (norm.contains('bluetooth') || norm.contains('блютуз')) {
      return ('ms-settings:bluetooth', 'Открываю настройки Bluetooth');
    }
    if (norm.contains('экрана') || norm.contains('диспле')) {
      return ('ms-settings:display', 'Открываю настройки экрана');
    }
    if (norm.contains('звука')) {
      return ('ms-settings:sound', 'Открываю настройки звука');
    }
    if (norm.contains('приложен')) {
      return ('ms-settings:appsfeatures', 'Открываю настройки приложений');
    }
    if (norm.contains('обновлен')) {
      return ('ms-settings:windowsupdate', 'Открываю обновления Windows');
    }
    return ('ms-settings:', 'Открываю настройки');
  }

  Future<void> _sendWindowsKey(String key) async {
    final sender = windowsKeySenderForTesting;
    if (sender != null) {
      await sender(key);
      return;
    }
    await Process.run(
      'powershell.exe',
      [
        '-NoProfile',
        '-NonInteractive',
        '-Command',
        r'$w = New-Object -ComObject WScript.Shell; $w.SendKeys($args[0])',
        key,
      ],
      runInShell: false,
    );
  }

  static Future<void> _runAllowed(
    String executable,
    List<String> arguments,
  ) async {
    await Process.start(
      executable,
      arguments,
      mode: ProcessStartMode.detached,
      runInShell: false,
    );
  }
}
