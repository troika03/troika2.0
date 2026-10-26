import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;
import 'dart:typed_data';
import 'package:audioplayers/audioplayers.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../config/troika_config.dart';
import 'account_service.dart';
import 'progressive_speech_player.dart';
import 'ram_mp3_http_adapter.dart';
import 'ram_mp3_source.dart';
import 'streaming_speech.dart';

typedef SpeechAdapterBinder =
    Future<RamMp3HttpAdapter> Function(
      LiveMp3Source source,
      Duration readerDeadline,
    );

/// Android hosted speech streams authorized MP3 bytes through an owned RAM URL.
/// Desktop bytes and local system speech keep their existing playback backend.
class TtsService {
  TtsService({
    bool? progressive,
    ProgressiveSpeechPlayer Function()? playerFactory,
    SpeechAdapterBinder? bindAdapter,
    this.playbackDeadline = const Duration(seconds: 90),
    this.requestTimeout = const Duration(seconds: 12),
  }) : _progressive = progressive ?? Platform.isAndroid,
       _playerFactory = playerFactory ?? JustAudioSpeechPlayer.new,
       _bindAdapter =
           bindAdapter ??
           ((source, deadline) =>
               RamMp3HttpAdapter.bind(source, readerDeadline: deadline)) {
    if (playbackDeadline <= Duration.zero ||
        playbackDeadline > const Duration(minutes: 5) ||
        requestTimeout <= Duration.zero) {
      throw ArgumentError('Invalid speech deadline.');
    }
    TroikaConfig.voiceIdentityChanges.addListener(_identityChanged);
  }

  static const voiceNameKey = 'troika_local_voice_name';
  static const voiceLocaleKey = 'troika_local_voice_locale';
  final FlutterTts _tts = FlutterTts();
  final bool _progressive;
  final ProgressiveSpeechPlayer Function() _playerFactory;
  final SpeechAdapterBinder _bindAdapter;
  final Duration playbackDeadline, requestTimeout;
  bool _initialized = false, _localSpeaking = false, _disposed = false;
  int _generation = 0;
  SpeechReply? _reply;

  void _identityChanged() =>
      unawaited(stop().then<void>((_) {}, onError: (Object _) {}));

  /// A handle never redirects old deltas or cleanup to a newer reply.
  SpeechReply beginReply() {
    if (_disposed || !TroikaConfig.voiceSessionAvailable) {
      throw const SpeechCancelled();
    }
    final previous = _reply;
    final predecessor = previous?.cancel() ?? Future<void>.value();
    unawaited(predecessor.then<void>((_) {}, onError: (Object _) {}));
    final reply = SpeechReply._(this, ++_generation, predecessor);
    _reply = reply;
    return reply;
  }

  // Compatibility while callers migrate to per-turn SpeechReply handles.
  void addReplyDelta(String delta) => _reply?.add(delta);
  Future<void> finishReply() => _reply?.finish() ?? Future<void>.value();
  bool get isSpeaking => _reply != null || _localSpeaking;

  Future<void> init() async {
    if (_initialized || _disposed) return;
    await _tts.setLanguage('ru-RU');
    if (_disposed) return;
    await _tts.setSpeechRate(0.65);
    if (_disposed) return;
    await _tts.setVolume(1.0);
    if (_disposed) return;
    await _tts.setPitch(1.0);
    if (_disposed) return;
    await _tts.awaitSpeakCompletion(true);
    if (_disposed) return;
    final prefs = await SharedPreferences.getInstance();
    if (_disposed) return;
    final savedName = prefs.getString(voiceNameKey);
    final savedLocale = prefs.getString(voiceLocaleKey);
    final voices = await _tts.getVoices;
    if (_disposed) return;
    if (voices is List) {
      final ruVoices = voices
          .where(
            (v) =>
                v is Map && (v['locale']?.toString().startsWith('ru') ?? false),
          )
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
          if (_disposed) return;
        }
      }
    }
    _tts.setStartHandler(() => _localSpeaking = true);
    _tts.setCompletionHandler(() => _localSpeaking = false);
    _tts.setErrorHandler((_) => _localSpeaking = false);
    _initialized = true;
  }

  Future<void> speak(String text) async {
    final stopping = stop();
    final generation = _generation;
    await stopping;
    if (_disposed || generation != _generation) return;
    if (TroikaConfig.signedIn && TroikaConfig.serverUrl.isNotEmpty) {
      final reply = beginReply();
      reply.add(text);
      await reply.finish();
      return;
    }
    await init();
    if (_disposed || generation != _generation) return;
    final clean = text
        .replaceAll(RegExp(r'\*+'), '')
        .replaceAll(RegExp(r'#+\s*'), '')
        .replaceAll(RegExp(r'`+'), '')
        .trim();
    if (clean.isEmpty) return;
    await _tts.speak(clean);
  }

  /// Invalidate before awaiting a platform call, pending bind or source load.
  Future<void> stop() async {
    final generation = ++_generation;
    final reply = _reply;
    _reply = null;
    final closing = reply?.cancel() ?? Future<void>.value();
    await Future.wait<void>([closing, _tts.stop().then<void>((_) {})]);
    if (generation == _generation) _localSpeaking = false;
  }

  void dispose() {
    if (_disposed) return;
    _disposed = true;
    TroikaConfig.voiceIdentityChanges.removeListener(_identityChanged);
    unawaited(stop().then<void>((_) {}, onError: (Object _) {}));
  }
}

