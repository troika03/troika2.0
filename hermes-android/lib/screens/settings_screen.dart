import '../widgets/troika_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../config/troika_config.dart';
import 'auth_screen.dart';
import '../services/assistant_service.dart';
import '../services/troika_api_service.dart';
import '../widgets/subscription_panel.dart';
import '../services/voice_presets.dart';

enum SettingsSection { advanced, permissions, account }

class SettingsScreen extends StatefulWidget {
  final VoidCallback? onSignedOut;
  final SettingsSection section;

  const SettingsScreen({
    super.key,
    this.onSignedOut,
    this.section = SettingsSection.advanced,
  });

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late TextEditingController _urlController;
  late TextEditingController _apiKeyController;
  bool _testing = false;
  String? _testResult;
  String _currentVoice = 'ru-RU-SvetlanaNeural';
  double _rate = 1.0; // 0.5..1.5 — скорость
  int _pitch = 0; // -50..+50 Hz — тон ("женственность" вверх)
  int _volume = 0; // -50..+50 % — громкость

  List<VoicePreset> _presets = [];
  String? _activePresetName;

  bool _bargeInEnabled = true;
  int _bargeInThreshold = 1200;
  bool _locationContextEnabled = false;
  bool _phoneControlEnabled = false;
  bool _exportingAccount = false;
  bool _deletingAccount = false;
  bool _loadingDevices = false;
  bool _loggingOutAll = false;
  String? _devicesError;
  String? _revokingDeviceId;
  List<AccountDevice> _accountDevices = const [];
  AccountSubscription? _subscription;
  String? _subscriptionError;
  bool _loadingSubscription = false;

  // Список доступных голосов Edge TTS с человекочитаемыми описаниями
  static const _voices = [
    {
      'id': 'ru-RU-SvetlanaNeural',
      'name': '🇷🇺 Светлана',
      'desc': 'Русская, женский, мягкий',
    },
    {
      'id': 'ru-RU-DmitryNeural',
      'name': '🇷🇺 Дмитрий',
      'desc': 'Русский, мужской, серьезный',
    },
    {
      'id': 'en-GB-RyanNeural',
      'name': '🇬🇧 Ryan',
      'desc': 'Британец, мужской, молодой',
    },
    {
      'id': 'en-GB-ThomasNeural',
      'name': '🇬🇧 Thomas',
      'desc': 'Британец, мужской, зрелый',
    },
    {
      'id': 'en-GB-SoniaNeural',
      'name': '🇬🇧 Sonia',
      'desc': 'Британка, женский, спокойная',
    },
    {
      'id': 'en-GB-LibbyNeural',
      'name': '🇬🇧 Libby',
      'desc': 'Британка, женский, энергичная',
    },
    {
      'id': 'en-US-AriaNeural',
      'name': '🇺🇸 Aria',
      'desc': 'Американка, женский, живая',
    },
    {
      'id': 'en-US-GuyNeural',
      'name': '🇺🇸 Guy',
      'desc': 'Американец, мужской, спокойный',
    },
  ];

  static const _channel = MethodChannel('com.troika.hermes/background');

  @override
  void initState() {
    super.initState();
    _urlController = TextEditingController(text: TroikaConfig.serverUrl);
    _apiKeyController = TextEditingController(text: TroikaConfig.apiKey);
    _loadCurrentVoice();
    _loadPresets();
    _loadBargeIn();
    _locationContextEnabled = TroikaConfig.locationContextEnabled;
    _phoneControlEnabled = TroikaConfig.phoneControlEnabled;
    if (TroikaConfig.signedIn) {
      _loadAccountDevices();
      _loadSubscription();
    }
  }

