import 'package:google_mlkit_translation/google_mlkit_translation.dart';

/// Офлайн-перевод «мыслей» Тройки EN→RU прямо на телефоне.
///
/// Reasoning-модели (gpt-oss, kimi) отдают ход рассуждений на английском —
/// это их внутренний язык. Чтобы Миша читал по-русски, переводим локально
/// через Google ML Kit: бесплатно, без сети (после разовой загрузки модели),
/// без обращения к мозгу Тройки (ноль токенов).
class ThoughtTranslator {
  ThoughtTranslator._();
  static final ThoughtTranslator instance = ThoughtTranslator._();

  final OnDeviceTranslator _translator = OnDeviceTranslator(
    sourceLanguage: TranslateLanguage.english,
    targetLanguage: TranslateLanguage.russian,
  );

  bool _modelReady = false;
  bool _modelDownloading = false;
  final Map<String, String> _cache = {};

  /// Запустить загрузку языковой модели в фоне (вызвать на старте приложения).
  /// Если модель уже скачана — ничего не делает.
  Future<void> warmUp() async {
    if (_modelReady || _modelDownloading) return;
    _modelDownloading = true;
    try {
      final mm = OnDeviceTranslatorModelManager();
      final downloaded =
          await mm.isModelDownloaded(TranslateLanguage.russian.bcpCode);
      if (!downloaded) {
        // requireWifi:false — качаем по любой сети; модель ~30 МБ, разово.
        await mm.downloadModel(TranslateLanguage.russian.bcpCode,
            isWifiRequired: false);
      }
      _modelReady = true;
    } catch (_) {
      // Не критично: если модель не скачалась, показываем оригинал (EN).
      _modelReady = false;
    } finally {
      _modelDownloading = false;
    }
  }

  /// Перевести текст EN→RU. Если модель не готова или текст уже на русском —
  /// вернуть оригинал (чтобы лента мыслей не зависала и не ломалась офлайн).
  Future<String> translate(String text) async {
    final src = text.trim();
    if (src.isEmpty) return text;
    // Уже кириллица — переводить не нужно.
    if (_looksRussian(src)) return text;
    if (_cache.containsKey(src)) return _cache[src]!;

    if (!_modelReady) {
      // Пробуем дотянуть модель; если не вышло — отдаём оригинал.
      await warmUp();
      if (!_modelReady) return text;
    }

    try {
      final ru = await _translator.translateText(src);
      final out = ru.trim().isEmpty ? text : ru;
      _cache[src] = out;
      return out;
    } catch (_) {
      return text;
    }
  }

  static bool _looksRussian(String s) {
    final cyr = RegExp(r'[А-Яа-яЁё]');
    final lat = RegExp(r'[A-Za-z]');
    final cyrCount = cyr.allMatches(s).length;
    final latCount = lat.allMatches(s).length;
    return cyrCount > latCount;
  }

  Future<void> dispose() async {
    await _translator.close();
  }
}
