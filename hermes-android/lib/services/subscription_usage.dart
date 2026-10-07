import 'dart:convert';

import 'package:flutter/foundation.dart';

/// Invalidates visible usage after an accepted or rejected cloud request.
final subscriptionUsageRevision = ValueNotifier<int>(0);

String cloudRequestError(int status, String body) {
  if (status == 429) {
    try {
      final payload = jsonDecode(body) as Map<String, dynamic>;
      if (payload['error'] is Map &&
          payload['error']['code'] == 'daily_request_limit_exceeded') {
        final rawReset = payload['usage'] is Map
            ? payload['usage']['resets_at']?.toString()
            : null;
        final reset = DateTime.tryParse(rawReset ?? '')?.toLocal();
        final time = reset == null
            ? 'после обновления дневного лимита'
            : '${reset.day.toString().padLeft(2, '0')}.'
                '${reset.month.toString().padLeft(2, '0')} в '
                '${reset.hour.toString().padLeft(2, '0')}:'
                '${reset.minute.toString().padLeft(2, '0')}';
        return 'Дневной AI-лимит исчерпан. Новые запросы доступны $time. '
            'Локальные команды продолжают работать. Остаток — в профиле.';
      }
    } catch (_) {
      // A provider/rate-limit failure must not masquerade as a plan limit.
    }
    return 'Тройка временно перегружена. Попробуй через минуту.';
  }
  if (status == 401) return 'Вход в аккаунт истёк. Войди снова.';
  if (status == 503) return 'Сервис временно недоступен. Попробуй позже.';
  return 'Не удалось выполнить запрос ($status). Попробуй ещё раз.';
}
