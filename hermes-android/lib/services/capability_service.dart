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
  const CapabilityTool({
    required this.id,
    required this.title,
    required this.available,
  });

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
            .map(
              (tool) => CapabilityTool.fromJson(
                Map<String, dynamic>.from(tool as Map),
              ),
            )
            .toList(),
      );
}

/// A skill or MCP server from the account catalogue.
class CatalogueEntry {
  final String id;
  final String title;
  final String description;
  final String category;
  final bool connectable;
  final bool connected;
  final String reason;
  final String homepage;
  final String icon;

  /// "public", "oauth", "token" or "" (not connectable here).
  final String connect;
  final String tokenName;
  final String tokenHelp;
  const CatalogueEntry({
    required this.id,
    required this.title,
    required this.description,
    this.category = '',
    required this.connectable,
    required this.connected,
    this.reason = '',
    this.homepage = '',
    this.icon = '',
    this.connect = '',
    this.tokenName = '',
    this.tokenHelp = '',
  });

  bool get accountService => connect == 'oauth' || connect == 'token';

  factory CatalogueEntry.fromJson(Map<String, dynamic> json) => CatalogueEntry(
    id: json['id'] as String,
    title: json['title'] as String? ?? json['id'] as String,
    description: json['description'] as String? ?? '',
    category:
        json['category_title'] as String? ?? json['transport'] as String? ?? '',
    connectable: json['connectable'] as bool,
    connected: json['connected'] as bool,
    reason: json['reason'] as String? ?? '',
    homepage: json['homepage'] as String? ?? '',
    icon: json['icon'] as String? ?? '',
    connect: json['connect'] as String? ?? '',
    tokenName: json['token_name'] as String? ?? '',
    tokenHelp: json['token_help'] as String? ?? '',
  );
}

/// Skills, MCP servers and product tools. [skills] and [mcp] are null when
/// the server predates the extension catalogue.
class ExtensionCatalogue {
  final List<CatalogueEntry>? skills;
  final List<CatalogueEntry>? mcp;
  final List<TroikaCapability> tools;
  const ExtensionCatalogue({
    required this.skills,
    required this.mcp,
    required this.tools,
  });
}

/// Result of starting a service connection.
class ServiceConnectStart {
  final String status;
  final String flow;
  final Uri? authorizationUrl;
  const ServiceConnectStart(this.status, this.flow, this.authorizationUrl);
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

  CapabilityService({
    http.Client? client,
    Future<bool> Function()? refreshSession,
  }) : _client = client ?? http.Client(),
       _ownsClient = client == null,
       _refreshSession =
           refreshSession ?? (() => AccountService().ensureFreshSession());

  Future<List<TroikaCapability>> load() => _request();

  Future<ExtensionCatalogue> loadCatalogue() => _extensions();
  Future<ExtensionCatalogue> setSkillConnected(String id, bool connected) =>
      _extensions(
        patch: {
          'skills': {id: connected},
        },
      );
  Future<ExtensionCatalogue> setMcpConnected(String id, bool connected) =>
      _extensions(
        patch: {
          'mcp': {id: connected},
        },
      );
  Future<ExtensionCatalogue> setToolEnabled(String id, bool enabled) =>
      _extensions(
        patch: {
          'capabilities': {id: enabled},
        },
      );

  /// Starts sign-in (OAuth) or saves a personal token for an account service.
  Future<ServiceConnectStart> connectService(String id, {String? token}) async {
    final body = await _serviceCall(
      'POST',
      '/v1/account/services/${Uri.encodeComponent(id)}/connect',
      token == null ? {} : {'token': token},
    );
    final url = Uri.tryParse(body['authorization_url'] as String? ?? '');
    if (body['status'] == 'waiting' && (url == null || url.scheme != 'https')) {
      throw const FormatException('Invalid authorization URL');
    }
    return ServiceConnectStart(
      body['status'] as String? ?? '',
      body['flow'] as String? ?? '',
      body['status'] == 'waiting' ? url : null,
    );
  }

  Future<String> serviceFlowStatus(String flow) async {
    final body = await _serviceCall(
      'GET',
      '/v1/account/services/flows/${Uri.encodeComponent(flow)}',
      null,
    );
    return body['status'] as String? ?? 'expired';
  }

  Future<Map<String, dynamic>> _serviceCall(
    String method,
    String path,
    Map<String, dynamic>? body,
  ) async {
    try {
      if (!await _refreshSession()) {
        throw const CapabilityException(
          'Войдите в аккаунт, чтобы подключать сервисы.',
        );
      }
      final uri = Uri.parse('${TroikaConfig.serverUrl}$path');
      final response =
          await (method == 'GET'
                  ? _client.get(uri, headers: TroikaConfig.headers)
                  : _client.post(
                      uri,
                      headers: TroikaConfig.headers,
                      body: jsonEncode(body),
                    ))
              .timeout(const Duration(seconds: 60));
      final decoded = response.bodyBytes.isEmpty
          ? null
          : jsonDecode(utf8.decode(response.bodyBytes));
      if (response.statusCode != 200) {
        final message = decoded is Map && decoded['error'] is Map
            ? (decoded['error'] as Map)['message']
            : null;
        throw CapabilityException(
          message is String && message.isNotEmpty
              ? message
              : response.statusCode == 404
              ? 'Сервер пока не поддерживает подключение сервисов.'
              : 'Не удалось подключить сервис. Попробуйте ещё раз.',
        );
      }
      if (decoded is! Map) throw const FormatException('Invalid response');
      return Map<String, dynamic>.from(decoded);
    } on SocketException {
      throw const CapabilityException(
        'Нет соединения. Проверьте интернет и повторите.',
      );
    } on TimeoutException {
      throw const CapabilityException(
        'Сервер не ответил вовремя. Попробуйте ещё раз.',
      );
    } on FormatException {
      throw const CapabilityException('Сервер вернул некорректный ответ.');
    } on http.ClientException {
      throw const CapabilityException('Нет соединения с сервером Тройки.');
    }
  }

