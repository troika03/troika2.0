import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../config/hermes_config.dart';
import '../services/assistant_service.dart';
import '../services/hermes_api_service.dart';
import '../services/voice_presets.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

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
    _urlController = TextEditingController(text: HermesConfig.serverUrl);
    _apiKeyController = TextEditingController(text: HermesConfig.apiKey);
    _loadCurrentVoice();
    _loadPresets();
    _loadBargeIn();
    _locationContextEnabled = HermesConfig.locationContextEnabled;
    _phoneControlEnabled = HermesConfig.phoneControlEnabled;
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
        backgroundColor: const Color(0xFF17150F),
        title: const Text(
          'Удалить пресет?',
          style: TextStyle(color: Colors.white),
        ),
        content: Text(
          'Пресет «$name» будет удален.',
          style: const TextStyle(color: Colors.white70),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text(
              'Отмена',
              style: TextStyle(color: Colors.white54),
            ),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text(
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
        backgroundColor: const Color(0xFF17150F),
        title: const Text('Имя пресета', style: TextStyle(color: Colors.white)),
        content: TextField(
          controller: controller,
          autofocus: true,
          style: const TextStyle(color: Colors.white),
          decoration: const InputDecoration(
            hintText: 'Например: Мой голос',
            hintStyle: TextStyle(color: Colors.white24),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text(
              'Отмена',
              style: TextStyle(color: Colors.white54),
            ),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, controller.text),
            child: const Text(
              'Сохранить',
              style: TextStyle(color: Color(0xFFF5A623)),
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
    HermesConfig.serverUrl = normalized;
    HermesConfig.apiKey = _apiKeyController.text.trim();

    final api = HermesApiService();
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
    await HermesConfig.setLocationContextEnabled(enabled);
    if (!mounted) return;
    setState(() => _locationContextEnabled = enabled);
  }

  Future<void> _setPhoneControlEnabled(bool enabled) async {
    await HermesConfig.setPhoneControlEnabled(enabled);
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
    HermesConfig.serverUrl = _normalizeUrl(_urlController.text);
    HermesConfig.apiKey = _apiKeyController.text.trim();
    Navigator.pop(context);
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(const SnackBar(content: Text('Настройки сохранены')));
  }

  @override
  Widget build(BuildContext context) {
    final assistant = context.watch<AssistantService>();

    return Scaffold(
      backgroundColor: const Color(0xFF0C0B0A),
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        title: const Text('Настройки', style: TextStyle(color: Colors.white70)),
        iconTheme: const IconThemeData(color: Colors.white38),
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          _sectionHeader('Подключение к серверу'),
          const Text(
            'IP-адрес или домен твоего сервера (вид: http://1.2.3.4:8642)',
            style: TextStyle(color: Colors.white38, fontSize: 12),
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
          const Text(
            'Создай на сервере: openssl rand -hex 32 (API_SERVER_KEY)',
            style: TextStyle(color: Colors.white38, fontSize: 11),
          ),
          const SizedBox(height: 16),
          OutlinedButton.icon(
            onPressed: _testing ? null : _testConnection,
            style: OutlinedButton.styleFrom(
              foregroundColor: const Color(0xFFF5A623),
              side: const BorderSide(color: Color(0xFFF5A623)),
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
              style: const TextStyle(color: Colors.white70, fontSize: 13),
            ),
          ],
          const SizedBox(height: 24),
          const Divider(color: Colors.white10),
          const SizedBox(height: 16),
          _sectionHeader('Wake-word'),
          SwitchListTile(
            title: const Text(
              'Слушать "Тройка" в фоне',
              style: TextStyle(color: Colors.white70),
            ),
            subtitle: const Text(
              'Работает в фоне, расходует заряд',
              style: TextStyle(color: Colors.white30, fontSize: 12),
            ),
            value: assistant.wakeWordEnabled,
            onChanged: (v) => assistant.setWakeWordEnabled(v),
            activeColor: const Color(0xFFF5A623),
          ),
          const SizedBox(height: 24),
          const Divider(color: Colors.white10),
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
                            ? const Color(0xFF2A2012)
                            : const Color(0xFF17150F),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(
                          color: isActive
                              ? const Color(0xFFF5A623)
                              : Colors.white10,
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
                                        ? Colors.white
                                        : Colors.white70,
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
                                const Icon(
                                  Icons.check_circle,
                                  color: Color(0xFFF5A623),
                                  size: 14,
                                ),
                            ],
                          ),
                          const Spacer(),
                          Text(
                            '${p.rate}x / ${p.pitch}Hz',
                            style: const TextStyle(
                              color: Colors.white30,
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
              foregroundColor: Colors.white70,
              side: const BorderSide(color: Colors.white10),
              minimumSize: const Size(double.infinity, 45),
            ),
            icon: const Icon(Icons.add_circle_outline, size: 18),
            label: const Text('Сохранить текущие настройки как пресет'),
          ),
          const SizedBox(height: 6),
          const Text(
            'Тап — применить, долгий тап — удалить.',
            style: TextStyle(color: Colors.white38, fontSize: 11),
          ),
          const SizedBox(height: 24),
          const Divider(color: Colors.white10),
          const SizedBox(height: 16),
          _sectionHeader('Голос Тройки'),
          const Text(
            'Слушай образец и выбирай. Edge TTS на PC, играет на телефоне.',
            style: TextStyle(color: Colors.white54, fontSize: 13, height: 1.5),
          ),
          const SizedBox(height: 12),
          ..._voices.map((v) {
            final isSelected = v['id'] == _currentVoice;
            return Container(
              margin: const EdgeInsets.only(bottom: 8),
              decoration: BoxDecoration(
                color: isSelected
                    ? const Color(0xFF2A2012)
                    : const Color(0xFF17150F),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color:
                      isSelected ? const Color(0xFFF5A623) : Colors.transparent,
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
                    color: Colors.white,
                    fontSize: 14,
                    fontWeight:
                        isSelected ? FontWeight.w600 : FontWeight.normal,
                  ),
                ),
                subtitle: Text(
                  v['desc']!,
                  style: const TextStyle(color: Colors.white54, fontSize: 12),
                ),
                trailing: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    IconButton(
                      icon: const Icon(
                        Icons.play_circle_outline,
                        color: Colors.white70,
                      ),
                      tooltip: 'Прослушать',
                      onPressed: () => _previewVoice(v['id']!),
                    ),
                    if (isSelected)
                      const Padding(
                        padding: EdgeInsets.only(left: 4),
                        child: Icon(
                          Icons.check_circle,
                          color: Color(0xFFF5A623),
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
          const Text(
            'Жми "Прослушать" чтобы услышать как звучит с этими настройками. '
            'Чтобы голос звучал более женственно — увеличий тон.',
            style: TextStyle(color: Colors.white54, fontSize: 12, height: 1.4),
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
                    foregroundColor: const Color(0xFFF5A623),
                    side: const BorderSide(color: Color(0xFFF5A623)),
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
                    backgroundColor: const Color(0xFFF5A623),
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
            style: TextButton.styleFrom(foregroundColor: Colors.white54),
            icon: const Icon(Icons.refresh, size: 14),
            label: const Text(
              'Сбросить к дефолтам',
              style: TextStyle(fontSize: 12),
            ),
          ),
          const SizedBox(height: 16),
          const Divider(color: Colors.white10),
          const SizedBox(height: 16),
          _sectionHeader('Прерывание речи (barge-in)'),
          SwitchListTile(
            title: const Text(
              'Замолкать когда я говорю',
              style: TextStyle(color: Colors.white70),
            ),
            subtitle: const Text(
              'Тройка обрывает свой ответ как только слышит твой голос',
              style: TextStyle(color: Colors.white30, fontSize: 12),
            ),
            value: _bargeInEnabled,
            onChanged: _saveBargeInEnabled,
            activeColor: const Color(0xFFF5A623),
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
            const Text(
              'Меньше = срабатывает на любой шорох (включая шум). '
              'Больше = только когда говоришь явно.',
              style: TextStyle(
                color: Colors.white38,
                fontSize: 11,
                height: 1.4,
              ),
            ),
          ],
          const SizedBox(height: 16),
          const Divider(color: Colors.white10),
          const SizedBox(height: 16),
          _sectionHeader('Управление телефоном'),
          const Text(
            'Разреши Тройке принимать команды только от твоего '
            'авторизованного сервера. Можно отключить в любой момент.',
            style: TextStyle(color: Colors.white54, fontSize: 13, height: 1.5),
          ),
          SwitchListTile(
            title: const Text(
              'Разрешить управление телефоном',
              style: TextStyle(color: Colors.white70),
            ),
            subtitle: const Text(
              'По умолчанию выключено. Опасные действия всё равно требуют '
              'отдельного подтверждения.',
              style: TextStyle(color: Colors.white38, fontSize: 12),
            ),
            value: _phoneControlEnabled,
            onChanged: _setPhoneControlEnabled,
            activeThumbColor: const Color(0xFFF5A623),
            contentPadding: EdgeInsets.zero,
          ),
          const SizedBox(height: 8),
          const Text(
            'Для нажатий, свайпов и ввода текста дополнительно включи '
            'Тройку в Спец. возможностях Android.',
            style: TextStyle(color: Colors.white54, fontSize: 13, height: 1.5),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: _openAccessibilitySettings,
            style: OutlinedButton.styleFrom(
              foregroundColor: const Color(0xFFF5A623),
              side: const BorderSide(color: Color(0xFFF5A623)),
            ),
            icon: const Icon(Icons.accessibility_new, size: 18),
            label: const Text('Открыть спец. возможности'),
          ),
          const SizedBox(height: 24),
          const Divider(color: Colors.white10),
          const SizedBox(height: 16),
          _sectionHeader('Файловая система'),
          const Text(
            'По умолчанию Тройка видит общедоступные папки: Downloads, '
            'Documents, Pictures, Music, Movies, DCIM. '
            'Если нужен доступ ко ВСЕМ файлам телефона (включая файлы '
            'других приложений) — дай разрешение "All files access".',
            style: TextStyle(color: Colors.white54, fontSize: 13, height: 1.5),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: _requestAllFilesAccess,
            style: OutlinedButton.styleFrom(
              foregroundColor: const Color(0xFFF5A623),
              side: const BorderSide(color: Color(0xFFF5A623)),
            ),
            icon: const Icon(Icons.folder_open, size: 18),
            label: const Text('Открыть доступ ко всем файлам'),
          ),
          const SizedBox(height: 24),
          const Divider(color: Colors.white10),
          const SizedBox(height: 16),
          _sectionHeader('Календарь'),
          const Text(
            'Чтобы Тройка мог ставить встречи и читать события из '
            'системного календаря (Google / Samsung / Outlook), '
            'разреши доступ.',
            style: TextStyle(color: Colors.white54, fontSize: 13, height: 1.5),
          ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: _requestCalendarPermission,
            style: OutlinedButton.styleFrom(
              foregroundColor: const Color(0xFFF5A623),
              side: const BorderSide(color: Color(0xFFF5A623)),
            ),
            icon: const Icon(Icons.event_available, size: 18),
            label: const Text('Разрешить доступ к календарю'),
          ),
          const SizedBox(height: 16),
          const Divider(color: Colors.white10),
          const SizedBox(height: 16),
          _sectionHeader('Местоположение'),
          const Text(
            'Только после включения Тройка получает GPS, Wi-Fi и Bluetooth '
            'контекст вместе с запросами. Разрешение Android само ничего не отправляет.',
            style: TextStyle(color: Colors.white54, fontSize: 13, height: 1.5),
          ),
          const SizedBox(height: 12),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text(
              'Передавать контекст местоположения',
              style: TextStyle(color: Colors.white70),
            ),
            subtitle: const Text(
              'Выключение останавливает передачу и очищает временный контекст на сервере.',
              style: TextStyle(color: Colors.white38, fontSize: 12),
            ),
            value: _locationContextEnabled,
            activeColor: const Color(0xFFF5A623),
            onChanged: _setLocationContextEnabled,
          ),
          OutlinedButton.icon(
            onPressed: _requestLocationPermission,
            style: OutlinedButton.styleFrom(
              foregroundColor: const Color(0xFFF5A623),
              side: const BorderSide(color: Color(0xFFF5A623)),
            ),
            icon: const Icon(Icons.my_location, size: 18),
            label: const Text('Разрешить местоположение'),
          ),
          const SizedBox(height: 24),
          ElevatedButton(
            onPressed: _save,
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFFF5A623),
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
                style: const TextStyle(color: Colors.white70, fontSize: 13),
              ),
              Text(
                display,
                style: const TextStyle(
                  color: Color(0xFFF5A623),
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
          SliderTheme(
            data: SliderTheme.of(context).copyWith(
              activeTrackColor: const Color(0xFFF5A623),
              inactiveTrackColor: Colors.white12,
              thumbColor: const Color(0xFFF5A623),
              overlayColor: const Color(0x337C6AF7),
              valueIndicatorColor: const Color(0xFFF5A623),
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
        style: const TextStyle(
          color: Color(0xFFF5A623),
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
      style: const TextStyle(color: Colors.white, fontSize: 14),
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        labelStyle: const TextStyle(color: Colors.white38),
        hintStyle: const TextStyle(color: Colors.white24),
        filled: true,
        fillColor: const Color(0xFF17150F),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: BorderSide.none,
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: Color(0xFFF5A623)),
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
