class WebSource {
  final Uri uri;
  final String title;
  final String status;

  const WebSource(this.uri, this.title, this.status);

  String get statusLabel => switch (status) {
        'opening' => 'Открываю',
        'read' => 'Прочитано',
        'failed' => 'Не удалось прочитать',
        _ => 'Найдено',
      };

  static WebSource? fromJson(dynamic value) {
    if (value is! Map) return null;
    final url = value['url'];
    if (url is! String || url.length > 2048) return null;
    final uri = Uri.tryParse(url);
    if (uri == null ||
        !{'http', 'https'}.contains(uri.scheme) ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty) {
      return null;
    }
    final status = value['status'];
    if (!{'found', 'opening', 'read', 'failed'}.contains(status)) return null;
    final rawTitle = value['title'];
    final title = rawTitle is String ? rawTitle : '';
    return WebSource(uri, title.length > 240 ? title.substring(0, 240) : title,
        status as String);
  }
}

class WebSourceActivity {
  final String phase;
  final List<WebSource> sources;

  const WebSourceActivity(this.phase, this.sources);

  static WebSourceActivity? fromJson(dynamic value) {
    if (value is! Map ||
        !{'searching', 'reading', 'found', 'read', 'failed'}
            .contains(value['phase'])) {
      return null;
    }
    final rows = value['sources'];
    return WebSourceActivity(value['phase'] as String, [
      if (rows is List)
        for (final row in rows.take(20))
          if (WebSource.fromJson(row) case final WebSource source) source,
    ]);
  }
}

/// Source state belongs to one reply and is never included in model history.
class WebSourceTrace {
  String phase = '';
  final Map<String, WebSource> _sources = {};
  List<WebSource> get sources => List.unmodifiable(_sources.values);
  bool get isEmpty => phase.isEmpty && _sources.isEmpty;
  String get label => switch (phase) {
        'searching' => 'Ищу источники',
        'reading' => 'Читаю источники',
        'failed' => 'Поиск или чтение не удалось',
        _ => 'Источники',
      };

  void apply(WebSourceActivity activity) {
    phase = activity.phase;
    for (final source in activity.sources) {
      final key = source.uri.toString();
      final previous = _sources[key];
      if (previous?.status == 'read' && source.status == 'found') continue;
      if (_sources.length < 20 || previous != null) _sources[key] = source;
    }
  }

  void finish() {
    if (phase == 'searching' || phase == 'reading') phase = 'failed';
    for (final source in List<WebSource>.of(_sources.values)) {
      if (source.status == 'opening') {
        _sources[source.uri.toString()] =
            WebSource(source.uri, source.title, 'failed');
      }
    }
  }
}