  Future<ExtensionCatalogue> _extensions({Map<String, dynamic>? patch}) async {
    try {
      if (!await _refreshSession()) {
        throw const CapabilityException(
          'Войдите в аккаунт, чтобы управлять возможностями.',
        );
      }
      final uri = Uri.parse('${TroikaConfig.serverUrl}/v1/account/extensions');
      final response =
          await (patch == null
                  ? _client.get(uri, headers: TroikaConfig.headers)
                  : _client.patch(
                      uri,
                      headers: TroikaConfig.headers,
                      body: jsonEncode(patch),
                    ))
              .timeout(const Duration(seconds: 20));
      if (response.statusCode == 404) {
        // Older server: only the tool switches exist.
        if (patch != null && !patch.containsKey('capabilities')) {
          throw const CapabilityException(
            'Сервер пока не поддерживает подключение навыков и MCP.',
          );
        }
        final caps = patch == null
            ? await _request()
            : await _request(
                patch: Map<String, bool>.from(patch['capabilities'] as Map),
              );
        return ExtensionCatalogue(skills: null, mcp: null, tools: caps);
      }
      if (response.statusCode == 401) {
        throw const CapabilityException(
          'Сессия завершилась. Войдите в аккаунт снова.',
        );
      }
      if (response.statusCode == 403) {
        throw const CapabilityException(
          'Это нельзя подключить в облаке Тройки.',
        );
      }
      if (response.statusCode != 200) {
        throw const CapabilityException(
          'Не удалось получить возможности. Попробуйте ещё раз.',
        );
      }
      final body = jsonDecode(utf8.decode(response.bodyBytes));
      if (body is! Map ||
          body['object'] != 'troika.extensions' ||
          body['skills'] is! List ||
          body['mcp'] is! List ||
          body['tools'] is! List) {
        throw const FormatException('Invalid extension catalogue');
      }
      List<CatalogueEntry> entries(String key) => (body[key] as List)
          .map(
            (item) =>
                CatalogueEntry.fromJson(Map<String, dynamic>.from(item as Map)),
          )
          .toList();
      return ExtensionCatalogue(
        skills: entries('skills'),
        mcp: entries('mcp'),
        tools: (body['tools'] as List)
            .map(
              (item) => TroikaCapability.fromJson(
                Map<String, dynamic>.from(item as Map),
              ),
            )
            .toList(),
      );
    } on SocketException {
      throw const CapabilityException(
        'Нет соединения. Проверьте интернет и повторите.',
      );
    } on TimeoutException {
      throw const CapabilityException(
        'Сервер не ответил вовремя. Попробуйте ещё раз.',
      );
    } on FormatException {
      throw const CapabilityException(
        'Сервер вернул некорректный каталог возможностей.',
      );
    } on TypeError {
      throw const CapabilityException(
        'Сервер вернул некорректный каталог возможностей.',
      );
    } on http.ClientException {
      throw const CapabilityException('Нет соединения с сервером Тройки.');
    }
  }

  Future<List<TroikaCapability>> setEnabled(String id, bool enabled) =>
      _request(patch: {id: enabled});

  Future<List<TroikaCapability>> _request({Map<String, bool>? patch}) async {
    try {
      if (!await _refreshSession()) {
        throw const CapabilityException(
          'Войдите в аккаунт, чтобы управлять возможностями.',
        );
      }
      final uri = Uri.parse(
        '${TroikaConfig.serverUrl}/v1/account/capabilities',
      );
      final response =
          await (patch == null
                  ? _client.get(uri, headers: TroikaConfig.headers)
                  : _client.patch(
                      uri,
                      headers: TroikaConfig.headers,
                      body: jsonEncode({'enabled': patch}),
                    ))
              .timeout(const Duration(seconds: 20));
      if (response.statusCode == 404) {
        throw const CapabilityException(
          'Каталог возможностей пока недоступен. Попробуйте позже.',
        );
      }
      if (response.statusCode == 401 || response.statusCode == 403) {
        throw const CapabilityException(
          'Сессия завершилась. Войдите в аккаунт снова.',
        );
      }
      if (response.statusCode != 200) {
        throw const CapabilityException(
          'Не удалось получить возможности. Попробуйте ещё раз.',
        );
      }
      final body = jsonDecode(utf8.decode(response.bodyBytes));
      if (body is! Map ||
          body['object'] != 'troika.capabilities' ||
          body['capabilities'] is! List) {
        throw const FormatException('Invalid capability catalogue');
      }
      return (body['capabilities'] as List)
          .map(
            (item) => TroikaCapability.fromJson(
              Map<String, dynamic>.from(item as Map),
            ),
          )
          .toList();
    } on SocketException {
      throw const CapabilityException(
        'Нет соединения. Проверьте интернет и повторите.',
      );
    } on TimeoutException {
      throw const CapabilityException(
        'Сервер не ответил вовремя. Попробуйте ещё раз.',
      );
    } on FormatException {
      throw const CapabilityException(
        'Сервер вернул некорректный каталог возможностей.',
      );
    } on TypeError {
      throw const CapabilityException(
        'Сервер вернул некорректный каталог возможностей.',
      );
    } on http.ClientException {
      throw const CapabilityException('Нет соединения с сервером Тройки.');
    }
  }

  void dispose() {
    if (_ownsClient) _client.close();
  }
}
