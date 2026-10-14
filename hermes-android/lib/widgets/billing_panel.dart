import 'package:flutter/material.dart';
import '../services/billing_service.dart';
import '../services/subscription_usage.dart';

class BillingPanel extends StatefulWidget {
  const BillingPanel({super.key});
  @override
  State<BillingPanel> createState() => _BillingPanelState();
}

class _BillingPanelState extends State<BillingPanel> {
  Map<String, dynamic>? _catalogue;
  String? _message;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final result = await BillingService().catalogue();
      if (mounted) setState(() => _catalogue = result);
    } catch (_) {
      if (mounted)
        setState(() => _message = 'Не удалось загрузить условия подписки.');
    }
  }

  Future<void> _buy(String sku, String title) async {
    final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
              title: Text(title),
              content: const Text(
                  'Оплата откроется в браузере. Автоматических списаний нет. '
                  'Смена тарифа начнётся после текущего оплаченного периода; докупка действует 90 дней.'),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(context, false),
                    child: const Text('Отмена')),
                FilledButton(
                    onPressed: () => Navigator.pop(context, true),
                    child: const Text('Перейти к оплате'))
              ],
            ));
    if (confirmed != true || !mounted) return;
    setState(() => _busy = true);
    try {
      await BillingService().checkout(sku);
      if (mounted)
        setState(
            () => _message = 'Баланс обновится после подтверждения оплаты.');
    } catch (error) {
      if (mounted) setState(() => _message = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _verifyEmail() async {
    final code = TextEditingController();
    try {
      final challenge = await BillingService().verification('request');
      if (!mounted) return;
      if (challenge['verified'] == true) {
        await BillingService().verification('welcome');
        subscriptionUsageRevision.value++;
        setState(() => _message =
            'Почта уже подтверждена. Welcome выдаётся один раз после проверки аккаунта; остаток — в профиле.');
        return;
      }
      final confirmed = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
                title: const Text('Подтверждение почты'),
                content: TextField(
                    controller: code,
                    obscureText: true,
                    keyboardType: TextInputType.number,
                    maxLength: 6,
                    decoration: const InputDecoration(
                        labelText: 'Код из письма · действует 10 минут')),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context, false),
                      child: const Text('Отмена')),
                  FilledButton(
                      onPressed: () => Navigator.pop(context, true),
                      child: const Text('Подтвердить'))
                ],
              ));
      if (confirmed != true || !mounted) return;
      final result = await BillingService().verification(
          'confirm', {'id': challenge['id'], 'code': code.text.trim()});
      subscriptionUsageRevision.value++;
      if (mounted)
        setState(() => _message = result['verified'] == true
            ? 'Почта подтверждена. Welcome выдаётся после проверки аккаунта при доступном фонде; остаток — в профиле.'
            : 'Код неверен или истёк.');
    } catch (_) {
      if (mounted)
        setState(() => _message = 'Подтверждение почты пока недоступно.');
    } finally {
      code.dispose();
    }
  }

  @override
  Widget build(BuildContext context) {
    final enabled =
        _catalogue?['enabled'] == true && _catalogue?['test'] == false;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const SizedBox(height: 20),
      const Text('Планируемые тарифы'),
      const Text(
          'Welcome · 1 000 000 на 14 дней, один раз после подтверждения почты и проверки аккаунта.'),
      if (_catalogue?['verification_enabled'] == true)
        OutlinedButton(
            onPressed: _busy ? null : _verifyEmail,
            child: const Text('Подтвердить почту и проверить Welcome')),
      const Text(
          'Free · 500 000 AI-токенов в месяц. Голос, текст, память, дела и напоминания. '
          'Поиск — до 10 задач; документы — до 3; снимки — до 5.'),
      for (final item in [
        (
          'plus',
          'Plus · 5 000 000 · 790 ₽/месяц',
          'Документы, поиск и небольшие проекты с кодом.'
        ),
        (
          'pro',
          'Pro · 10 000 000 · 1 490 ₽/месяц',
          'Сложные задачи, дорогие модели и до трёх одновременных задач.'
        ),
        (
          'top_up',
          '+1 000 000 · 99 ₽',
          'Действует 90 дней; функции тарифа сохраняются.'
        ),
      ]) ...[
        const SizedBox(height: 12),
        Text(item.$2),
        Text(item.$3),
        OutlinedButton(
            onPressed: enabled && !_busy ? () => _buy(item.$1, item.$2) : null,
            child: Text(
                item.$1 == 'top_up' ? 'Докупить токены' : 'Выбрать тариф')),
      ],
      if (!enabled)
        const Text(
            'Продажи откроются после подключения оплаты и проверки всех функций.'),
      if (_message != null) Text(_message!),
    ]);
  }
}
