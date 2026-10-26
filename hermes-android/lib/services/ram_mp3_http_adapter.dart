import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'ram_mp3_source.dart';

/// An owned loopback endpoint for one bounded RAM source, without disk audio.
///
/// The response retains Dart's HTTP framing and explicitly enables chunking.
/// No authorization headers or provider URLs are exposed to the audio player.
class RamMp3HttpAdapter {
  RamMp3HttpAdapter._(
    this._server,
    this._path,
    this.source,
    this.readerDeadline,
  );

  static Future<RamMp3HttpAdapter> bind(
    LiveMp3Source source, {
    Duration readerDeadline = const Duration(seconds: 90),
  }) async {
    if (readerDeadline <= Duration.zero ||
        readerDeadline > const Duration(minutes: 5)) {
      throw ArgumentError.value(readerDeadline, 'readerDeadline');
    }
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final random = Random.secure();
    final path =
        '/${base64UrlEncode(List.generate(24, (_) => random.nextInt(256))).replaceAll('=', '')}.mp3';
    final adapter = RamMp3HttpAdapter._(server, path, source, readerDeadline);
    server.listen(
      (request) => unawaited(adapter._serve(request).catchError((Object _) {})),
      onError: (Object _) {},
    );
    return adapter;
  }

  final HttpServer _server;
  final String _path;
  final LiveMp3Source source;
  final Duration readerDeadline;
  bool _closed = false;
  Future<void>? _closing;

  Uri get uri => Uri(
    scheme: 'http',
    host: InternetAddress.loopbackIPv4.address,
    port: _server.port,
    path: _path,
  );

  Future<void> _serve(HttpRequest request) async {
    final response = request.response;
    if (_closed || request.uri.path != _path || request.uri.hasQuery) {
      response.statusCode = HttpStatus.notFound;
      await response.close();
      return;
    }
    if (request.method != 'GET' && request.method != 'HEAD') {
      response.statusCode = HttpStatus.methodNotAllowed;
      await response.close();
      return;
    }

    StreamController<List<int>>? body;
    StreamSubscription<List<int>>? reader;
    Timer? deadline;
    var bodyEnded = false;
    try {
      response.statusCode = HttpStatus.ok;
      response.headers.contentType = ContentType('audio', 'mpeg');
      response.headers.set(HttpHeaders.cacheControlHeader, 'no-store');
      response.headers.chunkedTransferEncoding = true;

      if (request.method != 'HEAD') {
        final data = await source.request();
        body = StreamController<List<int>>(
          sync: true,
          onListen: () {
            reader = data.stream.listen(
              (chunk) {
                if (bodyEnded) return;
                body!.add(chunk);
              },
              onError: (Object error, StackTrace stack) {
                if (!bodyEnded) body!.addError(error, stack);
              },
              onDone: () {
                if (bodyEnded) return;
                bodyEnded = true;

                unawaited(body!.close());
              },
            );
          },
          onPause: () => reader?.pause(),
          onResume: () => reader?.resume(),
          onCancel: () => reader?.cancel(),
        );
        // Some silent disconnects are not reported until the next write. A
        // fixed reader deadline bounds that wait without new audio or disk IO.
        deadline = Timer(readerDeadline, () {
          if (bodyEnded) return;
          bodyEnded = true;

          unawaited(reader?.cancel());
          body!.addError(const _ReaderTimedOut());
          unawaited(body.close());
        });
        // Socket errors that are reported earlier release the reader directly.
        unawaited(
          response.done.then<void>(
            (_) {},
            onError: (Object _) {
              if (bodyEnded) return;
              bodyEnded = true;

              unawaited(reader?.cancel());
              body!.addError(const _ClientDisconnected());
              unawaited(body.close());
            },
          ),
        );
        await response.addStream(body.stream);
      }
      await response.close();
    } catch (_) {
      try {
        await response.close();
      } catch (_) {}
    } finally {
      deadline?.cancel();
      bodyEnded = true;
      await reader?.cancel();
      if (body != null && !body.isClosed) unawaited(body.close());
    }
  }

  /// Stop invalidates the RAM source and forcibly closes all owned responses.
  Future<void> close() => _closing ??= _close();

  Future<void> _close() async {
    _closed = true;

    try {
      await source.cancel();
    } finally {
      await _server.close(force: true);
    }
  }
}

class _ClientDisconnected implements Exception {
  const _ClientDisconnected();
}

class _ReaderTimedOut implements Exception {
  const _ReaderTimedOut();
}
