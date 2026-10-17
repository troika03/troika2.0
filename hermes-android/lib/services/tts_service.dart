import 'package:flutter_tts/flutter_tts.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:audioplayers/audioplayers.dart';
import 'package:http/http.dart' as http;
import '../config/troika_config.dart';
import 'account_service.dart';
import 'streaming_speech.dart';

/// Hosted conversational voice; local system voice remains available offline.
class TtsService {
  static const voiceNameKey = 'troika_local_voice_name';
  static const voiceLocaleKey = 'troika_local_voice_locale';
  final FlutterTts _tts = FlutterTts();
  bool _isSpeaking = false;
  bool _initialized = false;
  final AudioPlayer _player = AudioPlayer();
  StreamingSpeech<Uint8List>? _reply;
  http.Client? _client;
  Completer<void>? _playDone;
  int _generation = 0;

  /// Start synthesis as each complete phrase arrives from the model.
  void beginReply() {
    final previous = _reply;
    previous?.cancel();
    _client?.close();
    final generation = ++_generation;
    final owner = TroikaConfig.accountEmail;
    final endpoint = TroikaConfig.serverUrl;
    final client = http.Client();
    _client = client;
    _isSpeaking = true;
    final reply = StreamingSpeech<Uint8List>(
      prepare: (text) async {
        if (!await AccountService().ensureFreshSession() ||
            generation != _generation || owner != TroikaConfig.accountEmail ||
            endpoint != TroikaConfig.serverUrl) {
          throw StateError('Голосовая сессия завершена.');
        }
        final request = http.Request('POST', Uri.parse('$endpoint/v1/audio/speech'))
          ..headers.addAll(TroikaConfig.headers)
          ..body = jsonEncode({'input': text, 'response_format': 'mp3'});
        final response = await client.send(request).timeout(const Duration(seconds: 12));
        if (generation != _generation || owner != TroikaConfig.accountEmail ||
            !TroikaConfig.signedIn || response.statusCode != 200 ||
            !response.headers['content-type'].toString().startsWith('audio/mpeg')) {
          throw StateError('Не удалось озвучить ответ.');
        }
        final audio = BytesBuilder(copy: false);
        await for (final part in response.stream.timeout(const Duration(seconds: 12))) {
          if (generation != _generation || audio.length + part.length > 10 * 1024 * 1024) {
            throw StateError('Озвучка прервана.');
          }
          audio.add(part);
        }
        if (audio.isEmpty) throw StateError('Пустой голосовой ответ.');
        return audio.takeBytes();
      },
      play: (audio) async {
        if (generation != _generation || owner != TroikaConfig.accountEmail) return;
        final done = Completer<void>();
        _playDone = done;
        final subscription = _player.onPlayerComplete.listen((_) {
          if (!done.isCompleted) done.complete();
        });
        try {
          await _player.setPlaybackRate(1.10);
          await _player.play(BytesSource(audio, mimeType: 'audio/mpeg'));
          await done.future.timeout(const Duration(seconds: 90));
        } finally {
          await subscription.cancel();
          if (identical(_playDone, done)) _playDone = null;
        }
      },
      discard: (audio) => audio.fillRange(0, audio.length, 0),
    );
    _reply = reply;
    // The caller observes errors at finishReply; suppress unhandled early errors.
    unawaited(reply.done.then<void>((_) {}, onError: (Object _) {}));
  }

  void addReplyDelta(String delta) => _reply?.add(delta);

  Future<void> finishReply() async {
    final reply = _reply;
    if (reply == null) return;
    try { await reply.finish(); }
    finally {
      if (identical(_reply, reply)) {
        _reply = null;
        _client?.close();
        _client = null;
        _isSpeaking = false;
      }
    }
  }

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
    if (TroikaConfig.signedIn && TroikaConfig.serverUrl.isNotEmpty) {
      await stop();
      beginReply();
      addReplyDelta(text);
      await finishReply();
      return;
    }
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
    ++_generation;
    _reply?.cancel();
    _reply = null;
    _client?.close();
    _client = null;
    final done = _playDone;
    if (done != null && !done.isCompleted) done.complete();
    await _player.stop();
    await _tts.stop();
    _isSpeaking = false;
  }

  void dispose() {
    unawaited(stop().whenComplete(_player.dispose));
  }
}
