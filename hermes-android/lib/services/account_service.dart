import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import '../config/troika_config.dart';

class AccountService {
  static const _timeout = Duration(seconds: 20);

  Future<void> register({
    required String email,
    required String password,
  }) async {
    await _authenticate(
      Uri.parse(TroikaConfig.registrationUrl),
      email: email,
      password: password,
      expectedStatus: 201,
    );
  }

  Future<void> login({
    required String email,
    required String password,
  }) async {
    await _authenticate(
      Uri.parse(TroikaConfig.loginUrl),
      email: email,
      password: password,
      expectedStatus: 200,
    );
  }

  Future<void> _authenticate(
    Uri uri, {
    required String email,
    required String password,
    required int expectedStatus,
  }) async {
    if (TroikaConfig.serverUrl.trim().isEmpty) {
      throw const AccountException(
        'Сервер регистрации не указан в этой тестовой сборке.',
      );
    }
    try {
      final response = await http
          .post(
            uri,
            headers: const {'Content-Type': 'application/json'},
            body: jsonEncode({
              'email': email.trim(),
              'password': password,
              'device_name': _deviceName(),
              'platform': _platform(),
            }),
          )
          .timeout(_timeout);
      final payload = jsonDecode(utf8.decode(response.bodyBytes));
      if (response.statusCode != expectedStatus || payload is! Map) {
        throw AccountException(_errorMessage(payload, response.statusCode));
      }
      final token = payload['token']?.toString().trim() ?? '';
      if (!token.startsWith('trk_live_')) {
        throw const AccountException('Сервер не вернул токен аккаунта.');
      }
      final refreshToken = payload['refresh_token']?.toString().trim() ?? '';
      if (!refreshToken.startsWith('trk_refresh_')) {
        throw const AccountException(
          'Сервер не вернул защищённый токен обновления.',
        );
      }
      final accessExpiresAt =
          (payload['access_expires_at'] as num?)?.toDouble() ?? 0;
      final homeSessionId = payload['home_session_id']?.toString().trim() ?? '';
      if (homeSessionId.isEmpty) {
        throw const AccountException(
          'Сервер не вернул общую историю аккаунта.',
        );
      }
      await TroikaConfig.saveAccount(
        email: email,
        token: token,
        refreshToken: refreshToken,
        accessExpiresAt: accessExpiresAt,
        homeSessionId: homeSessionId,
      );
    } on SocketException {
      throw const AccountException('Нет соединения с сервером регистрации.');
    } on TimeoutException {
      throw const AccountException('Сервер регистрации не ответил вовремя.');
    } on FormatException {
      throw const AccountException('Сервер вернул некорректный ответ.');
    }
  }

  /// Refresh a short-lived access token, or migrate one legacy installation.
  Future<bool> ensureFreshSession({
    bool force = false,
    void Function()? checkRequest,
  }) async {
    checkRequest?.call();
    final requestOwner = TroikaConfig.accountEmail;
    if (!TroikaConfig.signedIn) return false;
    final expiry = TroikaConfig.accessTokenExpiresAt;
    final refreshToken = await TroikaConfig.getRefreshToken();
    checkRequest?.call();
    if (!force &&
        refreshToken.isNotEmpty &&
        expiry != null &&
        expiry.isAfter(
          DateTime.now().toUtc().add(const Duration(minutes: 5)),
        )) {
      return true;
    }
    final legacyUpgrade = refreshToken.isEmpty;
    final uri = Uri.parse(
      legacyUpgrade ? TroikaConfig.upgradeTokenUrl : TroikaConfig.refreshUrl,
    );
    try {
      final response = await http
          .post(
            uri,
            headers: legacyUpgrade
                ? TroikaConfig.headers
                : const {'Content-Type': 'application/json'},
            body: jsonEncode(
              legacyUpgrade ? const {} : {'refresh_token': refreshToken},
            ),
          )
          .timeout(_timeout);
      checkRequest?.call();
      if (response.statusCode != 200) return false;
      final payload =
          jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      final access = (payload['access_token'] ?? payload['token']).toString();
      final nextRefresh = (payload['refresh_token'] ?? '').toString();
      final expiresAt = (payload['access_expires_at'] as num?)?.toDouble() ?? 0;
      final homeSessionId = (payload['home_session_id'] ?? '')
          .toString()
          .trim();
      if (!access.startsWith('trk_live_') ||
          !nextRefresh.startsWith('trk_refresh_') ||
          expiresAt <= 0 ||
          homeSessionId.isEmpty) {
        return false;
      }
      checkRequest?.call();
      await TroikaConfig.saveAccount(
        email: requestOwner,
        token: access,
        refreshToken: nextRefresh,
        accessExpiresAt: expiresAt,
        homeSessionId: homeSessionId,
      );
      checkRequest?.call();
      return true;
    } catch (_) {
      return false;
    }
  }

  static String _platform() {
    if (Platform.isAndroid) return 'android';
    if (Platform.isIOS) return 'ios';
    if (Platform.isWindows) return 'windows';
    if (Platform.isMacOS) return 'macos';
    if (Platform.isLinux) return 'linux';
    return 'desktop';
  }

  static String _deviceName() => 'Troika ${_platform()}';

  static String _errorMessage(dynamic payload, int status) {
    if (payload is Map) {
      final error = payload['error'];
      if (error is Map && error['message'] != null) {
        final message = error['message'].toString();
        if (message.contains('already exists')) {
          return 'Аккаунт с этой почтой уже существует.';
        }
        if (message.contains('Invalid email or password')) {
          return 'Неверная почта или пароль.';
        }
        if (message.contains('between 10 and 128')) {
          return 'Пароль должен содержать минимум 10 символов.';
        }
      }
    }
    return 'Не удалось войти (код $status).';
  }
}

class AccountException implements Exception {
  final String message;

  const AccountException(this.message);

  @override
  String toString() => message;
}
