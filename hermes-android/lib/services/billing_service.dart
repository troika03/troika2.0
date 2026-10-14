import 'dart:convert';
import 'dart:math';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';
import '../config/troika_config.dart';
import 'account_service.dart';
import 'troika_api_service.dart';

/// Keep the same account-owned payment key after an uncertain checkout.
class BillingService {
  Future<Map<String, dynamic>> verification(String action,
          [Map<String, dynamic>? body]) =>
      _request('POST', '/v1/account/verification/$action', body);
  Future<Map<String, dynamic>> _request(String method, String path,
      [Map<String, dynamic>? body]) async {
    await AccountService().ensureFreshSession();
    final request = http.Request(
        method, Uri.parse(TroikaConfig.subscriptionUrl).replace(path: path))
      ..followRedirects = false
      ..headers.addAll(TroikaConfig.headers);
    if (body != null) {
      request.headers['Content-Type'] = 'application/json';
      request.body = jsonEncode(body);
    }
    final client = http.Client();
    try {
      final response =
          await client.send(request).timeout(const Duration(seconds: 20));
      final value = await response.stream
          .bytesToString()
          .timeout(const Duration(seconds: 10));
      if (response.statusCode != 200) {
        if (path.startsWith('/v1/account/verification/')) {
          throw TroikaApiException(
              'Подтверждение почты пока недоступно. Проверь код; перед новым письмом подожди минуту.');
        }
        throw TroikaApiException(
            'Оплата пока недоступна. Повтор сохранит тот же платёж.');
      }
      return jsonDecode(value) as Map<String, dynamic>;
    } finally {
      client.close();
    }
  }

  Future<Map<String, dynamic>> catalogue() => _request('GET', '/v1/billing');

  Future<void> checkout(String sku) async {
    final account = TroikaConfig.accountEmail;
    final preferences = await SharedPreferences.getInstance();
    final storageKey = 'troika_payment_${Uri.encodeComponent(account)}_$sku';
    var key = preferences.getString(storageKey);
    key ??= List.generate(
            16,
            (_) =>
                Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0'))
        .join();
    await preferences.setString(storageKey, key);
    final result = await _request(
        'POST', '/v1/billing/checkout', {'sku': sku, 'idempotency_key': key});
    if (account != TroikaConfig.accountEmail)
      throw TroikaApiException('Аккаунт изменился. Оплата остановлена.');
    if (['applied', 'test_succeeded', 'refunded'].contains(result['state'])) {
      await preferences.remove(storageKey);
      throw TroikaApiException(
          'Платёж уже завершён. Обнови баланс; новая покупка требует отдельного действия.');
    }
    final uri = Uri.parse(result['confirmation_url'] as String);
    if (!isPaymentUrl(uri))
      throw TroikaApiException('Неподдержанная страница оплаты.');
    if (!await launchUrl(uri, mode: LaunchMode.externalApplication))
      throw TroikaApiException('Не удалось открыть оплату.');
  }

  static bool isPaymentUrl(Uri uri) =>
      uri.scheme == 'https' &&
      uri.userInfo.isEmpty &&
      uri.port == 443 &&
      ['yoomoney.ru', 'yookassa.ru']
          .any((domain) => uri.host == domain || uri.host.endsWith('.$domain'));
}
