import 'dart:async';

import 'package:flutter_test/flutter_test.dart';

import 'package:troika_assistant/services/ram_mp3_source.dart';

void main() {
  test('empty EOF fails and releases upstream once', () async {
    var cancelled = 0;
    final source = LiveMp3Source(
      const Stream.empty(),
      checkCurrent: () => true,
      onCancel: () => cancelled++,
    );
    await expectLater(source.done, throwsA(isA<StateError>()));
    expect(await source.failure, isA<StateError>());
    await source.cancel();
    await source.cancel();
    expect(source.bufferedBytes, 0);
    expect(cancelled, 1);
  });
  test('delivers first bytes before upstream EOF', () async {
    final input = StreamController<List<int>>();
    final source = LiveMp3Source(input.stream, checkCurrent: () => true);
    addTearDown(source.cancel);
    var ended = false;
    unawaited(source.done.then((_) => ended = true, onError: (Object _) {}));
    final reader = StreamIterator((await source.request()).stream);
    final first = reader.moveNext();
    input.add([1, 2, 3]);
    expect(await first, isTrue);
    expect(reader.current, [1, 2, 3]);
    expect(ended, isFalse);
    await reader.cancel();
    await input.close();
    await source.done;
  });

  test('replays every request with only one upstream subscription', () async {
    var listens = 0;
    final input = StreamController<List<int>>(onListen: () => listens++);
    final source = LiveMp3Source(input.stream, checkCurrent: () => true);
    addTearDown(source.close);
    input.add([1, 2]);
    input.add([3]);
    await input.close();
    for (var index = 0; index < 3; index++) {
      final response = await source.request();
      expect(await response.stream.expand((bytes) => bytes).toList(), [
        1,
        2,
        3,
      ]);
    }
    expect(listens, 1);
    expect(source.bufferedBytes, 3);
  });

  test(
    'unsupported Range always returns the full unknown-length body',
    () async {
      final source = LiveMp3Source(
        Stream.value([4, 5, 6]),
        checkCurrent: () => true,
      );
      addTearDown(source.close);
      await source.done;
      final response = await source.request(2, 3);
      expect(response.rangeRequestsSupported, isFalse);
      expect(response.sourceLength, isNull);
      expect(response.contentLength, isNull);
      expect(response.offset, isNull);
      expect(response.contentType, 'audio/mpeg');
      expect(await response.stream.expand((bytes) => bytes).toList(), [
        4,
        5,
        6,
      ]);
    },
  );

  test(
    'one shared byte budget cancels upstream and clears replay on overflow',
    () async {
      var cancelled = 0;
      final input = StreamController<List<int>>(onCancel: () => cancelled++);
      final source = LiveMp3Source(
        input.stream,
        checkCurrent: () => true,
        maxBytes: 3,
      );
      final response = await source.request();
      input.add([1, 2]);
      await Future<void>.delayed(Duration.zero);
      expect(source.bufferedBytes, 2);
      input.add([3, 4]);
      await expectLater(source.done, throwsA(isA<LiveMp3LimitExceeded>()));
      expect(await source.failure, isA<LiveMp3LimitExceeded>());
      await expectLater(
        response.stream,
        emitsError(isA<LiveMp3LimitExceeded>()),
      );
      await source.cancel();
      expect(source.bufferedBytes, 0);
      expect(cancelled, 1);
      await input.close();
    },
  );

  test(
    'prefetch failure remains observable without an early unhandled error',
    () async {
      var closed = 0;
      final input = StreamController<List<int>>();
      final source = LiveMp3Source(
        input.stream,
        checkCurrent: () => true,
        onCancel: () => closed++,
      );
      final error = StateError('Synthetic upstream failure');
      input.addError(error);
      await Future<void>.delayed(Duration.zero);
      expect(await source.failure, same(error));
      await expectLater(source.done, throwsA(same(error)));
      await expectLater(source.request(), throwsA(same(error)));
      await source.close();
      expect(closed, 1);
      await input.close();
    },
  );

  test('source error reaches an already waiting reader', () async {
    final input = StreamController<List<int>>();
    final source = LiveMp3Source(input.stream, checkCurrent: () => true);
    final reader = StreamIterator((await source.request()).stream);
    final next = reader.moveNext();
    final assertion = expectLater(next, throwsA(isA<StateError>()));
    input.addError(StateError('Synthetic failure'));
    await assertion;
    await reader.cancel();
    await source.close();
    await input.close();
  });

  test(
    'cancel wakes a pending reader and releases upstream exactly once',
    () async {
      var cancelled = 0;
      var callerCancelled = 0;
      final input = StreamController<List<int>>(onCancel: () => cancelled++);
      final source = LiveMp3Source(
        input.stream,
        checkCurrent: () => true,
        onCancel: () => callerCancelled++,
      );
      final reader = StreamIterator((await source.request()).stream);
      final assertion = expectLater(
        reader.moveNext(),
        throwsA(isA<LiveMp3Cancelled>()),
      );
      await source.cancel();
      await assertion;
      await source.close();
      expect(cancelled, 1);
      expect(callerCancelled, 1);
      expect(source.bufferedBytes, 0);
      expect(await source.failure, isA<LiveMp3Cancelled>());
      await reader.cancel();
      await input.close();
    },
  );

  test(
    'cancelling a pending reader does not wait for another upstream chunk',
    () async {
      final input = StreamController<List<int>>();
      final source = LiveMp3Source(input.stream, checkCurrent: () => true);
      final subscription = (await source.request()).stream.listen((_) {});
      await subscription.cancel().timeout(const Duration(seconds: 1));
      expect(source.activeReaders, 0);
      await source.cancel();
      await input.close();
    },
  );

  test(
    'incoming chunk invalidation closes upstream and rejects bytes',
    () async {
      var current = true;
      var cancelled = 0;
      final input = StreamController<List<int>>(onCancel: () => cancelled++);
      final source = LiveMp3Source(input.stream, checkCurrent: () => current);
      current = false;
      input.add([1]);
      expect(await source.failure, isA<LiveMp3Cancelled>());
      await expectLater(source.request(), throwsA(isA<LiveMp3Cancelled>()));
      await source.cancel();
      expect(source.bufferedBytes, 0);
      expect(cancelled, 1);
      await input.close();
    },
  );

  test(
    'replay rechecks current state between delivered chunks after EOF',
    () async {
      var current = true;
      final source = LiveMp3Source(
        Stream.fromIterable([
          [1],
          [2],
        ]),
        checkCurrent: () => current,
      );
      await source.done;
      final reader = StreamIterator((await source.request()).stream);
      expect(await reader.moveNext(), isTrue);
      expect(reader.current, [1]);
      current = false;
      await expectLater(reader.moveNext(), throwsA(isA<LiveMp3Cancelled>()));
      expect(await source.failure, isA<LiveMp3Cancelled>());
      expect(source.bufferedBytes, 0);
      await reader.cancel();
      await source.close();
    },
  );

  test(
    'only two readers may be active and cancelled slots can be reused',
    () async {
      final input = StreamController<List<int>>();
      final source = LiveMp3Source(input.stream, checkCurrent: () => true);
      final first = (await source.request()).stream.listen(
        (_) {},
        onError: (Object _) {},
      );
      final second = (await source.request()).stream.listen(
        (_) {},
        onError: (Object _) {},
      );
      expect(source.activeReaders, 2);
      await expectLater(
        (await source.request()).stream,
        emitsError(isA<LiveMp3ReaderLimit>()),
      );
      await first.cancel();
      final third = (await source.request()).stream.listen(
        (_) {},
        onError: (Object _) {},
      );
      expect(source.activeReaders, 2);
      await second.cancel();
      await third.cancel();
      await source.close();
      await input.close();
    },
  );

  test('producer mutation cannot change retained replay', () async {
    final bytes = [1, 2];
    final input = StreamController<List<int>>(sync: true);
    final source = LiveMp3Source(input.stream, checkCurrent: () => true);
    input.add(bytes);
    bytes[0] = 9;
    await input.close();
    expect(
      await (await source.request()).stream.expand((bytes) => bytes).toList(),
      [1, 2],
    );
    await source.close();
  });

  test('configuration cannot exceed the hard 10 MiB source limit', () {
    expect(
      () => LiveMp3Source(
        const Stream.empty(),
        checkCurrent: () => true,
        maxBytes: LiveMp3Source.maximumBytes + 1,
      ),
      throwsArgumentError,
    );
  });
}
