import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';

class VoicePreset {
  final String name;
  final String voice;
  final double rate;
  final int pitch;
  final int volume;

  const VoicePreset({
    required this.name,
    required this.voice,
    required this.rate,
    required this.pitch,
    required this.volume,
  });

  Map<String, dynamic> toJson() => {
        'name': name,
        'voice': voice,
        'rate': rate,
        'pitch': pitch,
        'volume': volume,
      };

  factory VoicePreset.fromJson(Map<String, dynamic> j) => VoicePreset(
        name: j['name'] as String? ?? 'Без имени',
        voice: j['voice'] as String? ?? 'ru-RU-SvetlanaNeural',
        rate: (j['rate'] as num?)?.toDouble() ?? 1.0,
        pitch: (j['pitch'] as num?)?.toInt() ?? 0,
        volume: (j['volume'] as num?)?.toInt() ?? 0,
      );

  VoicePreset copyWith({
    String? name,
    String? voice,
    double? rate,
    int? pitch,
    int? volume,
  }) =>
      VoicePreset(
        name: name ?? this.name,
        voice: voice ?? this.voice,
        rate: rate ?? this.rate,
        pitch: pitch ?? this.pitch,
        volume: volume ?? this.volume,
      );
}

class VoicePresets {
  static const _listKey = 'flutter.hermes_voice_presets';
  static const _activeKey = 'flutter.hermes_voice_active_preset';
  static const _seededKey = 'flutter.hermes_voice_presets_seeded';

  static const List<VoicePreset> defaults = [
    VoicePreset(name: 'Claude', voice: 'ru-RU-SvetlanaNeural', rate: 0.95, pitch: 12, volume: 0),
    VoicePreset(name: 'Jarvis', voice: 'ru-RU-DmitryNeural', rate: 1.0, pitch: -5, volume: 0),
    VoicePreset(name: 'Быстрый', voice: 'ru-RU-SvetlanaNeural', rate: 1.15, pitch: 5, volume: 0),
    VoicePreset(name: 'Спокойный', voice: 'ru-RU-SvetlanaNeural', rate: 0.9, pitch: 15, volume: 0),
  ];

  static Future<List<VoicePreset>> load() async {
    final prefs = await SharedPreferences.getInstance();
    final seeded = prefs.getBool(_seededKey) ?? false;
    if (!seeded) {
      await _save(prefs, defaults);
      await prefs.setBool(_seededKey, true);
      await prefs.setString(_activeKey, 'Claude');
      return List.of(defaults);
    }
    final raw = prefs.getString(_listKey);
    if (raw == null || raw.isEmpty) return List.of(defaults);
    try {
      final list = (jsonDecode(raw) as List)
          .map((e) => VoicePreset.fromJson(e as Map<String, dynamic>))
          .toList();
      return list.isEmpty ? List.of(defaults) : list;
    } catch (_) {
      return List.of(defaults);
    }
  }

  static Future<String?> getActiveName() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_activeKey);
  }

  static Future<void> setActiveName(String? name) async {
    final prefs = await SharedPreferences.getInstance();
    if (name == null) {
      await prefs.remove(_activeKey);
    } else {
      await prefs.setString(_activeKey, name);
    }
  }

  static Future<void> saveAll(List<VoicePreset> presets) async {
    final prefs = await SharedPreferences.getInstance();
    await _save(prefs, presets);
  }

  static Future<void> _save(SharedPreferences prefs, List<VoicePreset> presets) async {
    final json = jsonEncode(presets.map((p) => p.toJson()).toList());
    await prefs.setString(_listKey, json);
  }

  static Future<List<VoicePreset>> addOrUpdate(VoicePreset preset) async {
    final list = await load();
    final idx = list.indexWhere((p) => p.name == preset.name);
    if (idx >= 0) {
      list[idx] = preset;
    } else {
      list.add(preset);
    }
    await saveAll(list);
    return list;
  }

  static Future<List<VoicePreset>> remove(String name) async {
    final list = await load();
    list.removeWhere((p) => p.name == name);
    await saveAll(list);
    final active = await getActiveName();
    if (active == name) await setActiveName(null);
    return list;
  }
}
