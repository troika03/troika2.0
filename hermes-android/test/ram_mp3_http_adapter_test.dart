import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:troika_assistant/services/ram_mp3_source.dart';
import 'package:troika_assistant/services/ram_mp3_http_adapter.dart';

Future<void> waitFor(bool Function() predicate) async {
  final until = DateTime.now().add(const Duration(seconds: 2));
  while (!predicate() && DateTime.now().isBefore(until)) {
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
  expect(predicate(), isTrue);
}

void main() {
  test(
    'actual HTTP sends bytes before upstream EOF and finishes exactly',
    () async {
      final input = StreamController<List<int>>();
      final source = LiveMp3Source(input.stream, checkCurrent: () => true);
      final adapter = await RamMp3HttpAdapter.bind(source);
      final client = HttpClient();
      addTearDown(() async {
        client.close(force: true);
        await adapter.close();
        await input.close();
      });
      final responseFuture = client
          .getUrl(adapter.uri)
          .then((request) => request.close());
      final first = List.generate(20000, (index) => index % 251);
      final tail = List.generate(4000, (index) => (index + 17) % 251);
      input.add(first);
      final response = await responseFuture.timeout(const Duration(seconds: 2));
      expect(response.statusCode, 200);
      expect(response.contentLength, -1);
      expect(response.headers.chunkedTransferEncoding, true);
      final bytes = <int>[];
      final gotFirst = Completer<void>();
      final ended = Completer<void>();
      response.listen(
        (chunk) {
          bytes.addAll(chunk);
          if (bytes.length >= first.length && !gotFirst.isCompleted) {
            gotFirst.complete();
          }
        },
        onDone: ended.complete,
        onError: ended.completeError,
      );
      await gotFirst.future.timeout(const Duration(seconds: 2));
      expect(ended.isCompleted, false);
      expect(bytes, first);
      input.add(tail);
      await input.close();
      await ended.future.timeout(const Duration(seconds: 2));
      expect(bytes, [...first, ...tail]);
      expect(source.activeReaders, 0);
    },
  );

  test(
    'actual HTTP repeats full 200 body for Range with one upstream listen',
    () async {
      var subscriptions = 0;
      final input = StreamController<List<int>>(
        onListen: () => subscriptions++,
      );
      final source = LiveMp3Source(input.stream, checkCurrent: () => true);
      final adapter = await RamMp3HttpAdapter.bind(source);
      final client = HttpClient();
      addTearDown(() async {
        client.close(force: true);
        await adapter.close();
      });
      final expected = List.generate(33000, (index) => index % 251);
      input.add(expected);
      await input.close();
      for (final range in [null, 'bytes=100-499', 'bytes=12345-']) {
        final request = await client.getUrl(adapter.uri);
        if (range != null) request.headers.set(HttpHeaders.rangeHeader, range);
        final response = await request.close();
        expect(response.statusCode, 200);
        expect(response.headers.value(HttpHeaders.contentRangeHeader), isNull);
        expect(
          await response
              .expand((chunk) => chunk)
              .toList()
              .timeout(const Duration(seconds: 2)),
          expected,
        );
      }
      expect(subscriptions, 1);
      expect(source.activeReaders, 0);
    },
  );

  test(
    'Stop ends pending HTTP and cancels upstream once without more bytes',
    () async {
      var cancellations = 0;
      final input = StreamController<List<int>>(
        onCancel: () => cancellations++,
      );
      final source = LiveMp3Source(input.stream, checkCurrent: () => true);
      final adapter = await RamMp3HttpAdapter.bind(source);
      final client = HttpClient();
      addTearDown(() async {
        client.close(force: true);
        await adapter.close();
        await input.close();
      });
      final responseFuture = client
          .getUrl(adapter.uri)
          .then((request) => request.close());
      input.add(List.filled(20000, 7));
      final response = await responseFuture.timeout(const Duration(seconds: 2));
      final first = Completer<void>();
      final ended = Completer<void>();
      response.listen(
        (_) {
          if (!first.isCompleted) first.complete();
        },
        onDone: () {
          if (!ended.isCompleted) ended.complete();
        },
        onError: (Object _) {
          if (!ended.isCompleted) ended.complete();
        },
      );
      await first.future.timeout(const Duration(seconds: 2));
      await adapter.close().timeout(const Duration(seconds: 2));
      await adapter.close();
      await ended.future.timeout(const Duration(seconds: 2));
      await waitFor(() => source.activeReaders == 0);
      expect(source.bufferedBytes, 0);
      expect(cancellations, 1);
    },
  );

  test(
    'client disconnect releases reader by its fixed deadline without new bytes',
    () async {
      final input = StreamController<List<int>>();
      final source = LiveMp3Source(input.stream, checkCurrent: () => true);
      final adapter = await RamMp3HttpAdapter.bind(
        source,
        readerDeadline: const Duration(milliseconds: 200),
      );
      final client = HttpClient();
      addTearDown(() async {
        client.close(force: true);
        await adapter.close();
        await input.close();
      });
      final responseFuture = client
          .getUrl(adapter.uri)
          .then((request) => request.close());
      input.add(List.filled(20000, 7));
      final response = await responseFuture.timeout(const Duration(seconds: 2));
      final first = Completer<void>();
      response.listen((_) {
        if (!first.isCompleted) first.complete();
      }, onError: (Object _) {});
      await first.future.timeout(const Duration(seconds: 2));
      expect(source.activeReaders, 1);
      client.close(force: true);
      await waitFor(() => source.activeReaders == 0);
    },
  );

  test('unguessable path and method guard do not open a reader', () async {
    final source = LiveMp3Source(
      const Stream.empty(),
      checkCurrent: () => true,
    );
    final adapter = await RamMp3HttpAdapter.bind(source);
    final client = HttpClient();
    addTearDown(() async {
      client.close(force: true);
      await adapter.close();
    });
    expect(adapter.uri.host, '127.0.0.1');
    expect(adapter.uri.path.length, greaterThan(32));
    final wrong = await (await client.getUrl(
      adapter.uri.replace(path: '/wrong'),
    )).close();
    expect(wrong.statusCode, 404);
    await wrong.drain<void>();
    final method = await (await client.postUrl(adapter.uri)).close();
    expect(method.statusCode, 405);
    await method.drain<void>();
    final head = await (await client.openUrl('HEAD', adapter.uri)).close();
    expect(head.statusCode, 200);
    expect(await head.expand((chunk) => chunk).toList(), isEmpty);
    expect(source.activeReaders, 0);
  });
}
