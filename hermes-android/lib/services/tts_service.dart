import 'package:flutter_tts/flutter_tts.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Сервис озвучки текста (TTS)
/// Использует встроенный Android TTS — офлайн, нулевая задержка
class TtsService {
  static const voiceNameKey = 'troika_local_voice_name';
  static const voiceLocaleKey = 'troika_local_voice_locale';
  final FlutterTts _tts = FlutterTts();
  bool _isSpeaking = false;
  bool _initialized = false;

  bool get isSpeaking => _isSpeaking;

  Future<void> init() async {
    if (_initialized) return;

    await _tts.setLanguage('ru-RU');
    await _tts.setSpeechRate(0.65); // комфортная скорость
    await _tts.setVolume(1.0);
    await _tts.setPitch(1.0);
    await _tts.awaitSpeakCompletion(true);

    final prefs = await SharedPreferences.getInstance();
    final savedName = prefs.getString(voiceNameKey);
    final savedLocale = prefs.getString(voiceLocaleKey);

    // Выбрать сохранённый голос или первый доступный русский.
    final voices = await _tts.getVoices;
    if (voices is List) {
      final ruVoices = voices
          .where((v) =>
              v is Map && (v['locale']?.toString().startsWith('ru') ?? false))
          .toList();
      if (ruVoices.isNotEmpty) {
        final best = ruVoices.cast<Map>().firstWhere(
              (voice) => voice['name']?.toString() == savedName,
              orElse: () => ruVoices.first as Map,
            );
        if (best['name'] != null) {
          await _tts.setVoice({
            'name': best['name'],
            'locale': savedLocale ?? best['locale'],
          });
        }
      }
    }

    _tts.setStartHandler(() => _isSpeaking = true);
    _tts.setCompletionHandler(() => _isSpeaking = false);
    _tts.setErrorHandler((msg) => _isSpeaking = false);

    _initialized = true;
  }

  /// Произнести текст
  Future<void> speak(String text) async {
    await init();
    if (_isSpeaking) await stop();

    // Убрать лишние символы для TTS
    final clean = text
        .replaceAll(RegExp(r'\*+'), '')
        .replaceAll(RegExp(r'#+\s*'), '')
        .replaceAll(RegExp(r'`+'), '')
        .trim();

    if (clean.isEmpty) return;
    await _tts.speak(clean);
  }

  /// Остановить озвучку
  Future<void> stop() async {
    await _tts.stop();
    _isSpeaking = false;
  }

  void dispose() {
    _tts.stop();
  }
}
