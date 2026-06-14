import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'config/hermes_config.dart';
import 'services/assistant_service.dart';
import 'screens/home_screen.dart';
import 'theme/troika_theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Инициализировать настройки (SharedPreferences)
  await HermesConfig.init();

  // Тёмный статус бар
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: Brightness.light,
    ),
  );

  runApp(const HermesApp());
}

class HermesApp extends StatelessWidget {
  const HermesApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (_) => AssistantService()..init(),
      child: MaterialApp(
        title: 'Тройка',
        debugShowCheckedModeBanner: false,
        theme: buildTroikaTheme(),
        home: const HomeScreen(),
      ),
    );
  }
}
