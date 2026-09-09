import 'dart:async';
import 'dart:io' show Platform;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'config/hermes_config.dart';
import 'services/assistant_service.dart';
import 'screens/home_screen.dart';
import 'screens/onboarding_screen.dart';
import 'theme/troika_theme.dart';
import 'services/thought_translator.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Инициализировать настройки (SharedPreferences)
  await HermesConfig.init();

  // Прогреть офлайн-переводчик мыслей EN->RU в фоне (разовая загрузка модели).
  unawaited(ThoughtTranslator.instance.warmUp());

  // Тёмный статус бар
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: Brightness.light,
    ),
  );

  runApp(const HermesApp());
}

class HermesApp extends StatefulWidget {
  const HermesApp({super.key});

  @override
  State<HermesApp> createState() => _HermesAppState();
}

class _HermesAppState extends State<HermesApp> {
  // Первый запуск показывает онбординг разрешений; после — сразу домой.
  // На десктопе (Windows/Linux/macOS) онбординг ПРОПУСКАЕТСЯ: его разрешения
  // (спец-возможности, поверх окон, фон, геолокация) — андроидные и на ПК не
  // применимы; микрофон запрашивается отдельно. Иначе пользователь застревает
  // на экране с неактивной кнопкой. Онбординг остаётся только для Android.
  bool _onboarded = HermesConfig.onboardingDone || !Platform.isAndroid;

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
        theme: buildTroikaTheme(),
        home: _onboarded
            ? const HomeScreen()
            : OnboardingScreen(
                onDone: () => setState(() => _onboarded = true),
              ),
      ),
    );
  }
}
