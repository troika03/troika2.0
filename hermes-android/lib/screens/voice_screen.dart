import 'package:flutter/material.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../services/tts_service.dart';
import '../theme/troika_theme.dart';

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
    return Scaffold(
      appBar: AppBar(
        title: const Text('Голос'),
        backgroundColor: TroikaColors.bg,
        surfaceTintColor: Colors.transparent,
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _voices.isEmpty
              ? const Center(
                  child: Text('Русские системные голоса не найдены.'),
                )
              : ListView.separated(
                  padding: const EdgeInsets.all(20),
                  itemCount: _voices.length,
                  separatorBuilder: (_, __) => const Divider(height: 1),
                  itemBuilder: (_, index) {
                    final voice = _voices[index];
                    return RadioListTile<String>(
                      value: voice['name']!,
                      groupValue: _selected,
                      title: Text(_friendlyName(voice['name']!)),
                      subtitle: Text(voice['locale']!),
                      onChanged: (_) => _select(voice),
                    );
                  },
                ),
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
