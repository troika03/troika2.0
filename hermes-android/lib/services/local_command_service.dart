import 'dart:io';

import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

import 'custom_command_store.dart';

class LocalCommandResult {
  final bool handled;
  final String response;
  final String heard;

  const LocalCommandResult({
    required this.handled,
    this.response = '',
    this.heard = '',
  });

  factory LocalCommandResult.fromMap(Map<Object?, Object?> value) {
    return LocalCommandResult(
      handled: value['handled'] == true,
      response: value['response']?.toString() ?? '',
      heard: value['heard']?.toString() ?? '',
    );
  }
}

/// Executes the small, deterministic command set that needs no Hermes server.
///
/// Android delegates to the existing native [PhoneCommands] implementation.
/// Windows uses a strict allowlist. User text is never passed to a shell.
class LocalCommandService {
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
  };

  Future<LocalCommandResult> execute(String text) async {
    final clean = text.trim();
    if (clean.isEmpty) return const LocalCommandResult(handled: false);
    final direct = await _modeCommand(clean);
    if (direct != null) return direct;
    final custom = await _customAction(clean);
    final command = custom ?? clean;

    if (Platform.isAndroid) {
      try {
        final value = await _platform.invokeMethod<Map<Object?, Object?>>(
          'executeLocalCommand',
          {'text': command},
        );
        return value == null
            ? const LocalCommandResult(handled: false)
            : LocalCommandResult.fromMap(value);
      } on PlatformException {
        return const LocalCommandResult(handled: false);
      }
    }

    if (Platform.isWindows) return _executeWindows(command);
    return const LocalCommandResult(handled: false);
  }

  Future<LocalCommandResult> recognizeAndExecute() async {
    if (!Platform.isAndroid) {
      return const LocalCommandResult(handled: false);
    }
    try {
      final value = await _platform.invokeMethod<Map<Object?, Object?>>(
        'recognizeLocalCommand',
      );
      final result = value == null
          ? const LocalCommandResult(handled: false)
          : LocalCommandResult.fromMap(value);
      if (!result.handled && result.heard.trim().isNotEmpty) {
        final retried = await execute(result.heard);
        return LocalCommandResult(
          handled: retried.handled,
          response: retried.response,
          heard: result.heard,
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

  Future<LocalCommandResult> _executeWindows(String text) async {
    final norm = _normalize(text);
    final now = DateTime.now();

    if (norm.contains('который час') ||
        norm.contains('каторый час') ||
        norm == 'время' ||
        norm.contains('сколько времени')) {
      final hh = now.hour.toString().padLeft(2, '0');
      final mm = now.minute.toString().padLeft(2, '0');
      return LocalCommandResult(handled: true, response: 'Сейчас $hh:$mm');
    }
    if (norm.contains('какая дата') ||
        norm == 'дата' ||
        norm.contains('какое сегодня число')) {
      return LocalCommandResult(
        handled: true,
        response: 'Сегодня ${now.day.toString().padLeft(2, '0')}.'
            '${now.month.toString().padLeft(2, '0')}.${now.year}',
      );
    }

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
      await launchUrl(
        Uri.parse('ms-screenclip:'),
        mode: LaunchMode.externalApplication,
      );
      return const LocalCommandResult(
        handled: true,
        response: 'Открываю создание снимка экрана',
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

    final search = _searchQuery(norm);
    if (search != null) {
      final uri = Uri.https('www.google.com', '/search', {'q': search});
      await launchUrl(uri, mode: LaunchMode.externalApplication);
      return LocalCommandResult(
        handled: true,
        response: 'Ищу: $search',
      );
    }

    final app = _requestedApp(norm);
    if (app != null) {
      if (app.startsWith('http') || app.startsWith('ms-settings:')) {
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
      .replaceAll(RegExp(r'[^a-zа-я0-9:\-\.\s]'), ' ')
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

  static String? _searchQuery(String norm) {
    for (final verb in ['найди ', 'поищи ', 'загугли ', 'погугли ']) {
      final index = norm.indexOf(verb);
      if (index >= 0) {
        final query = norm.substring(index + verb.length).trim();
        if (query.isNotEmpty && query.length <= 200) return query;
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

  static Future<void> _sendWindowsKey(String key) async {
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