class SpeechReply {
  SpeechReply._(this._service, this._generation, this._predecessor)
    : _owner = TroikaConfig.accountEmail,
      _endpoint = TroikaConfig.serverUrl,
      _session = TroikaConfig.sessionId,
      _revision = TroikaConfig.voiceIdentityRevision {
    _queue = StreamingSpeech<_Phrase>(
      prepare: _prepare,
      play: (phrase) async {
        await _predecessor;
        _check();
        await phrase.play();
      },
      discard: (phrase) {
        unawaited(
          phrase.close().then<void>(
            (_) {
              _phrases.remove(phrase);
            },
            onError: (Object _) {
              _phrases.remove(phrase);
            },
          ),
        );
      },
    );
    unawaited(_queue.done.then<void>((_) {}, onError: (Object _) {}));
  }

  final TtsService _service;
  final int _generation, _revision;
  final String _owner, _endpoint, _session;
  final Future<void> _predecessor;
  late final StreamingSpeech<_Phrase> _queue;
  final _clients = <http.Client>{};
  final _sources = <LiveMp3Source>{};
  final _phrases = <_Phrase>{};
  bool _cancelled = false;
  Future<void>? _closing, _finishing;

  bool get isCurrent =>
      !_cancelled &&
      !_service._disposed &&
      identical(_service._reply, this) &&
      _generation == _service._generation &&
      _revision == TroikaConfig.voiceIdentityRevision &&
      TroikaConfig.voiceSessionAvailable &&
      _owner == TroikaConfig.accountEmail &&
      _endpoint == TroikaConfig.serverUrl &&
      _session == TroikaConfig.sessionId;

  void _check() {
    if (!isCurrent) throw const SpeechCancelled();
  }

  void add(String delta) {
    if (isCurrent) _queue.add(delta);
  }

  Future<_Phrase> _prepare(String text) async {
    _check();
    if (!await AccountService().ensureFreshSession(checkRequest: _check)) {
      throw const SpeechCancelled();
    }
    _check();
    final client = http.Client();
    _clients.add(client);
    LiveMp3Source? source;
    RamMp3HttpAdapter? adapter;
    try {
      final request =
          http.Request('POST', Uri.parse('$_endpoint/v1/audio/speech'))
            ..followRedirects = false
            ..headers.addAll(TroikaConfig.headers)
            ..body = jsonEncode({
              'input': text,
              'response_format': 'mp3',
              if (_service._progressive) 'stream': true,
            });
      final response = await client
          .send(request)
          .timeout(_service.requestTimeout);
      _check();
      if (response.statusCode != 200 ||
          response.headers['content-type']
                  ?.split(';')
                  .first
                  .trim()
                  .toLowerCase() !=
              'audio/mpeg') {
        throw StateError('Не удалось озвучить ответ.');
      }
      final _Phrase phrase;
      if (_service._progressive) {
        source = LiveMp3Source(
          response.stream.timeout(_service.requestTimeout),
          checkCurrent: () => isCurrent,
          onCancel: () => client.close(),
        );
        _sources.add(source);
        adapter = await _service._bindAdapter(
          source,
          _service.playbackDeadline,
        );
        _check();
        phrase = _ProgressivePhrase(this, source, adapter, client);
      } else {
        final bytes = BytesBuilder(copy: false);
        await for (final part in response.stream.timeout(
          _service.requestTimeout,
        )) {
          _check();
          if (bytes.length + part.length > LiveMp3Source.maximumBytes) {
            throw const LiveMp3LimitExceeded();
          }
          bytes.add(part);
        }
        _check();
        if (bytes.isEmpty) throw StateError('Пустой голосовой ответ.');
        phrase = _BufferedPhrase(this, bytes.takeBytes());
        client.close();
        _clients.remove(client);
      }
      _phrases.add(phrase);
      return phrase;
    } catch (_) {
      await adapter?.close();
      await source?.cancel();
      _sources.remove(source);
      client.close();
      _clients.remove(client);
      rethrow;
    }
  }

  Future<void> finish() => _finishing ??= _finish();
  Future<void> _finish() async {
    if (!isCurrent) return;
    try {
      await _queue.finish();
    } finally {
      await cancel();
      if (identical(_service._reply, this)) _service._reply = null;
    }
  }

