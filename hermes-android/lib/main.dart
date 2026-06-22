import 'dart:async';
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
  bool _onboarded = HermesConfig.onboardingDone;

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
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
