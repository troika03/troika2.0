import 'package:flutter/material.dart';
import '../config/troika_config.dart';
import '../services/assistant_service.dart';

/// Единая дизайн-система Тройки.
///
/// Принципы: один тёплый фирменный акцент (Troika Amber), тёплый почти-чёрный
/// фон, чистая типографика (Inter), без неона/градиентов-радуг/HUD-мусора.
/// Тёплая палитра читается как «человеческое», а не «холодное AI».
class TroikaColors {
  TroikaColors._();

  /// Фирменный акцент — тёплый медово-янтарный. Лицо бренда.
  static const Color brand = Color(0xFFF5A623);
  static const Color brandDeep = Color(0xFFE08A12);
  static const Color brandSoft = Color(0xFFFFC65C);

  /// Keep accent tones readable on both neutral backgrounds.
  static Color accentFor(String name, {required bool dark}) => switch (name) {
        'teal' => dark ? const Color(0xFF65C8B9) : const Color(0xFF00695C),
        'blue' => dark ? const Color(0xFF82B9F5) : const Color(0xFF245B9A),
        'violet' => dark ? const Color(0xFFB6A2F4) : const Color(0xFF6246A3),
        'rose' => dark ? const Color(0xFFFFA1AE) : const Color(0xFFAD3E56),
        'green' => dark ? const Color(0xFFA6CF82) : const Color(0xFF537735),
        _ => dark ? brand : brandDeep,
      };

  /// Фон — тёплый почти-чёрный (не чистый #000, чуть тёплее).
  static const Color bg = Color(0xFF0C0B0A);
  static const Color surface = Color(0xFF17150F);
  static const Color surfaceHi = Color(0xFF211E16);

  /// Текст — тёплый off-white и приглушённый.
  static const Color text = Color(0xFFF3F0EA);
  static const Color textMuted = Color(0xFF8C887F);
  static const Color textFaint = Color(0xFF55524B);

  /// Единственный «не-акцентный» цвет — мягкая тёплая ошибка.
  static const Color error = Color(0xFFE5604D);

  /// Цвет под состояние ассистента. Бренд держим постоянным, играем
  /// яркостью/мотивом, ошибка — единственное исключение.
  static Color forState(AssistantState s) {
    switch (s) {
      case AssistantState.idle:
        return brand;
      case AssistantState.wakeDetected:
        return brandSoft;
      case AssistantState.recording:
        return brandSoft;
      case AssistantState.processing:
        return brand;
      case AssistantState.speaking:
        return brandSoft;
      case AssistantState.error:
        return error;
    }
  }

  /// Короткая подпись состояния — спокойная, строчными, без жаргона.
  static String hint(AssistantState s) {
    switch (s) {
      case AssistantState.idle:
        return 'скажи «тройка»';
      case AssistantState.wakeDetected:
        return 'да, слушаю';
      case AssistantState.recording:
        return 'слушаю — нажми, чтобы отправить';
      case AssistantState.processing:
        return 'думаю';
      case AssistantState.speaking:
        return 'нажми, чтобы прервать';
      case AssistantState.error:
        return 'ошибка — нажми, чтобы повторить';
    }
  }
}

/// Светлая альтернатива той же палитры. Подключение пользовательского выбора
/// относится к настройкам клиента; токены готовы и не создают второй бренд.
class TroikaLightColors {
  TroikaLightColors._();

  static const Color bg = Color(0xFFFFFBF4);
  static const Color surface = Color(0xFFFFFFFF);
  static const Color surfaceHi = Color(0xFFFFF2DC);
  static const Color text = Color(0xFF211A11);
  static const Color textMuted = Color(0xFF70675C);
}

/// Тема приложения.
ThemeData buildTroikaTheme() {
  final accent =
      TroikaColors.accentFor(TroikaConfig.interfaceAccent, dark: true);
  return ThemeData(
    brightness: Brightness.dark,
    scaffoldBackgroundColor: TroikaColors.bg,
    colorScheme: ColorScheme.dark(
      primary: accent,
      secondary: accent,
      surface: TroikaColors.surface,
      error: TroikaColors.error,
      onPrimary: Color(0xFF1A1206),
    ),
    useMaterial3: true,
    textTheme: _troikaTextTheme(TroikaColors.text),
  );
}

/// Светлая тема использует тот же янтарный акцент и ту же типографику.
ThemeData buildTroikaLightTheme() {
  final accent =
      TroikaColors.accentFor(TroikaConfig.interfaceAccent, dark: false);
  return ThemeData(
    brightness: Brightness.light,
    scaffoldBackgroundColor: TroikaLightColors.bg,
    colorScheme: ColorScheme.light(
      primary: accent,
      secondary: accent,
      surface: TroikaLightColors.surface,
      error: TroikaColors.error,
      onPrimary: Color(0xFFFFFFFF),
    ),
    useMaterial3: true,
    textTheme: _troikaTextTheme(TroikaLightColors.text),
  );
}

TextTheme _troikaTextTheme(Color color) {
  return TextTheme(
    displaySmall: TextStyle(
      color: color,
      fontSize: 32,
      height: 1.1,
      fontWeight: FontWeight.w600,
      letterSpacing: -0.6,
    ),
    titleLarge: TextStyle(
      color: color,
      fontSize: 20,
      height: 1.2,
      fontWeight: FontWeight.w600,
    ),
    bodyLarge: TextStyle(color: color, fontSize: 16, height: 1.4),
    bodyMedium: TextStyle(color: color, fontSize: 14, height: 1.4),
  );
}
