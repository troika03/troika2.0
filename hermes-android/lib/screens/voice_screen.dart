import '../widgets/troika_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../services/tts_service.dart';

class VoiceScreen extends StatefulWidget {
  const VoiceScreen({super.key});

  @override
  State<VoiceScreen> createState() => _VoiceScreenState();
}

class _VoiceScreenState extends State<VoiceScreen> {
  final FlutterTts _tts = FlutterTts();
  List<Map<String, String>> _voices = const [];
  String? _selected;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final raw = await _tts.getVoices;
    final prefs = await SharedPreferences.getInstance();
    final voices = <Map<String, String>>[];
    if (raw is List) {
      for (final item in raw) {
        if (item is! Map) continue;
        final locale = item['locale']?.toString() ?? '';
        final name = item['name']?.toString() ?? '';
        if (locale.toLowerCase().startsWith('ru') && name.isNotEmpty) {
          voices.add({'name': name, 'locale': locale});
        }
      }
    }
    if (!mounted) return;
    setState(() {
      _voices = voices;
      _selected = prefs.getString(TtsService.voiceNameKey) ??
          (voices.isEmpty ? null : voices.first['name']);
      _loading = false;
    });
  }

  Future<void> _select(Map<String, String> voice) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(TtsService.voiceNameKey, voice['name']!);
    await prefs.setString(TtsService.voiceLocaleKey, voice['locale']!);
    await _tts.setLanguage(voice['locale']!);
    await _tts.setVoice(voice);
    await _tts.speak('Привет. Я Тройка. Этот голос выбран.');
    if (mounted) setState(() => _selected = voice['name']);
  }

  @override
  Widget build(BuildContext context) {
    return TroikaPage(
      appBar: AppBar(
        title: const Text('Голос'),
        backgroundColor: TroikaPalette.of(context).bg,
        surfaceTintColor: Colors.transparent,
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _voices.isEmpty
              ? const SingleChildScrollView(
                  child: TroikaEmptyState(
                      icon: Icons.record_voice_over_outlined,
                      title: 'Голосов пока нет',
                      message:
                          'Добавь русский голос в настройках синтеза речи Android.'))
              : ListView(
                  padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
                  children: [
                      const TroikaIntro(
                          icon: Icons.record_voice_over_outlined,
                          title: 'Выбери голос',
                          subtitle:
                              'Нажми на голос, чтобы послушать пример и выбрать его для ответов.'),
                      if (_selected != null)
                        Card(
                            child: ListTile(
                                leading: const TroikaIcon(
                                    icon: Icons.volume_up_outlined),
                                title: const Text('Текущий голос'),
                                subtitle: Text(_friendlyName(_selected!)),
                                trailing:
                                    const Icon(Icons.check_circle_outline))),
                      for (final voice in _voices)
                        RadioListTile<String>(
                          value: voice['name']!,
                          groupValue: _selected,
                          title: Text(_friendlyName(voice['name']!)),
                          subtitle: Text(voice['locale']!),
                          onChanged: (_) => _select(voice),
                        ),
                    ]),
    );
  }

  String _friendlyName(String name) {
    final clean = name.replaceAll(RegExp(r'[-_]'), ' ');
    return clean.length > 44 ? '${clean.substring(0, 44)}…' : clean;
  }

  @override
  void dispose() {
    _tts.stop();
    super.dispose();
  }
}
