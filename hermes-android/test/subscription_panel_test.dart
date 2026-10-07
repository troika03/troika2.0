import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/services/subscription_usage.dart';
import 'package:troika_assistant/services/troika_api_service.dart';
import 'package:troika_assistant/theme/troika_theme.dart';
import 'package:troika_assistant/widgets/subscription_panel.dart';

AccountSubscription usage({int remaining = 4}) => AccountSubscription(
      plan: 'plus',
      status: 'active',
      dailyLimit: 5,
      used: 5 - remaining,
      remaining: remaining,
      quotaEnforced: true,
      resetsAt: DateTime.utc(2026, 10, 8),
    );

void main() {
  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await TroikaConfig.init();
  });

  test('quota error is distinct from provider throttling', () {
    final error = cloudRequestError(
        429,
        '{"error":{"code":"daily_request_limit_exceeded"},'
        '"usage":{"resets_at":"2026-10-08T00:00:00+00:00"}}');
    expect(error, contains('Дневной AI-лимит исчерпан'));
    expect(error, contains('Локальные команды продолжают работать'));
    expect(cloudRequestError(429, '{"error":{"code":"rate_limit"}}'),
        contains('временно перегружена'));
    expect(cloudRequestError(503, ''), contains('временно недоступен'));
  });

  testWidgets(
      'usage refreshes after cloud requests and hides stale counters on failure',
      (tester) async {
    var calls = 0;
    await tester.pumpWidget(MaterialApp(
      theme: buildTroikaTheme(),
      home: Scaffold(
          body: SingleChildScrollView(child: SubscriptionPanel(load: () async {
        calls++;
        if (calls == 3) throw TroikaApiException('Нет соединения');
        return usage(remaining: calls == 1 ? 4 : 0);
      }))),
    ));
    await tester.pumpAndSettle();
    expect(find.text('4'), findsOneWidget);
    subscriptionUsageRevision.value++;
    await tester.pumpAndSettle();
    expect(find.text('Дневной AI-лимит исчерпан'), findsOneWidget);
    await tester.tap(find.byTooltip('Обновить лимиты'));
    await tester.pumpAndSettle();
    expect(find.text('Нет соединения'), findsOneWidget);
    expect(find.text('0'), findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  for (final light in [false, true]) {
    testWidgets(
        'usage fits narrow screen with large text (${light ? 'light' : 'dark'})',
        (tester) async {
      tester.view.physicalSize = const Size(320, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(MaterialApp(
        theme: light ? buildTroikaLightTheme() : buildTroikaTheme(),
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context)
              .copyWith(textScaler: const TextScaler.linear(1.5)),
          child: child!,
        ),
        home: Scaffold(
            body: SingleChildScrollView(
                child: SubscriptionPanel(load: () async => usage()))),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.text('Тройка Plus'), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
    });
  }
}
