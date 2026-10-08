import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import '../config/troika_config.dart';
import 'account_service.dart';

class CapabilityTool {
  final String id;
  final String title;
  final bool available;
  const CapabilityTool(
      {required this.id, required this.title, required this.available});

  factory CapabilityTool.fromJson(Map<String, dynamic> json) => CapabilityTool(
        id: json['id'] as String,
        title: json['title'] as String? ?? json['id'] as String,
        available: json['available'] as bool,
      );
}

class TroikaCapability {
  final String id;
  final String title;
  final String description;
  final bool enabled;
  final bool available;
  final List<String> skills;
  final List<CapabilityTool> tools;

  const TroikaCapability({
    required this.id,
    required this.title,
    required this.description,
    required this.enabled,
    required this.available,
    required this.skills,
    required this.tools,
  });

  factory TroikaCapability.fromJson(Map<String, dynamic> json) =>
      TroikaCapability(
        id: json['id'] as String,
        title: json['title'] as String,
        description: json['description'] as String,
        enabled: json['enabled'] as bool,
        available: json['available'] as bool,
        skills: (json['skills'] as List)
            .map((skill) => (skill as Map)['description'] as String)
            .toList(),
        tools: (json['tools'] as List)
            .map((tool) =>
                CapabilityTool.fromJson(Map<String, dynamic>.from(tool as Map)))
            .toList(),
      );
}

class CapabilityException implements Exception {
  final String message;
  const CapabilityException(this.message);
  @override
  String toString() => message;
}

class CapabilityService {
  final http.Client _client;
  final bool _ownsClient;
  final Future<bool> Function() _refreshSession;

  CapabilityService(
      {http.Client? client, Future<bool> Function()? refreshSession})
      : _client = client ?? http.Client(),
        _ownsClient = client == null,
        _refreshSession =
            refreshSession ?? (() => AccountService().ensureFreshSession());

  Future<List<TroikaCapability>> load() => _request();
  Future<List<TroikaCapability>> setEnabled(String id, bool enabled) =>
      _request(patch: {id: enabled});

  Future<List<TroikaCapability>> _request({Map<String, bool>? patch}) async {
    try {
      if (!await _refreshSession()) {
        throw const CapabilityException(
            'Войдите в аккаунт, чтобы управлять возможностями.');
      }
      final uri =
          Uri.parse('${TroikaConfig.serverUrl}/v1/account/capabilities');
      final response = await (patch == null
              ? _client.get(uri, headers: TroikaConfig.headers)
              : _client.patch(uri,
                  headers: TroikaConfig.headers,
                  body: jsonEncode({'enabled': patch})))
          .timeout(const Duration(seconds: 20));
      if (response.statusCode == 404) {
        throw const CapabilityException(
            'Каталог возможностей пока недоступен. Попробуйте позже.');
      }
      if (response.statusCode == 401 || response.statusCode == 403) {
        throw const CapabilityException(
            'Сессия завершилась. Войдите в аккаунт снова.');
      }
      if (response.statusCode != 200) {
        throw const CapabilityException(
            'Не удалось получить возможности. Попробуйте ещё раз.');
      }
      final body = jsonDecode(utf8.decode(response.bodyBytes));
      if (body is! Map ||
          body['object'] != 'troika.capabilities' ||
          body['capabilities'] is! List) {
        throw const FormatException('Invalid capability catalogue');
      }
      return (body['capabilities'] as List)
          .map((item) =>
              TroikaCapability.fromJson(Map<String, dynamic>.from(item as Map)))
          .toList();
    } on SocketException {
      throw const CapabilityException(
          'Нет соединения. Проверьте интернет и повторите.');
    } on TimeoutException {
      throw const CapabilityException(
          'Сервер не ответил вовремя. Попробуйте ещё раз.');
    } on FormatException {
      throw const CapabilityException(
          'Сервер вернул некорректный каталог возможностей.');
    } on TypeError {
      throw const CapabilityException(
          'Сервер вернул некорректный каталог возможностей.');
    } on http.ClientException {
      throw const CapabilityException('Нет соединения с сервером Тройки.');
    }
  }

  void dispose() {
    if (_ownsClient) _client.close();
  }
}
