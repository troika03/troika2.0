import 'dart:async';

/// Ordered speech with at most two prepared phrases and no full-reply wait.
class StreamingSpeech<T> {
  StreamingSpeech({required this.prepare, required this.play, required this.discard});

  final Future<T> Function(String) prepare;
  final Future<void> Function(T) play;
  final void Function(T) discard;
  final _ready = <Future<T>>[];
  final _pending = <String>[];
  final _done = Completer<void>();
  String _buffer = '';
  bool _closed = false, _cancelled = false, _running = false;
  Object? _error;

  Future<void> get done => _done.future;

  void add(String delta) {
    if (_closed || _cancelled || _error != null) return;
    _buffer += delta;
    // Keep hidden emotion tags intact even when split across network events.
    if (_buffer.trimLeft().startsWith('[emo:') && !_buffer.contains(']')) return;
    _buffer = _buffer.replaceAll(RegExp(r'\[emo:\s*[^\]]*\]'), '');
    while (_buffer.isNotEmpty) {
      final boundary = RegExp(r'[!?…](?:\s|$)|\.\s|\n').firstMatch(_buffer);
      var cut = boundary?.end ?? 0;
      if (cut == 0 && _buffer.length > 180) {
        cut = _buffer.lastIndexOf(' ', 180);
        if (cut <= 0) cut = 180;
      }
      if (cut == 0) break;
      _enqueue(_buffer.substring(0, cut));
      _buffer = _buffer.substring(cut);
    }
    _prefetch();
    _pump();
  }

  void _enqueue(String text) {
    final clean = text.replaceAll(RegExp(r'[*#`]'), '').trim();
    if (clean.isNotEmpty && _pending.length < 100) _pending.add(clean);
  }

  Future<void> finish() {
    if (!_closed && !_cancelled) {
      _closed = true;
      _enqueue(_buffer);
      _buffer = '';
      _pump();
    }
    return done;
  }

  void cancel() {
    _cancelled = true;
    _buffer = '';
    _pending.clear();
    for (final item in _ready) {
      unawaited(item.then(discard).catchError((Object _) {}));
    }
    _ready.clear();
    if (!_done.isCompleted) _done.complete();
  }

  void _prefetch() {
    while (!_cancelled && _ready.length < 2 && _pending.isNotEmpty) {
      final item = prepare(_pending.removeAt(0));
      // Observe early failures while the preceding phrase is still playing.
      unawaited(item.then<void>((_) {}, onError: (Object _) {}));
      _ready.add(item);
    }
  }

  void _pump() {
    if (_running || _cancelled) return;
    _running = true;
    unawaited(_drain());
  }

  Future<void> _drain() async {
    try {
      _prefetch();
      while (!_cancelled && _ready.isNotEmpty) {
        final next = _ready.removeAt(0);
        final audio = await next;
        if (_cancelled) { discard(audio); break; }
        _prefetch();
        try { await play(audio); } finally { discard(audio); }
        _prefetch();
      }
    } catch (error) {
      _error = error;
      _pending.clear();
      for (final item in _ready) {
        unawaited(item.then(discard).catchError((Object _) {}));
      }
      _ready.clear();
    } finally {
      _running = false;
      if ((_closed || _error != null) && !_done.isCompleted) {
        if (_error != null) { _done.completeError(_error!); }
        else { _done.complete(); }
      }
    }
  }
}
