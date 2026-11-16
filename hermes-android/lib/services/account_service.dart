import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:flutter/services.dart';

import '../config/troika_config.dart';
import 'request_identity.dart';

class AccountService {
  static const _timeout = Duration(seconds: 20);
  static _SessionRefresh? _refreshInFlight;

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

  Future<void> login({required String email, required String password}) async {
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
    final identity = TroikaRequestIdentity();
    final expectedNativeRevision = TroikaConfig.nativeIdentityRevision;
    try {
      final response = await _postAccountRequest(
        uri,
        headers: const {'Content-Type': 'application/json'},
        body: jsonEncode({
          'email': email.trim(),
          'password': password,
          'device_name': _deviceName(),
          'platform': _platform(),
        }),
      );
      identity.check();
      if (response.statusCode == 429) {
        throw const AccountException(
          'Слишком много попыток. Подождите немного и попробуйте снова.',
          statusCode: 429,
        );
      }
      if (response.statusCode >= 500) {
        throw const AccountException(
          'Сервер временно недоступен. Попробуйте войти чуть позже.',
        );
      }
      final payload = jsonDecode(utf8.decode(response.bodyBytes));
      if (response.statusCode != expectedStatus || payload is! Map) {
        throw AccountException(
          _errorMessage(payload, response.statusCode),
          statusCode: response.statusCode,
        );
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
        replaceIdentity: true,
        expectedNativeRevision: expectedNativeRevision,
      );
    } on SocketException {
      throw const AccountException('Нет соединения с сервером регистрации.');
    } on TimeoutException {
      throw const AccountException('Сервер регистрации не ответил вовремя.');
    } on FormatException {
      throw const AccountException('Сервер вернул некорректный ответ.');
    } on StateError catch (error) {
      throw AccountException(error.message.toString());
    }
  }

  /// Refresh a short-lived access token, or migrate one legacy installation.
  Future<bool> ensureFreshSession({
    bool force = false,
    void Function()? checkRequest,
  }) async {
    checkRequest?.call();
    final identity = TroikaRequestIdentity();
    final observedToken = TroikaConfig.apiKey;
    while (_refreshInFlight != null) {
      final pending = _refreshInFlight!;
      bool result = false;
      try {
        result = await pending.future;
      } on RequestIdentityChanged catch (error) {
        if (error is AccountSessionRevoked &&
            identity.matches(pending.identity))
          rethrow;
        checkRequest?.call();
        if (checkRequest == null && _canAdoptFreshSession(identity))
          return true;
        if (identity.matches(pending.identity)) rethrow;
      }
      checkRequest?.call();
      identity.check();
      if (identical(_refreshInFlight, pending)) _refreshInFlight = null;
      if (identity.matches(pending.identity) &&
          (!force || pending.force || TroikaConfig.apiKey != observedToken)) {
        return result;
      }
    }
    // Shared refresh belongs to the account, not its first waiting speech turn.
    final operation = _SessionRefresh(
      identity,
      force,
      _ensureFreshSession(force: force, checkRequest: identity.check),
    );
    _refreshInFlight = operation;
    try {
      final result = await operation.future;
      checkRequest?.call();
      return result;
    } on AccountSessionRevoked {
      rethrow;
    } on RequestIdentityChanged {
      checkRequest?.call();
      // A successful legacy upgrade can replace the installation conversation
      // with the account's home session before any user turn has started.
      if (checkRequest == null && _canAdoptFreshSession(identity)) return true;
      rethrow;
    } finally {
      if (identical(_refreshInFlight, operation)) _refreshInFlight = null;
    }
  }

  bool _canAdoptFreshSession(TroikaRequestIdentity previous) =>
      TroikaConfig.voiceSessionAvailable &&
      TroikaConfig.serverUrl == previous.origin &&
      TroikaConfig.accountEmail == previous.owner &&
      TroikaConfig.sessionId.startsWith('ses_') &&
      (TroikaConfig.accessTokenExpiresAt?.isAfter(
            DateTime.now().toUtc().add(const Duration(minutes: 5)),
          ) ??
          false);

  Future<bool> _ensureFreshSession({
    bool force = false,
    void Function()? checkRequest,
  }) async {
    checkRequest?.call();
    await TroikaConfig.reloadAccountSession();
    checkRequest?.call();
    if (!TroikaConfig.signedIn) return false;
    if (Platform.isAndroid) {
      try {
        checkRequest?.call();
        final fresh = await const MethodChannel(
          'com.troika.hermes/background',
        ).invokeMethod<bool>('ensureFreshAccountSession', {'force': force});
        checkRequest?.call();
        await TroikaConfig.reloadAccountSession();
        checkRequest?.call();
        return fresh == true;
      } catch (_) {
        checkRequest?.call();
        return false;
      }
    }
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
    final previousToken = TroikaConfig.apiKey;
    final previousEmail = TroikaConfig.accountEmail;
    final uri = Uri.parse(
      legacyUpgrade ? TroikaConfig.upgradeTokenUrl : TroikaConfig.refreshUrl,
    );
    try {
      final response = await _postAccountRequest(
        uri,
        headers: legacyUpgrade
            ? TroikaConfig.headers
            : const {'Content-Type': 'application/json'},
        body: jsonEncode(
          legacyUpgrade ? const {} : {'refresh_token': refreshToken},
        ),
      );
      checkRequest?.call();
      if (response.statusCode == 401) {
        await TroikaConfig.clearRevokedDevice();
        throw const AccountSessionRevoked();
      }
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
      if (TroikaConfig.apiKey != previousToken ||
          TroikaConfig.accountEmail != previousEmail) {
        return false;
      }
      checkRequest?.call();
      await TroikaConfig.saveAccount(
        email: previousEmail,
        token: access,
        refreshToken: nextRefresh,
        accessExpiresAt: expiresAt,
        homeSessionId: homeSessionId,
      );
      checkRequest?.call();
      return true;
    } on AccountSessionRevoked {
      rethrow;
    } catch (_) {
      checkRequest?.call();
      return false;
    }
  }

  Future<http.Response> _postAccountRequest(
    Uri uri, {
    required Map<String, String> headers,
    required String body,
  }) async {
    final client = http.Client();
    try {
      return await (() async {
        final request = http.Request('POST', uri)
          ..followRedirects = false
          ..headers.addAll(headers)
          ..body = body;
        final response = await client.send(request);
        final bytes = <int>[];
        await for (final chunk in response.stream) {
          if (bytes.length + chunk.length > 64 * 1024) {
            throw const FormatException('Account response too large');
          }
          bytes.addAll(chunk);
        }
        return http.Response.bytes(
          bytes,
          response.statusCode,
          headers: response.headers,
        );
      })().timeout(_timeout);
    } finally {
      client.close();
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

class _SessionRefresh {
  const _SessionRefresh(this.identity, this.force, this.future);
  final TroikaRequestIdentity identity;
  final bool force;
  final Future<bool> future;
}

class AccountSessionRevoked extends RequestIdentityChanged {
  const AccountSessionRevoked();
}

class AccountException implements Exception {
  final String message;
  final int? statusCode;

  const AccountException(this.message, {this.statusCode});

  @override
  String toString() => message;
}
