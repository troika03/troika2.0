import 'package:flutter_test/flutter_test.dart';
import 'package:troika_assistant/services/billing_service.dart';
import 'package:troika_assistant/services/subscription_usage.dart';
import 'package:troika_assistant/services/troika_api_service.dart';

void main() {
  test('payment URLs cannot carry credentials or leave the payment service',
      () {
    expect(
        BillingService.isPaymentUrl(
            Uri.parse('https://yoomoney.ru/checkout/1')),
        isTrue);
    for (final url in [
      'http://yoomoney.ru/1',
      'https://yoomoney.ru.evil.test/',
      'https://u:p@yoomoney.ru/',
      'https://evil.test/'
    ]) {
      expect(BillingService.isPaymentUrl(Uri.parse(url)), isFalse);
    }
  });
  test('monthly receipts replace the displayed daily counter', () {
    final value = AccountSubscription.fromJson({
      'plan': 'plus',
      'resource_enforced': true,
      'quota_enforced': true,
      'daily_limit': 10000,
      'used': 99,
      'spent': 5911,
      'monthly_limit': 5000000,
      'remaining': 4990000,
      'reserved': 4089
    });
    expect(value.used, 5911);
    expect(value.resourceEnforced, isTrue);
    expect(value.reserved, 4089);
    expect(value.monthlyLimit, 5000000);
  });
  test('unknown provider cost never suggests blindly retrying', () {
    final error =
        cloudRequestError(409, '{"error":{"code":"resource_usage_unknown"}}');
    expect(error, contains('Резерв сохранён'));
    expect(error, isNot(contains('Попробуй ещё раз')));
  });
}
