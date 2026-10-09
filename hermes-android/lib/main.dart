import 'dart:async';
import 'dart:io' show Platform;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'config/troika_config.dart';
import 'services/assistant_service.dart';
import 'screens/home_screen.dart';
import 'screens/auth_screen.dart';
import 'screens/onboarding_screen.dart';
import 'theme/troika_theme.dart';
import 'services/thought_translator.dart';
import 'widgets/troika_page.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Инициализировать настройки (SharedPreferences)
  await TroikaConfig.init();

  // Прогреть офлайн-переводчик мыслей EN->RU в фоне (разовая загрузка модели).
  unawaited(ThoughtTranslator.instance.warmUp());

  runApp(const TroikaApp());
}

class TroikaApp extends StatefulWidget {
  const TroikaApp({super.key});

  @override
  State<TroikaApp> createState() => _TroikaAppState();
}

class _TroikaAppState extends State<TroikaApp> {
  // Старые ручные подключения продолжают работать. Новая установка сначала
  // создаёт аккаунт и получает отдельный токен устройства.
  bool _authenticated = TroikaConfig.signedIn || TroikaConfig.apiKey.isNotEmpty;
  // Первый запуск показывает онбординг разрешений; после — сразу домой.
  // На десктопе (Windows/Linux/macOS) онбординг ПРОПУСКАЕТСЯ: его разрешения
  // (спец-возможности, поверх окон, фон, геолокация) — андроидные и на ПК не
  // применимы; микрофон запрашивается отдельно. Иначе пользователь застревает
  // на экране с неактивной кнопкой. Онбординг остаётся только для Android.
  bool _onboarded = TroikaConfig.onboardingDone || !Platform.isAndroid;

  ThemeMode get _themeMode => switch (TroikaConfig.themeMode) {
        'light' => ThemeMode.light,
        'dark' => ThemeMode.dark,
        _ => ThemeMode.system,
      };

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      // lazy:false обязательно — иначе AssistantService.init() не запустится
      // пока пользователь не откроет главный экран (Provider по умолчанию
      // ленивый). После свежей установки первый экран — онбординг, который
      // AssistantService не трогает: wake-word listener не поднимается,
      // сервис HermesListenerService не стартует, «Тройка» с главного экрана
      // молчит, пока пользователь не нажмёт «Готово». Ranger-init убирает
      // эту ловушку.
      lazy: false,
      create: (_) => AssistantService()..init(),
      child: MaterialApp(
        title: 'Тройка',
        debugShowCheckedModeBanner: false,
        theme: buildTroikaLightTheme(),
        darkTheme: buildTroikaTheme(),
        themeMode: _themeMode,
        builder: (context, child) {
          final systemDark = TroikaConfig.themeMode == 'dark' ||
              (TroikaConfig.themeMode == 'system' &&
                  MediaQuery.platformBrightnessOf(context) == Brightness.dark);
          final surface = systemDark ? TroikaColors.bg : TroikaLightColors.bg;
          return AnnotatedRegion<SystemUiOverlayStyle>(
            value: SystemUiOverlayStyle(
              statusBarColor: Colors.transparent,
              statusBarIconBrightness:
                  systemDark ? Brightness.light : Brightness.dark,
              systemNavigationBarColor: surface,
              systemNavigationBarIconBrightness:
                  systemDark ? Brightness.light : Brightness.dark,
            ),
            child: MediaQuery(
              data: MediaQuery.of(context).copyWith(
                textScaler: TextScaler.linear(TroikaConfig.textScale),
              ),
              child: child!,
            ),
          );
        },
        home: !_authenticated
            ? TroikaPageScope(
                child: AuthScreen(
                onAuthenticated: () => setState(() => _authenticated = true),
              ))
            : _onboarded
                ? HomeScreen(
                    onSignedOut: () => setState(() => _authenticated = false),
                    onAppearanceChanged: () => setState(() {}),
                  )
                : TroikaPageScope(
                    child: OnboardingScreen(
                    onDone: () => setState(() => _onboarded = true),
                  )),
      ),
    );
  }
}
