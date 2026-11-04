import 'package:flutter/material.dart';
import '../config/troika_config.dart';
import '../services/assistant_service.dart';

/// Единая дизайн-система Тройки.
///
/// Графитовые поверхности, Golos Text и зелёный голосовой контур.
class TroikaColors {
  TroikaColors._();

  static const Color brand = Color(0xFF8DE0B4);
  static const Color brandDeep = Color(0xFF286747);
  static const Color brandSoft = Color(0xFFA7E4BF);

  /// Keep accent tones readable on both neutral backgrounds.
  static Color accentFor(String name, {required bool dark}) => switch (name) {
    'amber' => dark ? const Color(0xFFF5A623) : const Color(0xFF8E5419),
    'teal' => dark ? const Color(0xFF65C8B9) : const Color(0xFF00695C),
    'blue' => dark ? const Color(0xFF82B9F5) : const Color(0xFF245B9A),
    'violet' => dark ? const Color(0xFFB6A2F4) : const Color(0xFF6246A3),
    'rose' => dark ? const Color(0xFFFFA1AE) : const Color(0xFFAD3E56),
    'green' => dark ? const Color(0xFFA6CF82) : const Color(0xFF537735),
    _ => dark ? brandSoft : brandDeep,
  };

  static const Color bg = Color(0xFF202322);
  static const Color navigation = Color(0xFF181B1A);
  static const Color surface = Color(0xFF2C302E);
  static const Color surfaceHi = Color(0xFF363B38);
  static const Color line = Color(0xFF3A413D);
  static const Color accentSurface = Color(0xFF293A30);

  static const Color text = Color(0xFFF4F7F4);
  static const Color textMuted = Color(0xFFA4ADA6);
  static const Color textFaint = Color(0xFF8D9991);

  static const Color error = Color(0xFFF2A69A);

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
        return 'нажми, чтобы отправить';
      case AssistantState.processing:
        return 'разбираюсь';
      case AssistantState.speaking:
        return 'нажми, чтобы прервать';
      case AssistantState.error:
        return 'нажми, чтобы повторить';
    }
  }
}

/// Светлая альтернатива той же палитры. Подключение пользовательского выбора
/// относится к настройкам клиента; токены готовы и не создают второй бренд.
class TroikaLightColors {
  TroikaLightColors._();

  static const Color bg = Color(0xFFFAFCF9);
  static const Color navigation = Color(0xFFF0F3EE);
  static const Color surface = Color(0xFFEDF2EC);
  static const Color surfaceHi = Color(0xFFE5EBE3);
  static const Color line = Color(0xFFDDE5DB);
  static const Color accentSurface = Color(0xFFE6F3E9);
  static const Color text = Color(0xFF1F2923);
  static const Color textMuted = Color(0xFF68756B);
  static const Color error = Color(0xFFA53830);
}

/// Тема приложения.
ThemeData buildTroikaTheme() => _buildTroikaTheme(dark: true);

ThemeData buildTroikaLightTheme() => _buildTroikaTheme(dark: false);

