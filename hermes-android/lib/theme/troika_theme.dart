import 'package:flutter/material.dart';
import '../config/troika_config.dart';
import '../services/assistant_service.dart';

/// Единая дизайн-система Тройки.
///
/// Принципы: один тёплый фирменный акцент (Troika Amber), тёплый почти-чёрный
/// фон, Golos Text и спокойные поверхности из согласованных макетов.
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
        _ => dark ? brand : const Color(0xFF8E5419),
      };

  /// Фон — тёплый почти-чёрный (не чистый #000, чуть тёплее).
  static const Color bg = Color(0xFF0C0B0A);
  static const Color surface = Color(0xFF21211D);
  static const Color surfaceHi = Color(0xFF2A2A24);

  /// Текст — тёплый off-white и приглушённый.
  static const Color text = Color(0xFFF3F0EA);
  static const Color textMuted = Color(0xFFB2B0A3);
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

  static const Color bg = Color(0xFFF3F0EA);
  static const Color surface = Color(0xFFFFFFFF);
  static const Color surfaceHi = Color(0xFFEDEAE2);
  static const Color text = Color(0xFF0C0B0A);
  static const Color textMuted = Color(0xFF68675E);
}

/// Тема приложения.
ThemeData buildTroikaTheme() {
  final accent =
      TroikaColors.accentFor(TroikaConfig.interfaceAccent, dark: true);
  return ThemeData(
    fontFamily: 'Golos Text',
    brightness: Brightness.dark,
    scaffoldBackgroundColor: TroikaColors.bg,
    colorScheme: ColorScheme.dark(
      primary: accent,
      secondary: accent,
      surface: TroikaColors.surface,
      onSurface: TroikaColors.text,
      onSurfaceVariant: TroikaColors.textMuted,
      outline: const Color(0xFF36362E),
      outlineVariant: const Color(0xFF36362E),
      error: TroikaColors.error,
      onPrimary: const Color(0xFF1A1206),
    ),
    useMaterial3: true,
    navigationBarTheme: _navigationTheme(accent, TroikaColors.textMuted),
    textTheme: _troikaTextTheme(TroikaColors.text),
  );
}

/// Светлая тема использует тот же янтарный акцент и ту же типографику.
ThemeData buildTroikaLightTheme() {
  final accent =
      TroikaColors.accentFor(TroikaConfig.interfaceAccent, dark: false);
  return ThemeData(
    fontFamily: 'Golos Text',
    brightness: Brightness.light,
    scaffoldBackgroundColor: TroikaLightColors.bg,
    colorScheme: ColorScheme.light(
      primary: accent,
      secondary: accent,
      surface: TroikaLightColors.surface,
      onSurface: TroikaLightColors.text,
      onSurfaceVariant: TroikaLightColors.textMuted,
      outline: const Color(0xFFDEDBD1),
      outlineVariant: const Color(0xFFDEDBD1),
      error: TroikaColors.error,
      onPrimary: const Color(0xFFFFFFFF),
    ),
    useMaterial3: true,
    navigationBarTheme: _navigationTheme(accent, TroikaLightColors.textMuted),
    textTheme: _troikaTextTheme(TroikaLightColors.text),
  );
}

TextTheme _troikaTextTheme(Color color) {
  return TextTheme(
    displaySmall: TextStyle(
      color: color,
      fontSize: 24,
      height: 1.25,
      fontWeight: FontWeight.w500,
    ),
    titleLarge: TextStyle(
      color: color,
      fontSize: 20,
      height: 1.2,
      fontWeight: FontWeight.w500,
    ),
    bodyLarge: TextStyle(color: color, fontSize: 16, height: 1.4),
    bodyMedium: TextStyle(color: color, fontSize: 14, height: 1.4),
  );
}

NavigationBarThemeData _navigationTheme(Color accent, Color muted) =>
    NavigationBarThemeData(
      indicatorColor: Colors.transparent,
      iconTheme: WidgetStateProperty.resolveWith((states) => IconThemeData(
            size: 16,
            color: states.contains(WidgetState.selected) ? accent : muted,
          )),
      labelTextStyle: WidgetStateProperty.resolveWith((states) => TextStyle(
            fontFamily: 'Golos Text',
            fontSize: 12,
            fontWeight: FontWeight.w400,
            color: states.contains(WidgetState.selected) ? accent : muted,
          )),
    );
