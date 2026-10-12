import 'dart:convert';
import 'package:http/http.dart' as http;
import '../config/troika_config.dart';
import 'troika_api_service.dart';

class TroikaMemorySnapshot {
  final List<TroikaMemory> memories;
  final Set<String> automaticIds;
  final bool automaticEnabled, supportsAutomatic;
  const TroikaMemorySnapshot(
      {required this.memories,
      required this.automaticIds,
      required this.automaticEnabled,
      required this.supportsAutomatic});

  factory TroikaMemorySnapshot.fromJson(Map<String, dynamic> data) {
    final rows = ((data['memories'] as List?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .toList();
    final preferences = data['preferences'];
    return TroikaMemorySnapshot(
      memories: rows.map(TroikaMemory.fromJson).toList(),
      automaticIds: {
        for (final row in rows)
          if (row['source'] == 'automatic') row['id'].toString()
      },
      automaticEnabled:
          preferences is Map && preferences['automatic_enabled'] == true,
      supportsAutomatic:
          preferences is Map && preferences['automatic_enabled'] is bool,
    );
  }
}

class MemoryService {
  final http.Client _client;
  MemoryService({http.Client? client}) : _client = client ?? http.Client();

  Future<TroikaMemorySnapshot> load() async {
    final response = await _client
        .get(Uri.parse('${TroikaConfig.serverUrl}/v1/memories'),
            headers: TroikaConfig.headers)
        .timeout(const Duration(seconds: 15));
    _check(response, 'Память недоступна');
    return TroikaMemorySnapshot.fromJson(
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>);
  }

  Future<void> setAutomaticEnabled(bool enabled) async {
    final response = await _client
        .put(Uri.parse('${TroikaConfig.serverUrl}/v1/memory-preferences'),
            headers: TroikaConfig.headers,
            body: json.encode({'automatic_enabled': enabled}))
        .timeout(const Duration(seconds: 15));
    _check(response, 'Настройка памяти не сохранена');
    final data = json.decode(utf8.decode(response.bodyBytes));
    if (data is! Map || data['automatic_enabled'] != enabled) {
      throw TroikaApiException('Сервер не подтвердил настройку памяти.');
    }
  }

  static void _check(http.Response response, String message) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw TroikaApiException('$message (${response.statusCode}).');
    }
  }

  void dispose() => _client.close();
}
