import 'dart:async';

import 'package:flutter/material.dart';

import '../config/troika_config.dart';
import '../services/subscription_usage.dart';
import '../services/troika_api_service.dart';
import 'billing_panel.dart';
import 'own_api_panel.dart';

/// Shows server-owned usage; never substitutes cached or invented allowances.
class SubscriptionPanel extends StatefulWidget {
  final Future<AccountSubscription> Function()? load;

  const SubscriptionPanel({super.key, this.load});

  @override
  State<SubscriptionPanel> createState() => _SubscriptionPanelState();
}

class _SubscriptionPanelState extends State<SubscriptionPanel>
    with WidgetsBindingObserver {
  AccountSubscription? _subscription;
  String? _error;
  bool _loading = false;
  bool _reloadPending = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    subscriptionUsageRevision.addListener(_load);
    _load();
    // Covers native background voice and activity on a second device.
    _timer = Timer.periodic(const Duration(minutes: 1), (_) {
      if (mounted && (ModalRoute.of(context)?.isCurrent ?? true)) _load();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    subscriptionUsageRevision.removeListener(_load);
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _load();
  }

  Future<void> _load() async {
    if (_loading) {
      _reloadPending = true;
      return;
    }
    final account = TroikaConfig.accountEmail;
    if (!TroikaConfig.signedIn && widget.load == null) return;
    setState(() => _loading = true);
    try {
      final value =
          await (widget.load?.call() ?? TroikaApiService().getSubscription());
      if (!mounted || account != TroikaConfig.accountEmail) return;
      setState(() {
        _subscription = value;
        _error = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _subscription = null;
        _error = error is TroikaApiException
            ? error.message
            : 'Не удалось обновить лимиты. Проверь соединение.';
      });
    } finally {
      if (mounted) {
        setState(() => _loading = false);
        if (_reloadPending) {
          _reloadPending = false;
          unawaited(_load());
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final value = _subscription;
    return Material(
      color: colors.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(24),
        side: BorderSide(color: colors.outlineVariant.withValues(alpha: 0.5)),
      ),
      clipBehavior: Clip.antiAlias,
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text('Подписка и лимиты',
                      style: Theme.of(context).textTheme.titleLarge),
                ),
                IconButton(
                  tooltip: 'Обновить лимиты',
                  onPressed: _loading ? null : _load,
                  icon: _loading
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.refresh_rounded),
                ),
              ],
            ),
            if (value != null) SubscriptionUsageView(subscription: value),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(_error!, style: TextStyle(color: colors.onSurfaceVariant)),
              const SizedBox(height: 8),
              TextButton(onPressed: _load, child: const Text('Повторить')),
            ],
            if (widget.load == null) const BillingPanel(),
            if (widget.load == null) const OwnApiPanel(),
            if (value == null && _error == null)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 16),
                child: Text('Получаю тариф и остаток…'),
              ),
          ],
        ),
      ),
    );
  }
}

class SubscriptionUsageView extends StatelessWidget {
  final AccountSubscription subscription;

  const SubscriptionUsageView({super.key, required this.subscription});