  Future<void> _loadSubscription() async {
    if (_loadingSubscription || !TroikaConfig.signedIn) return;
    setState(() {
      _loadingSubscription = true;
      _subscriptionError = null;
    });
    try {
      final subscription = await TroikaApiService().getSubscription();
      if (!mounted) return;
      setState(() => _subscription = subscription);
    } on TroikaApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _subscription = null;
        _subscriptionError = error.message;
      });
    } finally {
      if (mounted) setState(() => _loadingSubscription = false);
    }
  }

  Future<void> _loadBargeIn() async {
    final prefs = await SharedPreferences.getInstance();
    if (!mounted) return;
    setState(() {
      _bargeInEnabled =
          prefs.getBool('flutter.hermes_barge_in_enabled') ?? true;
      _bargeInThreshold =
          prefs.getInt('flutter.hermes_barge_in_threshold') ?? 1200;
    });
  }

  Future<void> _saveBargeInEnabled(bool v) async {
    setState(() => _bargeInEnabled = v);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('flutter.hermes_barge_in_enabled', v);
  }

  Future<void> _saveBargeInThreshold(int v) async {
    setState(() => _bargeInThreshold = v);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt('flutter.hermes_barge_in_threshold', v);
  }

  Future<void> _loadPresets() async {
    final list = await VoicePresets.load();
    final active = await VoicePresets.getActiveName();
    if (!mounted) return;

    // Проверка на первый запуск (если активен Claude и настройки по умолчанию)
    final wasFirstLaunch = active == 'Claude' &&
        list.any((p) => p.name == 'Claude') &&
        _currentVoice == 'ru-RU-SvetlanaNeural' &&
        _rate == 1.0 &&
        _pitch == 0 &&
        _volume == 0;

    setState(() {
      _presets = list;
      _activePresetName = active;
    });

    if (wasFirstLaunch) {
      final claude = list.firstWhere((p) => p.name == 'Claude');
      await _applyPreset(claude, showSnack: false);
    }
  }

  Future<void> _applyPreset(VoicePreset p, {bool showSnack = true}) async {
    setState(() {
      _currentVoice = p.voice;
      _rate = p.rate;
      _pitch = p.pitch;
      _volume = p.volume;
      _activePresetName = p.name;
    });
    try {
      await _channel.invokeMethod('setEdgeVoice', _voiceArgs(p.voice));
    } catch (_) {}
    await VoicePresets.setActiveName(p.name);
    if (showSnack && mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('Применен пресет «${p.name}»')));
    }
  }

  Future<void> _saveCurrentAsPreset() async {
    final name = await _askPresetName();
    if (name == null || name.trim().isEmpty) return;
    final preset = VoicePreset(
      name: name.trim(),
      voice: _currentVoice,
      rate: _rate,
      pitch: _pitch,
      volume: _volume,
    );
    final list = await VoicePresets.addOrUpdate(preset);
    await VoicePresets.setActiveName(preset.name);
    if (!mounted) return;
    setState(() {
      _presets = list;
      _activePresetName = preset.name;
    });
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text('Сохранен пресет «${preset.name}»')));
  }

  Future<void> _deletePreset(String name) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: TroikaPalette.of(context).surface,
        title: Text(
          'Удалить пресет?',
          style: TextStyle(color: TroikaPalette.of(context).text),
        ),
        content: Text(
          'Пресет «$name» будет удален.',
          style: TextStyle(color: TroikaPalette.of(context).textMuted),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: Text(
              'Отмена',
              style: TextStyle(color: TroikaPalette.of(context).textMuted),
            ),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(
              'Удалить',
              style: TextStyle(color: Color(0xFFE57373)),
            ),
          ),
        ],
      ),
    );
    if (confirm != true) return;
    final list = await VoicePresets.remove(name);
    if (!mounted) return;
    setState(() {
      _presets = list;
      if (_activePresetName == name) _activePresetName = null;
    });
  }

  Future<String?> _askPresetName() async {
    final controller = TextEditingController();
    return showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: TroikaPalette.of(context).surface,
        title: Text('Имя пресета',
            style: TextStyle(color: TroikaPalette.of(context).text)),
        content: TextField(
          controller: controller,
          autofocus: true,
          style: TextStyle(color: TroikaPalette.of(context).text),
          decoration: InputDecoration(
            hintText: 'Например: Мой голос',
            hintStyle: TextStyle(color: TroikaPalette.of(context).textMuted),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: Text(
              'Отмена',
              style: TextStyle(color: TroikaPalette.of(context).textMuted),
            ),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, controller.text),
            child: Text(
              'Сохранить',
              style: TextStyle(color: Theme.of(context).colorScheme.primary),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _loadCurrentVoice() async {
    try {
      final data = await _channel.invokeMethod('getEdgeVoice');
      if (data != null && mounted) {
        if (data is Map) {
          setState(() {
            _currentVoice =
                (data['voice'] as String?) ?? 'ru-RU-SvetlanaNeural';
            _rate = (data['rate'] as num?)?.toDouble() ?? 1.0;
            _pitch = (data['pitch'] as num?)?.toInt() ?? 0;
            _volume = (data['volume'] as num?)?.toInt() ?? 0;
          });
        } else if (data is String) {
          setState(() => _currentVoice = data);
        }
      }
    } catch (_) {}
  }

  Map<String, dynamic> _voiceArgs(String voice) => {
        'voice': voice,
        'rate': _rate,
        'pitch': _pitch,
        'volume': _volume,
      };

  Future<void> _previewVoice(String voice) async {
    try {
      await _channel.invokeMethod('previewEdgeVoice', _voiceArgs(voice));
    } catch (_) {}
  }

  Future<void> _previewCurrentSettings() async {
    try {
      await _channel.invokeMethod(
        'previewEdgeVoice',
        _voiceArgs(_currentVoice),
      );
    } catch (_) {}
  }

  Future<void> _selectVoice(String voice) async {
    setState(() => _currentVoice = voice);
    try {
      await _channel.invokeMethod('setEdgeVoice', _voiceArgs(voice));
    } catch (_) {}
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Голос обновлен, сервис перезапущен')),
      );
    }
  }

  Future<void> _applyVoiceSettings() async {
    try {
      await _channel.invokeMethod('setEdgeVoice', _voiceArgs(_currentVoice));
    } catch (_) {}
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Настройки голоса применены')),
      );
    }
  }

  Future<void> _resetVoiceSettings() async {
    setState(() {
      _rate = 1.0;
      _pitch = 0;
      _volume = 0;
    });
    await _applyVoiceSettings();
  }

  /// Нормализуем введённый новичком адрес: добавляем http:// и порт 8642,
  /// если их забыли. «1.2.3.4» → «http://1.2.3.4:8642».
  String _normalizeUrl(String raw) {
    var url = raw.trim();
    if (url.isEmpty) return url;
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = 'http://$url';
    }
    // Убираем хвостовой слэш
    url = url.replaceAll(RegExp(r'/+$'), '');
    // Если порт не указан — добавляем дефолтный 8642
    final hostPart = url.replaceFirst(RegExp(r'^https?://'), '');
    if (!hostPart.contains(':')) {
      url = '$url:8642';
    }
    return url;
  }

  Future<void> _testConnection() async {
    setState(() {
      _testing = true;
      _testResult = null;
    });

    final normalized = _normalizeUrl(_urlController.text);
    _urlController.text = normalized;
    TroikaConfig.serverUrl = normalized;
    TroikaConfig.apiKey = _apiKeyController.text.trim();

    final api = TroikaApiService();
    final ok = await api.checkConnection();

    setState(() {
      _testing = false;
      _testResult = ok
          ? '✅ Подключено к серверу!'
          : '❌ Не удалось подключиться. Проверь IP и что сервер запущен.';
    });
  }

  Future<void> _openAccessibilitySettings() async {
    const channel = MethodChannel('com.troika.hermes/background');
    try {
      await channel.invokeMethod('openAccessibilitySettings');
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Не удалось открыть настройки: $e')),
        );
      }
    }
  }

  Future<void> _requestAllFilesAccess() async {
    const channel = MethodChannel('com.troika.hermes/background');
    try {
      await channel.invokeMethod('requestAllFilesAccess');
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Не удалось открыть настройки: $e')),
        );
      }
    }
  }

  Future<void> _requestCalendarPermission() async {
    const channel = MethodChannel('com.troika.hermes/background');
    try {
      final has = await channel.invokeMethod('hasCalendarPermission');
      if (has == true) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Доступ к календарю уже разрешен')),
          );
        }
        return;
      }
      await channel.invokeMethod('requestCalendarPermission');
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Не удалось запросить доступ: $e')),
        );
      }
    }
  }

  Future<void> _requestLocationPermission() async {
    const channel = MethodChannel('com.troika.hermes/background');
    try {
      final has = await channel.invokeMethod('hasLocationPermission');
      if (has != true) {
        await channel.invokeMethod('requestLocationPermission');
        return;
      }
      // Обычное уже есть — предлагаем фоновое (через системные настройки).
      final bg = await channel.invokeMethod('hasBackgroundLocation');
      if (bg == true) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Местоположение уже разрешено (включая фон)'),
            ),
          );
        }
        return;
      }
      await channel.invokeMethod('requestBackgroundLocation');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Выбери «Разрешать всегда» в настройках приложения'),
            duration: Duration(seconds: 4),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Не удалось запросить доступ: $e')),
        );
      }
    }
  }

  Future<void> _setLocationContextEnabled(bool enabled) async {
    if (enabled) await _requestLocationPermission();
    await TroikaConfig.setLocationContextEnabled(enabled);
    if (!mounted) return;
    setState(() => _locationContextEnabled = enabled);
  }

  Future<void> _setPhoneControlEnabled(bool enabled) async {
    await TroikaConfig.setPhoneControlEnabled(enabled);
    if (!mounted) return;
    setState(() => _phoneControlEnabled = enabled);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          enabled
              ? 'Управление телефоном включено'
              : 'Управление телефоном выключено',
        ),
      ),
    );
  }

  void _save() {
    TroikaConfig.serverUrl = _normalizeUrl(_urlController.text);
    TroikaConfig.apiKey = _apiKeyController.text.trim();
    Navigator.pop(context);
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(const SnackBar(content: Text('Настройки сохранены')));
  }

  Future<void> _openAccountLogin() async {
    final authenticated = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (routeContext) => TroikaPageScope(
            child: AuthScreen(
          onAuthenticated: () => Navigator.of(routeContext).pop(true),
        )),
      ),
    );
    if (authenticated != true || !mounted) return;
    setState(() {
      _urlController.text = TroikaConfig.serverUrl;
      _apiKeyController.text = TroikaConfig.apiKey;
    });
    await _loadAccountDevices();
    await _loadSubscription();
  }

  Future<void> _loadAccountDevices() async {
    if (!TroikaConfig.signedIn || _loadingDevices) return;
    setState(() {
      _loadingDevices = true;
      _devicesError = null;
    });
    try {
      final devices = await TroikaApiService().listAccountDevices();
      if (!mounted) return;
      setState(() => _accountDevices = devices);
    } on TroikaApiException catch (error) {
      if (!mounted) return;
      if (error.statusCode == 401) {
        await _finishRevokedSession();
        return;
      }
      if (!mounted) return;
      setState(() => _devicesError = error.message);
    } catch (_) {
      if (!mounted) return;
      setState(() => _devicesError = 'Не удалось загрузить устройства.');
    } finally {
      if (mounted) setState(() => _loadingDevices = false);
    }
  }

  Future<void> _finishRevokedSession([AssistantService? assistant]) async {
    final liveAssistant = assistant ?? context.read<AssistantService>();
    try {
      await liveAssistant.setWakeWordEnabled(false);
    } catch (error) {
      debugPrint('[Settings] Failed to stop wake listener: $error');
    }
    await TroikaConfig.clearRevokedDevice();
    if (!mounted) return;
    Navigator.of(context).pop();
    widget.onSignedOut?.call();
  }

  Future<void> _revokeAccountDevice(
    AccountDevice device,
    AssistantService assistant,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: TroikaPalette.of(context).surface,
        title: Text(
          device.current ? 'Выйти на этом устройстве?' : 'Отозвать устройство?',
          style: TextStyle(color: TroikaPalette.of(context).text),
        ),
        content: Text(
          device.current
              ? 'Текущий сеанс завершится. Для облачных функций потребуется войти снова.'
              : '«${device.name}» сразу потеряет доступ к аккаунту, задачам и управлению.',
          style: TextStyle(
              color: TroikaPalette.of(context).textMuted, height: 1.4),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Отмена'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: Text(
              device.current ? 'Выйти' : 'Отозвать',
              style: const TextStyle(color: Color(0xFFE57373)),
            ),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() => _revokingDeviceId = device.id);
    try {
      final result = await TroikaApiService().revokeAccountDevice(device.id);
      if (result.current || result.reauthenticationRequired) {
        await _finishRevokedSession(assistant);
        return;
      }
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Доступ «${device.name}» отозван')),
      );
      await _loadAccountDevices();
    } on TroikaApiException catch (error) {
      if (error.statusCode == 401) {
        await _finishRevokedSession(assistant);
        return;
      }
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error.message)),
      );
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Не удалось отозвать устройство.')),
      );
    } finally {
      if (mounted) setState(() => _revokingDeviceId = null);
    }
  }

  Future<void> _logoutAllDevices(AssistantService assistant) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: TroikaPalette.of(context).surface,
        title: Text(
          'Выйти на всех устройствах?',
          style: TextStyle(color: TroikaPalette.of(context).text),
        ),
        content: Text(
          'Все телефоны и компьютеры сразу потеряют доступ. Войти потребуется заново.',
          style: TextStyle(
              color: TroikaPalette.of(context).textMuted, height: 1.4),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Отмена'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text(
              'Выйти везде',
              style: TextStyle(color: Color(0xFFE57373)),
            ),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _loggingOutAll = true);
    try {
      await TroikaApiService().logoutAllDevices();
      await _finishRevokedSession(assistant);
    } on TroikaApiException catch (error) {
      if (error.statusCode == 401) {
        await _finishRevokedSession(assistant);
        return;
      }
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error.message)),
      );
    } finally {
      if (mounted) setState(() => _loggingOutAll = false);
    }
  }

  String _deviceSubtitle(AccountDevice device) {
    final platform = switch (device.platform) {
      'android' => 'Android',
      'windows' => 'Windows',
      'ios' => 'iOS',
      'macos' => 'macOS',
      'linux' => 'Linux',
      'web' => 'Web',
      _ => device.platform,
    };
    if (!device.active) return '$platform · доступ отозван';
    if (device.current) return '$platform · это устройство';
    final local = device.createdAt.toLocal();
    final date = '${local.day.toString().padLeft(2, '0')}.'
        '${local.month.toString().padLeft(2, '0')}.${local.year}';
    return '$platform · добавлено $date';
  }

  Widget _deviceManagementSection(AssistantService assistant) {
    if (_loadingDevices && _accountDevices.isEmpty) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 20),
        child: Center(
          child: SizedBox(
            width: 22,
            height: 22,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
        ),
      );
    }
    if (_devicesError != null && _accountDevices.isEmpty) {
      return Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: TroikaPalette.of(context).surface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: TroikaPalette.of(context).line),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              _devicesError!,
              style: TextStyle(
                  color: TroikaPalette.of(context).textMuted, height: 1.4),
            ),
            const SizedBox(height: 8),
            TextButton.icon(
              onPressed: _loadAccountDevices,
              icon: const Icon(Icons.refresh, size: 18),
              label: const Text('Повторить'),
            ),
          ],
        ),
      );
    }
    if (_accountDevices.isEmpty) {
      return Text(
        'Подключённые устройства пока не найдены.',
        style:
            TextStyle(color: TroikaPalette.of(context).textMuted, fontSize: 13),
      );
    }
    return Container(
      decoration: BoxDecoration(
        color: TroikaPalette.of(context).surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: TroikaPalette.of(context).line),
      ),
      child: Column(
        children: [
          for (var index = 0; index < _accountDevices.length; index++) ...[
            if (index > 0)
              Divider(
                  height: 1, indent: 56, color: TroikaPalette.of(context).line),
            ListTile(
              minVerticalPadding: 12,
              leading: Icon(
                _accountDevices[index].platform == 'android'
                    ? Icons.phone_android
                    : Icons.devices_outlined,
                color: _accountDevices[index].current
                    ? Theme.of(context).colorScheme.primary
                    : TroikaPalette.of(context).textMuted,
              ),
              title: Text(
                _accountDevices[index].name,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(color: TroikaPalette.of(context).textMuted),
              ),
              subtitle: Text(
                _deviceSubtitle(_accountDevices[index]),
                style: TextStyle(
                    color: TroikaPalette.of(context).textMuted, fontSize: 12),
              ),
              trailing: _accountDevices[index].active
                  ? IconButton(
                      constraints: const BoxConstraints(
                        minWidth: 48,
                        minHeight: 48,
                      ),
                      tooltip: _accountDevices[index].current
                          ? 'Выйти на этом устройстве'
                          : 'Отозвать доступ',
                      onPressed: _revokingDeviceId == null
                          ? () => _revokeAccountDevice(
                                _accountDevices[index],
                                assistant,
                              )
                          : null,
                      icon: _revokingDeviceId == _accountDevices[index].id
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(
                              Icons.logout,
                              color: Color(0xFFE57373),
                            ),
                    )
                  : const SizedBox(width: 48),
            ),
          ],
        ],
      ),
    );
  }

  Future<void> _exportAccountData() async {
    setState(() => _exportingAccount = true);
    try {
      final saved = await TroikaApiService().exportAccountData();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            saved ? 'Архив данных сохранён' : 'Сохранение экспорта отменено',
          ),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error.toString())),
      );
    } finally {
      if (mounted) setState(() => _exportingAccount = false);
    }
  }

  Future<void> _deleteAccount(AssistantService assistant) async {
    final confirmationController = TextEditingController();
    var exactConfirmation = false;
    final confirmed = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          backgroundColor: TroikaPalette.of(context).surface,
          title: Text(
            'Удалить аккаунт?',
            style: TextStyle(color: TroikaPalette.of(context).text),
          ),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Сервер удалит историю диалогов, проекты, задачи, напоминания, '
                'документы и данные устройства. Отменить это нельзя. Копии '
                'файлов, уже сохранённые на телефоне, останутся.',
                style: TextStyle(
                    color: TroikaPalette.of(context).textMuted, height: 1.4),
              ),
              const SizedBox(height: 16),
              Text(
                'Для подтверждения введи УДАЛИТЬ',
                style: TextStyle(
                    color: TroikaPalette.of(context).textMuted, fontSize: 12),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: confirmationController,
                autofocus: true,
                style: TextStyle(color: TroikaPalette.of(context).text),
                onChanged: (value) => setDialogState(
                  () => exactConfirmation = value.trim() == 'УДАЛИТЬ',
                ),
                decoration: const InputDecoration(hintText: 'УДАЛИТЬ'),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Отмена'),
            ),
            TextButton(
              onPressed: exactConfirmation
                  ? () => Navigator.pop(dialogContext, true)
                  : null,
              child: const Text(
                'Удалить навсегда',
                style: TextStyle(color: Color(0xFFE57373)),
              ),
            ),
          ],
        ),
      ),
    );
    confirmationController.dispose();
    if (confirmed != true || !mounted) return;

    setState(() => _deletingAccount = true);
    try {
      final completed = await TroikaApiService().deleteAccount();
      await assistant.setWakeWordEnabled(false);
      await TroikaConfig.clearDeletedAccount();
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (dialogContext) => AlertDialog(
          backgroundColor: TroikaPalette.of(context).surface,
          title: Text(
            completed ? 'Аккаунт удалён' : 'Удаление принято',
            style: TextStyle(color: TroikaPalette.of(context).text),
          ),
          content: Text(
            completed
                ? 'Данные удалены, доступ устройства отозван.'
                : 'Доступ уже отозван. Сервер завершит очистку автоматически.',
            style: TextStyle(color: TroikaPalette.of(context).textMuted),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Закрыть приложение'),
            ),
          ],
        ),
      );
      await SystemNavigator.pop();
    } catch (error) {
      if (!mounted) return;
      setState(() => _deletingAccount = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error.toString())),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final assistant = context.watch<AssistantService>();
    final title = switch (widget.section) {
      SettingsSection.advanced => 'Дополнительно',
      SettingsSection.permissions => 'Разрешения',
      SettingsSection.account => 'Аккаунт и данные',
    };

    return TroikaPage(
      backgroundColor: TroikaPalette.of(context).bg,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        title: Text(
          title,
          style: TextStyle(color: TroikaPalette.of(context).textMuted),
        ),
        iconTheme: IconThemeData(color: TroikaPalette.of(context).textMuted),
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          if (widget.section == SettingsSection.advanced) ...[
            _sectionHeader('Подключение к серверу'),
            Text(
              'IP-адрес или домен твоего сервера (вид: http://1.2.3.4:8642)',
              style: TextStyle(
                  color: TroikaPalette.of(context).textMuted, fontSize: 12),
            ),
            const SizedBox(height: 8),
            _inputField(
              controller: _urlController,
              label: 'URL сервера',
              hint: 'http://1.2.3.4:8642',
            ),
            const SizedBox(height: 12),
            _inputField(
              controller: _apiKeyController,
              label: 'API ключ',
              hint: 'Ключ, созданный для твоего сервера',
              obscure: true,
            ),
            const SizedBox(height: 4),
            Text(
              'Создай на сервере: openssl rand -hex 32 (API_SERVER_KEY)',
              style: TextStyle(
                  color: TroikaPalette.of(context).textMuted, fontSize: 11),
            ),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              onPressed: _testing ? null : _testConnection,
              style: OutlinedButton.styleFrom(
                foregroundColor: Theme.of(context).colorScheme.primary,
                side: BorderSide(color: Theme.of(context).colorScheme.primary),
              ),
              icon: _testing
                  ? const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.wifi_tethering, size: 16),
              label: Text(_testing ? 'Проверяю...' : 'Проверить соединение'),
            ),
            if (_testResult != null) ...[
              const SizedBox(height: 8),
              Text(
                _testResult!,
                style: TextStyle(
                    color: TroikaPalette.of(context).textMuted, fontSize: 13),
              ),
            ],
            const SizedBox(height: 24),
            Divider(color: TroikaPalette.of(context).line),
            const SizedBox(height: 16),
            _sectionHeader('Wake-word'),
            SwitchListTile(
              title: Text(
                'Слушать "Тройка" в фоне',
                style: TextStyle(color: TroikaPalette.of(context).textMuted),
              ),
              subtitle: Text(
                'Работает в фоне, расходует заряд',
                style: TextStyle(
                    color: TroikaPalette.of(context).textMuted, fontSize: 12),
              ),
              value: assistant.wakeWordEnabled,
              onChanged: (v) => assistant.setWakeWordEnabled(v),
              activeThumbColor: Theme.of(context).colorScheme.primary,
            ),
            const SizedBox(height: 24),
            Divider(color: TroikaPalette.of(context).line),
            const SizedBox(height: 16),
            _sectionHeader('Пресеты голоса'),
            if (_presets.isNotEmpty)
              Container(
                height: 90,
                margin: const EdgeInsets.only(bottom: 12),
                child: ListView.builder(
                  scrollDirection: Axis.horizontal,
                  itemCount: _presets.length,
                  itemBuilder: (ctx, i) {
                    final p = _presets[i];
                    final isActive = _activePresetName == p.name;
                    return GestureDetector(
                      onTap: () => _applyPreset(p),
                      onLongPress: () => _deletePreset(p.name),
                      child: Container(
                        width: 140,
                        margin: const EdgeInsets.only(right: 12, bottom: 4),
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: isActive
                              ? TroikaPalette.of(context).tint
                              : TroikaPalette.of(context).surface,
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(
                            color: isActive
                                ? Theme.of(context).colorScheme.primary
                                : TroikaPalette.of(context).line,
                            width: 1.5,
                          ),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                Expanded(
                                  child: Text(
                                    p.name,
                                    style: TextStyle(
                                      color: isActive
                                          ? TroikaPalette.of(context).text
                                          : TroikaPalette.of(context).textMuted,
                                      fontSize: 14,
                                      fontWeight: isActive
                                          ? FontWeight.w600
                                          : FontWeight.normal,
                                    ),
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ),
                                if (isActive)
                                  Icon(
                                    Icons.check_circle,
                                    color:
                                        Theme.of(context).colorScheme.primary,
                                    size: 14,
                                  ),
                              ],
                            ),
                            const Spacer(),
                            Text(
                              '${p.rate}x / ${p.pitch}Hz',
                              style: TextStyle(
                                color: TroikaPalette.of(context).textMuted,
                                fontSize: 10,
                              ),
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
              ),
            OutlinedButton.icon(
              onPressed: _saveCurrentAsPreset,
              style: OutlinedButton.styleFrom(
                foregroundColor: TroikaPalette.of(context).textMuted,
                side: BorderSide(color: TroikaPalette.of(context).line),
                minimumSize: const Size(double.infinity, 45),
              ),
              icon: const Icon(Icons.add_circle_outline, size: 18),
              label: const Text('Сохранить текущие настройки как пресет'),
            ),
            const SizedBox(height: 6),
            Text(
              'Тап — применить, долгий тап — удалить.',
              style: TextStyle(
                  color: TroikaPalette.of(context).textMuted, fontSize: 11),
            ),
            const SizedBox(height: 24),
            Divider(color: TroikaPalette.of(context).line),
            const SizedBox(height: 16),
            _sectionHeader('Голос Тройки'),
            Text(
              'Слушай образец и выбирай. Edge TTS на PC, играет на телефоне.',
              style: TextStyle(
                  color: TroikaPalette.of(context).textMuted,
                  fontSize: 13,
                  height: 1.5),
            ),
            const SizedBox(height: 12),
            ..._voices.map((v) {
              final isSelected = v['id'] == _currentVoice;
              return Container(
                margin: const EdgeInsets.only(bottom: 8),
                decoration: BoxDecoration(
                  color: isSelected
                      ? TroikaPalette.of(context).tint
                      : TroikaPalette.of(context).surface,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(
                    color: isSelected
                        ? Theme.of(context).colorScheme.primary
                        : Colors.transparent,
                    width: 1.5,
                  ),
                ),
                child: ListTile(
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 4,
                  ),
                  title: Text(
                    v['name']!,
                    style: TextStyle(
                      color: TroikaPalette.of(context).text,
                      fontSize: 14,
                      fontWeight:
                          isSelected ? FontWeight.w600 : FontWeight.normal,
                    ),
                  ),
                  subtitle: Text(
                    v['desc']!,
                    style: TextStyle(
                        color: TroikaPalette.of(context).textMuted,
                        fontSize: 12),
                  ),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      IconButton(
                        icon: Icon(
                          Icons.play_circle_outline,
                          color: TroikaPalette.of(context).textMuted,
                        ),
                        tooltip: 'Прослушать',
                        onPressed: () => _previewVoice(v['id']!),
                      ),
                      if (isSelected)
                        Padding(
                          padding: EdgeInsets.only(left: 4),
                          child: Icon(
                            Icons.check_circle,
                            color: Theme.of(context).colorScheme.primary,
                          ),
                        ),
                    ],
                  ),
                  onTap: () => _selectVoice(v['id']!),
                ),
              );
            }),
            const SizedBox(height: 16),
            _sectionHeader('Настройки звучания'),
            Text(
              'Жми "Прослушать" чтобы услышать как звучит с этими настройками. '
              'Чтобы голос звучал более женственно — увеличий тон.',
              style: TextStyle(
                  color: TroikaPalette.of(context).textMuted,
                  fontSize: 12,
                  height: 1.4),
            ),
            const SizedBox(height: 8),
            _sliderRow(
              label: 'Скорость',
              value: _rate,
              min: 0.5,
              max: 1.5,
              divisions: 20,
              display: '${_rate.toStringAsFixed(2)}x',
              onChanged: (v) =>
                  setState(() => _rate = double.parse(v.toStringAsFixed(2))),
            ),
            _sliderRow(
              label: 'Тон (питч)',
              value: _pitch.toDouble(),
              min: -50,
              max: 50,
              divisions: 20,
              display: '${_pitch >= 0 ? "+" : ""}$_pitch Гц',
              onChanged: (v) => setState(() => _pitch = v.toInt()),
            ),
            _sliderRow(
              label: 'Громкость',
              value: _volume.toDouble(),
              min: -50,
              max: 50,
              divisions: 20,
              display: '${_volume >= 0 ? "+" : ""}$_volume%',
              onChanged: (v) => setState(() => _volume = v.toInt()),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: _previewCurrentSettings,
                    style: OutlinedButton.styleFrom(
                      foregroundColor: Theme.of(context).colorScheme.primary,
                      side: BorderSide(
                          color: Theme.of(context).colorScheme.primary),
                    ),
                    icon: const Icon(Icons.play_arrow, size: 16),
                    label: const Text('Прослушать'),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: _applyVoiceSettings,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Theme.of(context).colorScheme.primary,
                    ),
                    icon: const Icon(Icons.check, size: 16),
                    label: const Text('Применить'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            TextButton.icon(
              onPressed: _resetVoiceSettings,
              style: TextButton.styleFrom(
                  foregroundColor: TroikaPalette.of(context).textMuted),
              icon: const Icon(Icons.refresh, size: 14),
              label: const Text(
                'Сбросить к дефолтам',
                style: TextStyle(fontSize: 12),
              ),
            ),
            const SizedBox(height: 16),
            Divider(color: TroikaPalette.of(context).line),
            const SizedBox(height: 16),
            _sectionHeader('Прерывание речи (barge-in)'),
            SwitchListTile(
              title: Text(
                'Замолкать когда я говорю',
                style: TextStyle(color: TroikaPalette.of(context).textMuted),
              ),
              subtitle: Text(
                'Тройка обрывает свой ответ как только слышит твой голос',
                style: TextStyle(
                    color: TroikaPalette.of(context).textMuted, fontSize: 12),
              ),
              value: _bargeInEnabled,
              onChanged: _saveBargeInEnabled,
              activeThumbColor: Theme.of(context).colorScheme.primary,
              contentPadding: EdgeInsets.zero,
            ),
            if (_bargeInEnabled) ...[
              const SizedBox(height: 4),
              _sliderRow(
                label: 'Чувствительность',
                value: _bargeInThreshold.toDouble(),
                min: 600,
                max: 2400,
                divisions: 18,
                display: _bargeInThreshold <= 900
                    ? '$_bargeInThreshold (высокая)'
                    : _bargeInThreshold >= 1800
                        ? '$_bargeInThreshold (низкая)'
                        : '$_bargeInThreshold (средняя)',
                onChanged: (v) => _saveBargeInThreshold(v.toInt()),
              ),
              Text(
                'Меньше = срабатывает на любой шорох (включая шум). '
                'Больше = только когда говоришь явно.',
                style: TextStyle(
                  color: TroikaPalette.of(context).textMuted,
                  fontSize: 11,
                  height: 1.4,
                ),
              ),
            ],
            const SizedBox(height: 16),
            Divider(color: TroikaPalette.of(context).line),
            const SizedBox(height: 16),
          ],
          if (widget.section != SettingsSection.account) ...[
            _sectionHeader('Управление телефоном'),
            Text(
              'Разреши Тройке принимать команды только от твоего '
              'авторизованного сервера. Можно отключить в любой момент.',
              style: TextStyle(
                  color: TroikaPalette.of(context).textMuted,
                  fontSize: 13,
                  height: 1.5),
            ),
            SwitchListTile(
              title: Text(
                'Разрешить управление телефоном',
                style: TextStyle(color: TroikaPalette.of(context).textMuted),
              ),
              subtitle: Text(
                'По умолчанию выключено. Опасные действия всё равно требуют '
                'отдельного подтверждения.',
                style: TextStyle(
                    color: TroikaPalette.of(context).textMuted, fontSize: 12),
              ),
              value: _phoneControlEnabled,
              onChanged: _setPhoneControlEnabled,
              activeThumbColor: Theme.of(context).colorScheme.primary,
              contentPadding: EdgeInsets.zero,
            ),
            const SizedBox(height: 8),
            Text(
              'Для нажатий, свайпов и ввода текста дополнительно включи '
              'Тройку в Спец. возможностях Android.',
              style: TextStyle(
                  color: TroikaPalette.of(context).textMuted,
                  fontSize: 13,
                  height: 1.5),
            ),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              onPressed: _openAccessibilitySettings,
              style: OutlinedButton.styleFrom(
                foregroundColor: Theme.of(context).colorScheme.primary,
                side: BorderSide(color: Theme.of(context).colorScheme.primary),
              ),
              icon: const Icon(Icons.accessibility_new, size: 18),
              label: const Text('Открыть спец. возможности'),
            ),
            const SizedBox(height: 24),
            Divider(color: TroikaPalette.of(context).line),
            const SizedBox(height: 16),
            _sectionHeader('Файловая система'),
            Text(
              'По умолчанию Тройка видит общедоступные папки: Downloads, '
              'Documents, Pictures, Music, Movies, DCIM. '
              'Если нужен доступ ко ВСЕМ файлам телефона (включая файлы '
              'других приложений) — дай разрешение "All files access".',
              style: TextStyle(
                  color: TroikaPalette.of(context).textMuted,
                  fontSize: 13,
                  height: 1.5),
            ),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              onPressed: _requestAllFilesAccess,
              style: OutlinedButton.styleFrom(
                foregroundColor: Theme.of(context).colorScheme.primary,
                side: BorderSide(color: Theme.of(context).colorScheme.primary),
              ),
              icon: const Icon(Icons.folder_open, size: 18),
              label: const Text('Открыть доступ ко всем файлам'),
            ),
            const SizedBox(height: 24),
            Divider(color: TroikaPalette.of(context).line),
            const SizedBox(height: 16),
            _sectionHeader('Календарь'),
            Text(
              'Чтобы Тройка мог ставить встречи и читать события из '
              'системного календаря (Google / Samsung / Outlook), '
              'разреши доступ.',
              style: TextStyle(
                  color: TroikaPalette.of(context).textMuted,
                  fontSize: 13,
                  height: 1.5),
            ),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              onPressed: _requestCalendarPermission,
              style: OutlinedButton.styleFrom(
                foregroundColor: Theme.of(context).colorScheme.primary,
                side: BorderSide(color: Theme.of(context).colorScheme.primary),
              ),
              icon: const Icon(Icons.event_available, size: 18),
              label: const Text('Разрешить доступ к календарю'),
            ),
            const SizedBox(height: 16),
            Divider(color: TroikaPalette.of(context).line),
            const SizedBox(height: 16),
            _sectionHeader('Местоположение'),
            Text(
              'Только после включения Тройка получает GPS, Wi-Fi и Bluetooth '
              'контекст вместе с запросами. Разрешение Android само ничего не отправляет.',
              style: TextStyle(
                  color: TroikaPalette.of(context).textMuted,
                  fontSize: 13,
                  height: 1.5),
            ),
            const SizedBox(height: 12),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(
                'Передавать контекст местоположения',
                style: TextStyle(color: TroikaPalette.of(context).textMuted),
              ),
              subtitle: Text(
                'Выключение останавливает передачу и очищает временный контекст на сервере.',
                style: TextStyle(
                    color: TroikaPalette.of(context).textMuted, fontSize: 12),
              ),
              value: _locationContextEnabled,
              activeThumbColor: Theme.of(context).colorScheme.primary,
              onChanged: _setLocationContextEnabled,
            ),
            OutlinedButton.icon(
              onPressed: _requestLocationPermission,
              style: OutlinedButton.styleFrom(
                foregroundColor: Theme.of(context).colorScheme.primary,
                side: BorderSide(color: Theme.of(context).colorScheme.primary),
              ),
              icon: const Icon(Icons.my_location, size: 18),
              label: const Text('Разрешить местоположение'),
            ),
          ],
          if (widget.section == SettingsSection.account &&
              !TroikaConfig.signedIn) ...[
            Text(
              'Аккаунт не подключён. Войди в Тройку, чтобы история, задачи '
              'и файлы были одинаковыми на телефоне и Windows.',
              style: TextStyle(
                  color: TroikaPalette.of(context).textMuted,
                  fontSize: 13,
                  height: 1.5),
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: _openAccountLogin,
              icon: const Icon(Icons.login),
              label: const Text('Войти в аккаунт'),
            ),
          ],
          if (widget.section != SettingsSection.permissions &&
              TroikaConfig.apiKey.startsWith('trk_live_')) ...[
            const SizedBox(height: 24),
            Divider(color: TroikaPalette.of(context).line),
            const SizedBox(height: 16),
            _sectionHeader('Аккаунт'),
            if (TroikaConfig.accountEmail.isNotEmpty) ...[
              Text(
                TroikaConfig.accountEmail,
                style: TextStyle(
                  color: TroikaPalette.of(context).textMuted,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 8),
            ],
            if (_loadingSubscription)
              const LinearProgressIndicator(minHeight: 2)
            else if (_subscription != null) ...[
              SubscriptionUsageView(subscription: _subscription!),
              TextButton.icon(
                onPressed: _loadSubscription,
                icon: const Icon(Icons.refresh_rounded),
                label: const Text('Обновить лимиты'),
              ),
              const SizedBox(height: 8),
            ] else if (_subscriptionError != null) ...[
              Text(
                _subscriptionError!,
                style: TextStyle(
                    color: TroikaPalette.of(context).textMuted, fontSize: 13),
              ),
              TextButton(
                onPressed: _loadSubscription,
                child: const Text('Повторить'),
              ),
            ],
            Text(
              'Устройства',
              style: TextStyle(
                color: TroikaPalette.of(context).textMuted,
                fontSize: 15,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 8),
            _deviceManagementSection(assistant),
            const SizedBox(height: 8),
            TextButton.icon(
              onPressed:
                  _loggingOutAll ? null : () => _logoutAllDevices(assistant),
              icon: _loggingOutAll
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.logout),
              label: Text(
                _loggingOutAll
                    ? 'Завершаю сеансы…'
                    : 'Выйти на всех устройствах',
              ),
              style: TextButton.styleFrom(
                foregroundColor: const Color(0xFFE57373),
              ),
            ),
            const SizedBox(height: 20),
            Text(
              'Сначала можно сохранить ZIP со всеми переносимыми данными и '
              'личными файлами. Удаление отзывает доступ всех устройств и '
              'стирает серверную историю, проекты, задачи, напоминания и документы.',
              style: TextStyle(
                  color: TroikaPalette.of(context).textMuted,
                  fontSize: 13,
                  height: 1.5),
            ),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              onPressed: _exportingAccount || _deletingAccount
                  ? null
                  : _exportAccountData,
              style: OutlinedButton.styleFrom(
                foregroundColor: Theme.of(context).colorScheme.primary,
                side: BorderSide(color: Theme.of(context).colorScheme.primary),
              ),
              icon: _exportingAccount
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.archive_outlined, size: 18),
              label: Text(
                _exportingAccount ? 'Создаю архив...' : 'Экспортировать данные',
              ),
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed:
                  _deletingAccount ? null : () => _deleteAccount(assistant),
              style: OutlinedButton.styleFrom(
                foregroundColor: const Color(0xFFE57373),
                side: const BorderSide(color: Color(0xFFE57373)),
              ),
              icon: _deletingAccount
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.delete_forever, size: 18),
              label: Text(
                _deletingAccount ? 'Удаляю...' : 'Удалить аккаунт и данные',
              ),
            ),
          ],
          if (widget.section != SettingsSection.account) ...[
            const SizedBox(height: 24),
            ElevatedButton(
              onPressed: _save,
              style: ElevatedButton.styleFrom(
                backgroundColor: Theme.of(context).colorScheme.primary,
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
              ),
              child: const Text(
                'Сохранить',
                style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _sliderRow({
    required String label,
    required double value,
    required double min,
    required double max,
    required int divisions,
    required String display,
    required ValueChanged<double> onChanged,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                label,
                style: TextStyle(
                    color: TroikaPalette.of(context).textMuted, fontSize: 13),
              ),
              Text(
                display,
                style: TextStyle(
                  color: Theme.of(context).colorScheme.primary,
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
          SliderTheme(
            data: SliderTheme.of(context).copyWith(
              activeTrackColor: Theme.of(context).colorScheme.primary,
              inactiveTrackColor: TroikaPalette.of(context).line,
              thumbColor: Theme.of(context).colorScheme.primary,
              overlayColor: const Color(0x337C6AF7),
              valueIndicatorColor: Theme.of(context).colorScheme.primary,
            ),
            child: Slider(
              value: value.clamp(min, max),
              min: min,
              max: max,
              divisions: divisions,
              label: display,
              onChanged: onChanged,
            ),
          ),
        ],
      ),
    );
  }

  Widget _sectionHeader(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Text(
        text,
        style: TextStyle(
          color: Theme.of(context).colorScheme.primary,
          fontSize: 12,
          fontWeight: FontWeight.w600,
          letterSpacing: 1.5,
        ),
      ),
    );
  }

  Widget _inputField({
    required TextEditingController controller,
    required String label,
    String? hint,
    bool obscure = false,
  }) {
    return TextField(
      controller: controller,
      obscureText: obscure,
      style: TextStyle(color: TroikaPalette.of(context).text, fontSize: 14),
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        labelStyle: TextStyle(color: TroikaPalette.of(context).textMuted),
        hintStyle: TextStyle(color: TroikaPalette.of(context).textMuted),
        filled: true,
        fillColor: TroikaPalette.of(context).surface,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: BorderSide.none,
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: BorderSide(color: Theme.of(context).colorScheme.primary),
        ),
      ),
    );
  }

  @override
  void dispose() {
    _urlController.dispose();
    _apiKeyController.dispose();
    super.dispose();
  }
}