ThemeData _buildTroikaTheme({required bool dark}) {
  final accent = TroikaColors.accentFor(
    TroikaConfig.interfaceAccent,
    dark: dark,
  );
  final background = dark ? TroikaColors.bg : TroikaLightColors.bg;
  final surface = dark ? TroikaColors.surface : TroikaLightColors.surface;
  final text = dark ? TroikaColors.text : TroikaLightColors.text;
  final muted = dark ? TroikaColors.textMuted : TroikaLightColors.textMuted;
  final line = dark ? TroikaColors.line : TroikaLightColors.line;
  final onAccent = dark ? TroikaLightColors.text : Colors.white;
  final error = dark ? TroikaColors.error : TroikaLightColors.error;
  final scheme =
      ColorScheme.fromSeed(
        seedColor: accent,
        brightness: dark ? Brightness.dark : Brightness.light,
      ).copyWith(
        primary: accent,
        secondary: accent,
        primaryContainer: dark
            ? TroikaColors.accentSurface
            : TroikaLightColors.accentSurface,
        onPrimary: onAccent,
        onSecondary: onAccent,
        onPrimaryContainer: text,
        surface: surface,
        onSurface: text,
        onSurfaceVariant: muted,
        outline: muted,
        outlineVariant: line,
        error: error,
        onError: dark ? TroikaLightColors.text : Colors.white,
      );
  final buttonShape = RoundedRectangleBorder(
    borderRadius: BorderRadius.circular(24),
  );
  final fieldBorder = OutlineInputBorder(
    borderRadius: BorderRadius.circular(12),
    borderSide: BorderSide(color: line),
  );
  return ThemeData(
    fontFamily: 'Golos Text',
    brightness: scheme.brightness,
    scaffoldBackgroundColor: background,
    colorScheme: scheme,
    useMaterial3: true,
    textTheme: _troikaTextTheme(text),
    appBarTheme: AppBarTheme(
      backgroundColor: background,
      foregroundColor: text,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      titleTextStyle: TextStyle(
        fontFamily: 'Golos Text',
        fontSize: 18,
        fontWeight: FontWeight.w500,
        color: text,
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: accent,
        foregroundColor: onAccent,
        minimumSize: const Size(48, 48),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
        elevation: 0,
        shape: buttonShape,
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: accent,
        foregroundColor: onAccent,
        minimumSize: const Size(48, 48),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
        elevation: 0,
        shape: buttonShape,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: text,
        minimumSize: const Size(48, 48),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        side: BorderSide(color: line),
        shape: buttonShape,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: accent,
        minimumSize: const Size(44, 44),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        shape: buttonShape,
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(
        foregroundColor: text,
        minimumSize: const Size(44, 44),
        shape: const CircleBorder(),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: surface,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      border: fieldBorder,
      enabledBorder: fieldBorder,
      focusedBorder: fieldBorder.copyWith(
        borderSide: BorderSide(color: accent, width: 1.5),
      ),
      errorBorder: fieldBorder.copyWith(borderSide: BorderSide(color: error)),
      focusedErrorBorder: fieldBorder.copyWith(
        borderSide: BorderSide(color: error, width: 1.5),
      ),
      hintStyle: TextStyle(color: muted, fontSize: 14),
      labelStyle: TextStyle(color: muted, fontSize: 14),
      floatingLabelStyle: TextStyle(color: accent, fontSize: 14),
      errorMaxLines: 3,
    ),
    dividerTheme: DividerThemeData(color: line, thickness: 1, space: 24),
    drawerTheme: DrawerThemeData(
      backgroundColor: dark
          ? TroikaColors.navigation
          : TroikaLightColors.navigation,
      surfaceTintColor: Colors.transparent,
    ),
    navigationBarTheme: _navigationTheme(accent, muted),
  );
}

TextTheme _troikaTextTheme(Color color) {
  return TextTheme(
    displaySmall: TextStyle(
      color: color,
      fontSize: 30,
      height: 1.3,
      fontWeight: FontWeight.w500,
    ),
    titleLarge: TextStyle(
      color: color,
      fontSize: 26,
      height: 1.3,
      fontWeight: FontWeight.w500,
    ),
    bodyLarge: TextStyle(color: color, fontSize: 16, height: 1.6),
    bodyMedium: TextStyle(color: color, fontSize: 14, height: 1.55),
    bodySmall: TextStyle(color: color, fontSize: 12, height: 1.5),
  );
}

NavigationBarThemeData _navigationTheme(Color accent, Color muted) =>
    NavigationBarThemeData(
      indicatorColor: Colors.transparent,
      iconTheme: WidgetStateProperty.resolveWith(
        (states) => IconThemeData(
          size: 20,
          color: states.contains(WidgetState.selected) ? accent : muted,
        ),
      ),
      labelTextStyle: WidgetStateProperty.resolveWith(
        (states) => TextStyle(
          fontFamily: 'Golos Text',
          fontSize: 12,
          fontWeight: FontWeight.w400,
          color: states.contains(WidgetState.selected) ? accent : muted,
        ),
      ),
    );