  Future<void> cancel() {
    if (_closing != null) return _closing!;
    final done = Completer<void>();
    _closing = done.future;
    _cancelled = true;
    _queue.cancel();
    for (final client in _clients) {
      client.close();
    }
    _clients.clear();
    unawaited(
      Future.wait<void>([
        for (final source in _sources.toList()) source.cancel(),
        for (final phrase in _phrases.toList()) phrase.close(),
      ]).then<void>(
        (_) {
          _phrases.clear();
          _sources.clear();
          done.complete();
        },
        onError: (Object error, StackTrace stack) {
          done.completeError(error, stack);
        },
      ),
    );
    return _closing!;
  }
}

abstract class _Phrase {
  Future<void> play();
  Future<void> close();
}

class _ProgressivePhrase implements _Phrase {
  _ProgressivePhrase(this.reply, this.source, this.adapter, this.client);
  final SpeechReply reply;
  final LiveMp3Source source;
  final RamMp3HttpAdapter adapter;
  final http.Client client;
  ProgressiveSpeechPlayer? _player;
  final _cancelled = Completer<void>();
  Future<void>? _closing;

  @override
  Future<void> play() async {
    reply._check();
    final player = reply._service._playerFactory();
    _player = player;
    final done = Completer<void>();
    final nativeError = Completer<Object>();
    void failNative(Object error, [StackTrace? stack]) {
      if (!nativeError.isCompleted) nativeError.complete(error);
      if (!done.isCompleted) done.completeError(error, stack);
    }

    final subscription = player.completed.listen(
      (completed) {
        if (completed && !done.isCompleted) done.complete();
      },
      onError: (Object error, StackTrace stack) {
        failNative(error, stack);
      },
    );
    // Decoder failures arrive on just_audio.errorStream independently of play().
    final failures = player.failures.listen((error) {
      failNative(error);
    });
    final watch = Stopwatch()..start();
    Duration remaining() => reply._service.playbackDeadline - watch.elapsed;
    final cancelled = _cancelled.future.then<void>(
      (_) => throw const SpeechCancelled(),
    );
    final failure = source.failure.then<void>((error) => throw error);
    final failedNative = nativeError.future.then<void>((error) => throw error);
    unawaited(cancelled.then<void>((_) {}, onError: (Object _) {}));
    unawaited(failure.then<void>((_) {}, onError: (Object _) {}));
    unawaited(failedNative.then<void>((_) {}, onError: (Object _) {}));
    unawaited(done.future.then<void>((_) {}, onError: (Object _) {}));
    try {
      await Future.any<void>([
        player.setSource(adapter.uri),
        cancelled,
        failure,
        failedNative,
      ]).timeout(remaining());
      reply._check();
      if (_cancelled.isCompleted) throw const SpeechCancelled();
      final playing = player.play();
      unawaited(
        playing.then<void>(
          (_) {},
          onError: (Object error, StackTrace stack) {
            if (!done.isCompleted) done.completeError(error, stack);
          },
        ),
      );
      final eof = source.done.then<void>((_) {
        if (source.bufferedBytes == 0) {
          throw StateError('Пустой голосовой ответ.');
        }
      });
      // play() fulfilment and upstream EOF alone never prove playback success.
      await Future.any<void>([
        Future.wait<void>([
          done.future,
          eof,
        ], eagerError: true).then<void>((_) {}),
        cancelled,
        failure,
        failedNative,
      ]).timeout(remaining());
      reply._check();
    } finally {
      await subscription.cancel();
      await failures.cancel();
    }
  }

  @override
  Future<void> close() => _closing ??= _close();
  Future<void> _close() async {
    if (!_cancelled.isCompleted) _cancelled.complete();
    client.close();
    reply._clients.remove(client);
    reply._sources.remove(source);
    final player = _player;
    try {
      await adapter.close();
    } finally {
      if (player != null) {
        try {
          await player.stop();
        } finally {
          await player.dispose();
        }
      }
    }
  }
}

class _BufferedPhrase implements _Phrase {
  _BufferedPhrase(this.reply, this.bytes);
  final SpeechReply reply;
  final Uint8List bytes;
  AudioPlayer? _player;
  final _done = Completer<void>();
  Future<void>? _closing;

  @override
  Future<void> play() async {
    reply._check();
    final player = AudioPlayer();
    _player = player;
    final subscription = player.onPlayerComplete.listen((_) {
      if (!_done.isCompleted) _done.complete();
    });
    try {
      await player.setPlaybackRate(1.10);
      reply._check();
      await player.play(BytesSource(bytes, mimeType: 'audio/mpeg'));
      reply._check();
      await _done.future.timeout(reply._service.playbackDeadline);
    } finally {
      await subscription.cancel();
    }
  }

  @override
  Future<void> close() => _closing ??= _close();
  Future<void> _close() async {
    if (!_done.isCompleted) _done.complete();
    bytes.fillRange(0, bytes.length, 0);
    final player = _player;
    if (player != null) {
      try {
        await player.stop();
      } finally {
        await player.dispose();
      }
    }
  }
}

class SpeechCancelled implements Exception {
  const SpeechCancelled();
  @override
  String toString() => 'Speech reply is no longer current.';
}
