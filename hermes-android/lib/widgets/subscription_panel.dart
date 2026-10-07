import 'dart:async';

import 'package:flutter/material.dart';

import '../config/troika_config.dart';
import '../services/subscription_usage.dart';
import '../services/troika_api_service.dart';

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
    final resetLabel = reset == null
        ? 'Лимит обновляется ежедневно в 00:00 UTC'
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
              child: Text('из ${value.dailyLimit} AI-запросов осталось',
                  style: TextStyle(color: colors.onSurfaceVariant)),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Semantics(
          label: 'Использовано ${value.used} из ${value.dailyLimit} запросов',
          child: ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: LinearProgressIndicator(
              value: value.dailyLimit > 0
                  ? (value.used / value.dailyLimit).clamp(0.0, 1.0)
                  : 0,
              minHeight: 6,
              color: exhausted ? colors.error : colors.primary,
              backgroundColor: colors.primary.withValues(alpha: 0.12),
            ),
          ),
        ),
        const SizedBox(height: 12),
        Text('Сегодня использовано: ${value.used}',
            style: TextStyle(color: colors.onSurfaceVariant)),
        const SizedBox(height: 4),
        Text(resetLabel, style: TextStyle(color: colors.onSurfaceVariant)),
        if (!value.quotaEnforced) ...[
          const SizedBox(height: 12),
          Text('Ограничение отключено на сервере. Остаток справочный.',
              style: TextStyle(color: colors.error)),
        ],
        if (exhausted) ...[
          const SizedBox(height: 12),
          Text('Дневной AI-лимит исчерпан',
              style: TextStyle(color: colors.error)),
        ],
        const SizedBox(height: 20),
        Divider(color: colors.outlineVariant.withValues(alpha: 0.5)),
        const SizedBox(height: 12),
        Text(
            'Локальные команды не расходуют AI-лимит. '
            'История, память и сохранённые файлы остаются доступны.',
            style: TextStyle(color: colors.onSurfaceVariant, height: 1.4)),
      ],
    );
  }
}
