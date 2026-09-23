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
      await TroikaConfig.saveAccount(email: email, token: token);
    } on SocketException {
      throw const AccountException('Нет соединения с сервером регистрации.');
    } on TimeoutException {
      throw const AccountException('Сервер регистрации не ответил вовремя.');
    } on FormatException {
      throw const AccountException('Сервер вернул некорректный ответ.');
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
