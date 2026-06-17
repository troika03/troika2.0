import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:permission_handler/permission_handler.dart';
import '../config/hermes_config.dart';

/// Экран первичной настройки Тройки «под ключ».
///
/// Сервер и ключ уже вшиты в дефолты ([HermesConfig.defaultServerUrl]).
/// Здесь пользователя проводят через системные разрешения, которые Android
/// нельзя выдать из кода: микрофон, спец-возможности (управление телефоном),
/// поверх других окон, отключение оптимизации батареи (для работы 24/7).
///
/// Каждый шаг показывает живой статус (✓/○): нажал «Выдать» → открылась нужная
/// системная страница → вернулся в приложение → статус сам перепроверяется
/// (через WidgetsBindingObserver на resume). Когда обязательные шаги выполнены —
/// кнопка «Готово» становится активной.
class OnboardingScreen extends StatefulWidget {
  final VoidCallback onDone;
  const OnboardingScreen({super.key, required this.onDone});

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen>
    with WidgetsBindingObserver {
  static const _channel = MethodChannel('com.troika.hermes/background');

  bool _mic = false;
  bool _accessibility = false;
  bool _overlay = false;
  bool _battery = false;
  bool _location = false;
  bool _locationBg = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _refresh();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Вернулись в приложение из системных настроек — перепроверяем статусы.
    if (state == AppLifecycleState.resumed) _refresh();
  }

  Future<bool> _ask(String method) async {
    try {
      final v = await _channel.invokeMethod<bool>(method);
      return v ?? false;
    } catch (_) {
      return false;
    }
  }

  Future<void> _refresh() async {
    final mic = await Permission.microphone.isGranted;
    final acc = await _ask('isAccessibilityEnabled');
    final ovl = await _ask('hasOverlayPermission');
    final bat = await _ask('isBatteryOptimizationIgnored');
    final loc = await _ask('hasLocationPermission');
    final locBg = await _ask('hasBackgroundLocation');
    if (!mounted) return;
    setState(() {
      _mic = mic;
      _accessibility = acc;
      _overlay = ovl;
      _battery = bat;
      _location = loc;
      _locationBg = locBg;
    });
  }

  Future<void> _grantMic() async {
    await Permission.microphone.request();
    await _refresh();
  }

  Future<void> _invoke(String method) async {
    try {
      await _channel.invokeMethod(method);
    } catch (_) {}
    // статус обновится сам на resume, но дёрнем и сразу для отзывчивости
    await Future.delayed(const Duration(milliseconds: 400));
    await _refresh();
  }

  // Обязательные для базовой работы: микрофон (слышать) + спец-возможности
  // (управлять телефоном, скриншоты). Остальное — желательное.
  bool get _requiredDone => _mic && _accessibility;

  void _finish() {
    HermesConfig.onboardingDone = true;
    widget.onDone();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 32, 24, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Настройка Тройки',
                  style: theme.textTheme.headlineSmall
                      ?.copyWith(fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              Text(
                'Сервер уже подключён ($_serverHint). Осталось выдать '
                'разрешения — без них Тройка не услышит тебя и не сможет '
                'управлять телефоном.',
                style: theme.textTheme.bodyMedium
                    ?.copyWith(color: Colors.white70),
              ),
              const SizedBox(height: 24),
              Expanded(
                child: ListView(
                  children: [
                    _Step(
                      icon: Icons.mic,
                      title: 'Микрофон',
                      subtitle: 'Чтобы слышать тебя и распознавать речь.',
                      done: _mic,
                      required_: true,
                      onTap: _grantMic,
                    ),
                    _Step(
                      icon: Icons.accessibility_new,
                      title: 'Спец-возможности',
                      subtitle:
                          'Управление телефоном: нажатия, свайпы, ввод, скриншоты. '
                          'Включи «Тройка» в списке.',
                      done: _accessibility,
                      required_: true,
                      onTap: () => _invoke('openAccessibilitySettings'),
                    ),
                    _Step(
                      icon: Icons.layers,
                      title: 'Поверх других окон',
                      subtitle:
                          'Чтобы всплывать поверх приложений во время диалога.',
                      done: _overlay,
                      required_: false,
                      onTap: () => _invoke('requestOverlayPermission'),
                    ),
                    _Step(
                      icon: Icons.battery_charging_full,
                      title: 'Работа в фоне 24/7',
                      subtitle:
                          'Отключить оптимизацию батареи, чтобы система не '
                          'усыпляла Тройку.',
                      done: _battery,
                      required_: false,
                      onTap: () => _invoke('requestBatteryOptimizationDisable'),
                    ),
                    _Step(
                      icon: Icons.my_location,
                      title: 'Местоположение',
                      subtitle:
                          'Чтобы Тройка знала где ты — погода рядом, места, '
                          'маршруты, «где я».',
                      done: _location,
                      required_: false,
                      onTap: () => _invoke('requestLocationPermission'),
                    ),
                    _Step(
                      icon: Icons.location_searching,
                      title: 'Местоположение в фоне',
                      subtitle:
                          'Видеть твоё место даже когда приложение свёрнуто. '
                          'В настройках выбери «Разрешать всегда». Сначала выдай '
                          'обычное местоположение выше.',
                      done: _locationBg,
                      required_: false,
                      onTap: () => _invoke('requestBackgroundLocation'),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 8),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: _requiredDone ? _finish : null,
                  style: FilledButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                  ),
                  child: Text(_requiredDone
                      ? 'Готово, поехали'
                      : 'Выдай микрофон и спец-возможности'),
                ),
              ),
              if (_requiredDone && !(_overlay && _battery))
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Center(
                    child: TextButton(
                      onPressed: _finish,
                      child: const Text('Пропустить необязательное'),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }

  String get _serverHint {
    final u = HermesConfig.serverUrl;
    return u.isEmpty ? 'не задан' : u.replaceFirst('http://', '');
  }
}

class _Step extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final bool done;
  final bool required_;
  final VoidCallback onTap;

  const _Step({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.done,
    required this.required_,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: ListTile(
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        leading: Icon(icon,
            color: done ? Colors.greenAccent : Colors.white70, size: 28),
        title: Row(
          children: [
            Flexible(
              child: Text(title,
                  style: theme.textTheme.titleMedium
                      ?.copyWith(fontWeight: FontWeight.w600)),
            ),
            if (required_ && !done)
              Container(
                margin: const EdgeInsets.only(left: 8),
                padding:
                    const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: Colors.orange.withValues(alpha: 0.25),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: const Text('нужно',
                    style: TextStyle(fontSize: 11, color: Colors.orange)),
              ),
          ],
        ),
        subtitle: Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text(subtitle,
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: Colors.white60)),
        ),
        trailing: done
            ? const Icon(Icons.check_circle, color: Colors.greenAccent)
            : FilledButton.tonal(
                onPressed: onTap,
                child: const Text('Выдать'),
              ),
      ),
    );
  }
}
