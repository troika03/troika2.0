import 'dart:io';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Keys stay in RAM. A remembered personal mode never falls back to Troika.
class OwnApiService {
  static const _channel = MethodChannel('troika/own_provider');
  static String? _key;
  static String? _owner;
  static Future<bool> enabled(String owner) async {
    final p = await SharedPreferences.getInstance();
    return p.getBool('troika_personal_provider_enabled') == true &&
        p.getString('troika_personal_provider_owner') == owner;
  }

  static Future<void> connect(String owner, String provider, String model, String key) async {
    if (owner.isEmpty || !{'openrouter', 'openai'}.contains(provider) ||
        model.isEmpty || model.length > 200 || RegExp(r'\s').hasMatch(model) ||
        key.length < 16 || key.length > 512 || RegExp(r'\s').hasMatch(key)) {
      throw ArgumentError('Проверь провайдера, модель и API-ключ.');
    }
    if (Platform.isAndroid) {
      await _channel.invokeMethod('configure', {'owner': owner, 'provider': provider, 'model': model, 'key': key});
    }
    final p = await SharedPreferences.getInstance();
    await p.setString('troika_personal_provider_owner', owner);
    await p.setString('troika_personal_provider_name', provider);
    await p.setString('troika_personal_provider_model', model);
    await p.setBool('troika_personal_provider_enabled', true);
    _key = key; _owner = owner;
  }

  static Future<void> disconnect() async {
    _key = null; _owner = null;
    final p = await SharedPreferences.getInstance();
    await p.setBool('troika_personal_provider_enabled', false);
    if (Platform.isAndroid) await _channel.invokeMethod('clear');
  }

  static Future<Map<String, String>> headers(String owner) async {
    if (!await enabled(owner)) return {};
    if (_key == null || _owner != owner) {
      throw StateError('Введи личный API-ключ снова. Ключ Тройки не использован.');
    }
    final p = await SharedPreferences.getInstance();
    return {'X-Troika-Provider-Key': _key!,
      'X-Troika-Provider': p.getString('troika_personal_provider_name')!,
      'X-Troika-Provider-Model': p.getString('troika_personal_provider_model')!};
  }
}
