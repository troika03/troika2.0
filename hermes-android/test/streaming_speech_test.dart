import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:troika_assistant/services/streaming_speech.dart';

void main() {
  test('first phrase plays before final text, in order with bounded preparation', () async {
    final firstPlayed = Completer<void>();
    final release = Completer<void>();
    final prepared = <String>[];
    final played = <String>[];
    final queue = StreamingSpeech<String>(
      prepare: (text) async { prepared.add(text); return text; },
      play: (text) async {
        played.add(text);
        if (played.length == 1) { firstPlayed.complete(); await release.future; }
      },
      discard: (_) {},
    );
    queue.add('[emo:');
    queue.add('joy] Привет! Второе предложение. Третье. Четвёртое.');
    await firstPlayed.future;
    expect(played, ['Привет!']);
    expect(prepared.length, lessThanOrEqualTo(3));
    queue.add(' Последняя часть');
    release.complete();
    await queue.finish();
    expect(played, ['Привет!', 'Второе предложение.', 'Третье.', 'Четвёртое.', 'Последняя часть']);
  });

  test('stop discards in-flight audio and never starts playback', () async {
    final audio = Completer<String>();
    final played = <String>[], discarded = <String>[];
    final queue = StreamingSpeech<String>(
      prepare: (_) => audio.future,
      play: (text) async { played.add(text); },
      discard: discarded.add,
    );
    queue.add('Привет!');
    queue.cancel();
    audio.complete('stale audio');
    await queue.done;
    await Future<void>.delayed(Duration.zero);
    expect(played, isEmpty);
    expect(discarded, ['stale audio']);
  });

  test('failed prefetch is reported without replaying previous phrases', () async {
    final played = <String>[];
    final queue = StreamingSpeech<String>(
      prepare: (text) async { if (text == 'Сбой.') throw StateError('offline'); return text; },
      play: (text) async { played.add(text); }, discard: (_) {},
    );
    queue.add('Первая. Сбой. Последняя.');
    await expectLater(queue.finish(), throwsStateError);
    expect(played, ['Первая.']);
  });
}
