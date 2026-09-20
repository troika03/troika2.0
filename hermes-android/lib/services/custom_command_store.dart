import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

class CustomCommand {
  final String phrase;
  final String action;

  const CustomCommand({required this.phrase, required this.action});

  Map<String, String> toJson() => {'phrase': phrase, 'action': action};

  factory CustomCommand.fromJson(Map<String, dynamic> value) => CustomCommand(
        phrase: value['phrase']?.toString() ?? '',
        action: value['action']?.toString() ?? '',
      );
}

class CustomCommandStore {
  static const key = 'troika_custom_commands';

  static Future<List<CustomCommand>> load() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(key);
    if (raw == null || raw.isEmpty) return const [];
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! List) return const [];
      return decoded
          .whereType<Map>()
          .map((item) => CustomCommand.fromJson(item.cast<String, dynamic>()))
          .where((item) => item.phrase.isNotEmpty && item.action.isNotEmpty)
          .toList();
    } catch (_) {
      return const [];
    }
  }

  static Future<void> save(List<CustomCommand> commands) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      key,
      jsonEncode(commands.map((item) => item.toJson()).toList()),
    );
  }
}
