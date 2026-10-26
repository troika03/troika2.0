// ignore_for_file: experimental_member_use

import 'dart:async';
import 'dart:typed_data';

import 'package:just_audio/just_audio.dart';

/// A single already-authorized MP3 body with bounded, in-memory replay.
///
/// Each request receives the complete body from byte zero. Range requests are
/// deliberately unsupported. The caller owns HTTP validation and must call
/// [cancel] on Stop, owner change, endpoint change, or disposal. Cancelling one
/// reader does not cancel the shared upstream because another GET may follow.
class LiveMp3Source extends StreamAudioSource {
  static const maximumBytes = 10 * 1024 * 1024;
  static const maximumReaders = 2;

  LiveMp3Source(
    Stream<List<int>> upstream, {
    required this.checkCurrent,
    int maxBytes = maximumBytes,
    this.onCancel,
  }) : _maxBytes = maxBytes {
    if (maxBytes < 1 || maxBytes > maximumBytes) {
      throw ArgumentError.value(maxBytes, 'maxBytes');
    }
    // Preserve the original future for late observers without an unhandled
    // error if prefetch fails before the caller attaches its own listener.
    unawaited(
      _done.future.then<void>((_) {}, onError: (Object _, StackTrace _) {}),
    );
    _starting = true;
    try {
      _subscription = upstream.listen(
        _receive,
        onError: (Object error, StackTrace stack) => _fail(error, stack),
        onDone: _finish,
        cancelOnError: true,
      );
    } catch (error, stack) {
      _fail(error, stack);
    } finally {
      _starting = false;
      if (_closed) _cancelUpstream();
    }
    _ensureCurrent();
  }

  final bool Function() checkCurrent;
  final int _maxBytes;
  final FutureOr<void> Function()? onCancel;
  final _chunks = <Uint8List>[];
  final _readers = <_Reader>{};
  final _done = Completer<void>();
  final _failureSignal = Completer<Object>();
  StreamSubscription<List<int>>? _subscription;
  Future<void>? _cancellation;
  Object? _error;
  StackTrace? _stack;
  int _bytes = 0;
  bool _starting = false;
  bool _closed = false;
  bool _upstreamDone = false;

  /// Upstream EOF or failure. This is not a playback-completion signal.
  Future<void> get done => _done.future;

  /// Resolves with the first failure or cancellation, including after EOF.
  ///
  /// Unlike an erroring future, this signal cannot produce an unhandled error.
  /// A caller can use it to stop playback even if the proxy ignores stream errors.
  Future<Object> get failure => _failureSignal.future;

  int get bufferedBytes => _bytes;
  int get activeReaders => _readers.length;

  bool _ensureCurrent() {
    if (_closed) return false;
    bool current;
    try {
      current = checkCurrent();
    } catch (_) {
      current = false;
    }
    if (!current) _fail(const LiveMp3Cancelled(), StackTrace.current);
    return current;
  }

  void _receive(List<int> chunk) {
    if (!_ensureCurrent()) return;
    if (chunk.length > _maxBytes - _bytes) {
      _fail(const LiveMp3LimitExceeded(), StackTrace.current);
      return;
    }
    if (chunk.isEmpty) return;
    // A producer or consumer cannot mutate another reader's replay bytes.
    _chunks.add(Uint8List.fromList(chunk).asUnmodifiableView());
    _bytes += chunk.length;

    for (final reader in _readers.toList()) {
      _schedule(reader);
    }
  }

  void _finish() {
    if (_closed) return;
    if (_bytes == 0) {
      _fail(StateError('Empty MP3 response.'), StackTrace.current);
      return;
    }
    _upstreamDone = true;

    if (!_done.isCompleted) _done.complete();
    for (final reader in _readers.toList()) {
      _schedule(reader);
    }
  }

  void _fail(Object error, StackTrace stack) {
    if (_closed) return;
    _closed = true;
    _error = error;
    _stack = stack;
    _chunks.clear();
    _bytes = 0;

    if (!_failureSignal.isCompleted) _failureSignal.complete(error);
    if (!_done.isCompleted) _done.completeError(error, stack);
    for (final reader in _readers.toList()) {
      _schedule(reader);
    }
    if (!_starting) _cancelUpstream();
  }

  Future<void> _cancelUpstream() {
    if (_cancellation != null) return _cancellation!;
    final future = () async {
      try {
        try {
          await _subscription?.cancel();
        } finally {
          await onCancel?.call();
        }
      } catch (_) {
        rethrow;
      }
    }();
    _cancellation = future;
    unawaited(future.then<void>((_) {}, onError: (Object _, StackTrace _) {}));
    return future;
  }

  /// Invalidates all readers, clears replay, and cancels upstream exactly once.
  Future<void> cancel() {
    _fail(const LiveMp3Cancelled(), StackTrace.current);
    return _cancelUpstream();
  }

  Future<void> close() => cancel();

  @override
  Future<StreamAudioResponse> request([int? start, int? end]) async {
    _ensureCurrent();
    if (_error != null) Error.throwWithStackTrace(_error!, _stack!);
    return StreamAudioResponse(
      rangeRequestsSupported: false,
      sourceLength: null,
      contentLength: null,
      offset: null,
      contentType: 'audio/mpeg',
      stream: _readerStream(),
    );
  }

  Stream<List<int>> _readerStream() {
    late _Reader reader;
    final controller = StreamController<List<int>>(
      sync: true,
      onListen: () {
        if (_readers.length >= maximumReaders) {
          reader.error = const LiveMp3ReaderLimit();
        } else {
          _readers.add(reader);
        }

        _schedule(reader);
      },
      onPause: () {
        reader.paused = true;
      },
      onResume: () {
        reader.paused = false;

        _schedule(reader);
      },
      onCancel: () {
        reader.cancelled = true;
        _readers.remove(reader);
      },
    );

    reader = _Reader(controller);
    return controller.stream;
  }

  void _schedule(_Reader reader) {
    if (reader.scheduled || reader.cancelled || reader.paused) return;
    reader.scheduled = true;
    scheduleMicrotask(() => _drain(reader));
  }

  void _drain(_Reader reader) {
    reader.scheduled = false;
    if (reader.cancelled || reader.paused) return;
    final error = reader.error ?? _error;
    if (error != null) {
      reader.cancelled = true;
      _readers.remove(reader);

      reader.controller.addError(error, _stack ?? StackTrace.current);
      unawaited(reader.controller.close());
      return;
    }
    if (!_ensureCurrent()) {
      _schedule(reader);
      return;
    }
    if (reader.index < _chunks.length) {
      final chunk = _chunks[reader.index++];
      // Synchronous delivery, one chunk per microtask, lets pause/cancel and
      // owner invalidation take effect before the next chunk is delivered.

      reader.controller.add(chunk);
      _schedule(reader);
    } else if (_upstreamDone) {
      reader.cancelled = true;
      _readers.remove(reader);

      unawaited(reader.controller.close());
    }
  }
}

class _Reader {
  _Reader(this.controller);
  final StreamController<List<int>> controller;
  int index = 0;
  bool scheduled = false;
  bool paused = false;
  bool cancelled = false;
  Object? error;
}

class LiveMp3Cancelled implements Exception {
  const LiveMp3Cancelled();
  @override
  String toString() => 'Live MP3 source is no longer current.';
}

class LiveMp3LimitExceeded implements Exception {
  const LiveMp3LimitExceeded();
  @override
  String toString() => 'Live MP3 source exceeded its byte limit.';
}

class LiveMp3ReaderLimit implements Exception {
  const LiveMp3ReaderLimit();
  @override
  String toString() => 'Live MP3 source has too many active readers.';
}
