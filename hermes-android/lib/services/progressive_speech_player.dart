import 'package:just_audio/just_audio.dart' as audio;

/// Tests replace only the native device player at this boundary.
abstract interface class ProgressiveSpeechPlayer {
  Stream<bool> get completed;
  Stream<Object> get failures;
  Future<void> setSource(Uri uri);
  Future<void> play();
  Future<void> stop();
  Future<void> dispose();
}

class JustAudioSpeechPlayer implements ProgressiveSpeechPlayer {
  final audio.AudioPlayer _player = audio.AudioPlayer(
    audioLoadConfiguration: const audio.AudioLoadConfiguration(
      androidLoadControl: audio.AndroidLoadControl(
        minBufferDuration: Duration(milliseconds: 500),
        maxBufferDuration: Duration(seconds: 2),
        bufferForPlaybackDuration: Duration(milliseconds: 150),
        bufferForPlaybackAfterRebufferDuration: Duration(milliseconds: 250),
        prioritizeTimeOverSizeThresholds: true,
        backBufferDuration: Duration.zero,
      ),
    ),
  );
  @override
  Stream<bool> get completed => _player.playerStateStream.map(
    (state) => state.processingState == audio.ProcessingState.completed,
  );
  @override
  Stream<Object> get failures => _player.errorStream;
  @override
  Future<void> setSource(Uri uri) async {
    await _player.setAudioSource(audio.AudioSource.uri(uri), preload: false);
    await _player.setSpeed(1.10);
  }

  @override
  Future<void> play() => _player.play();
  @override
  Future<void> stop() => _player.stop();
  @override
  Future<void> dispose() => _player.dispose();
}