  Widget _operationDetails(Map<String, dynamic> operation) {
    final usage =
        operation['usage'] is Map ? operation['usage'] as Map : const {};
    final tokens = usage['tokens'] is Map ? usage['tokens'] as Map : null;
    final service =
        usage['service_usage'] is Map ? usage['service_usage'] as Map : null;
    final charged = operation['charged_tokens'];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(charged == null
          ? 'Расход уточняется · резерв ${operation['reserved_tokens']} AI-токенов'
          : 'Списано $charged расчётных AI-токенов'),
      if (service?['tokens_upper_bound'] == 1)
        Text('Бесплатная модель передала разные счётчики: '
            'ответ ${service!['reported_completion_tokens']}, '
            'рассуждения ${service['reported_reasoning_tokens']}. '
            'Общее число — верхняя оценка. Вход и ответ учитываются без повторного сложения рассуждений.'),
      if (tokens != null && service?['tokens_upper_bound'] != 1)
        Text('Токены модели: вход ${tokens['input_tokens']}, '
            'cache ${tokens['cache_read_tokens']}, cache write ${tokens['cache_write_tokens']}, ответ ${tokens['output_tokens']}. '
            'Reasoning ${tokens['reasoning_tokens']} уже входит в ответ.'),
      if (service != null)
        Text('Расход по коэффициентам: ${service['cost_rub']} ₽ · '
            '${service['units']} ${service['unit'] == 'seconds' ? 'секунд' : service['unit'] == 'characters' ? 'символов' : 'токенов модели'}'),
      Text('Версия коэффициентов: ${operation['pricing_version']}'),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final value = subscription;
    final exhausted = value.quotaEnforced && value.remaining <= 0;
    final plan = switch (value.plan.toLowerCase()) {
      'free' => 'Free',
      'plus' => 'Plus',
      'pro' => 'Pro',
      'beta' => 'Beta',
      _ => value.plan,
    };
    final reset = value.resetsAt?.toLocal();
    if (!value.resourceEnforced) {
      return Padding(
        padding: const EdgeInsets.only(top: 16),
        child: Text(
            'Тройка $plan. Месячный учёт AI-токенов ещё не включён. '
            'Текущий баланс станет доступен после подключения учёта всех расходов. '
            'История, память и сохранённые файлы доступны.',
            style: TextStyle(color: colors.onSurfaceVariant, height: 1.4)),
      );
    }
    final resetLabel = reset == null
        ? 'Дата обновления уточняется на сервере'
        : 'Обновление ${reset.day.toString().padLeft(2, '0')}.'
            '${reset.month.toString().padLeft(2, '0')} в '
            '${reset.hour.toString().padLeft(2, '0')}:'
            '${reset.minute.toString().padLeft(2, '0')} · местное время';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 8),
        Text('Тройка $plan',
            style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w600,
                )),
        const SizedBox(height: 4),
        Text(value.status == 'active' ? 'Активный тариф' : 'Тариф недоступен',
            style: TextStyle(color: colors.onSurfaceVariant)),
        const SizedBox(height: 24),
        Wrap(
          crossAxisAlignment: WrapCrossAlignment.end,
          spacing: 8,
          runSpacing: 4,
          children: [
            Text('${value.remaining}',
                style: Theme.of(context).textTheme.displaySmall?.copyWith(
                      color: exhausted ? colors.error : colors.onSurface,
                      fontWeight: FontWeight.w600,
                    )),
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text('расчётных AI-токенов осталось',
                  style: TextStyle(color: colors.onSurfaceVariant)),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Semantics(
          label:
              'Использовано ${value.used}, в резерве ${value.reserved} AI-токенов',
          child: ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: LinearProgressIndicator(
              value: value.remaining + value.used + value.reserved > 0
                  ? ((value.used + value.reserved) /
                          (value.remaining + value.used + value.reserved))
                      .clamp(0.0, 1.0)
                  : 0,
              minHeight: 6,
              color: exhausted ? colors.error : colors.primary,
              backgroundColor: colors.primary.withValues(alpha: 0.12),
            ),
          ),
        ),
        const SizedBox(height: 12),
        Text('Использовано: ${value.used} · В резерве: ${value.reserved}',
            style: TextStyle(color: colors.onSurfaceVariant)),
        const SizedBox(height: 4),
        Text(resetLabel, style: TextStyle(color: colors.onSurfaceVariant)),
        if (value.operations.isNotEmpty)
          ExpansionTile(
            title: const Text('Расход последних операций'),
            tilePadding: EdgeInsets.zero,
            children: [
              for (final operation in value.operations.take(5))
                Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: _operationDetails(operation))
            ],
          ),
        if (!value.quotaEnforced) ...[
          const SizedBox(height: 12),
          Text('Ограничение отключено на сервере. Остаток справочный.',
              style: TextStyle(color: colors.error)),
        ],
        if (exhausted) ...[
          const SizedBox(height: 12),
          Text('AI-токены исчерпаны. Данные и локальные команды доступны.',
              style: TextStyle(color: colors.error)),
        ],
        const SizedBox(height: 20),
        Divider(color: colors.outlineVariant.withValues(alpha: 0.5)),
        const SizedBox(height: 12),
        Text(
            'В ресурс входят контекст, история, инструменты, ответ и облачный голос. '
            'Неиспользованный резерв возвращается после подтверждения расходов. '
            'Локальные команды не расходуют AI-токены. '
            'История, память и сохранённые файлы остаются доступны.',
            style: TextStyle(color: colors.onSurfaceVariant, height: 1.4)),
      ],
    );
  }
}
