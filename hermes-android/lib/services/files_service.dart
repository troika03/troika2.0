import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:open_filex/open_filex.dart';
import '../config/hermes_config.dart';

/// Один элемент файлового браузера (папка или файл) с сервера Тройки.
class TroikaFile {
  final String name;
  final String path; // путь относительно vault
  final bool isDir;
  final int size;
  final double modified; // unix-время
  final String ext;

  TroikaFile({
    required this.name,
    required this.path,
    required this.isDir,
    required this.size,
    required this.modified,
    required this.ext,
  });

  factory TroikaFile.fromJson(Map<String, dynamic> j) => TroikaFile(
        name: (j['name'] ?? '').toString(),
        path: (j['path'] ?? '').toString(),
        isDir: j['is_dir'] == true,
        size: (j['size'] as num?)?.toInt() ?? 0,
        modified: (j['modified'] as num?)?.toDouble() ?? 0,
        ext: (j['ext'] ?? '').toString(),
      );

  DateTime get time =>
      DateTime.fromMillisecondsSinceEpoch((modified * 1000).round());
}

/// Доступ к документам Тройки на сервере: листинг папок, открытие файлов.
/// Файлы (.docx и пр.) скачиваются во временную папку и открываются
/// системным приложением (Word / Google Docs).
class FilesService {
  static const Duration _timeout = Duration(seconds: 20);

  /// Список содержимого папки [path] (пусто = корень vault).
  Future<List<TroikaFile>> list({String path = ''}) async {
    final uri = Uri.parse(
        '${HermesConfig.filesUrl}?path=${Uri.encodeComponent(path)}');
    final resp =
        await http.get(uri, headers: HermesConfig.headers).timeout(_timeout);
    if (resp.statusCode == 404) return [];
    if (resp.statusCode != 200) {
      throw Exception('Не удалось получить файлы (${resp.statusCode}).');
    }
    final data = json.decode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
    final raw = (data['items'] as List?) ?? const [];
    return raw
        .whereType<Map<String, dynamic>>()
        .map(TroikaFile.fromJson)
        .toList();
  }

  /// Скачать файл во временную папку и открыть системным приложением.
  /// Возвращает сообщение об ошибке, либо null при успехе.
  Future<String?> openFile(TroikaFile file) async {
    try {
      final uri = Uri.parse(
          '${HermesConfig.filesUrl}/download?path=${Uri.encodeComponent(file.path)}');
      final resp =
          await http.get(uri, headers: HermesConfig.headers).timeout(
              const Duration(seconds: 60));
      if (resp.statusCode != 200) {
        return 'Не удалось скачать файл (${resp.statusCode}).';
      }
      final dir = await getTemporaryDirectory();
      final safeName = file.name.replaceAll(RegExp(r'[\\/:*?"<>|]'), '_');
      final f = File('${dir.path}/$safeName');
      await f.writeAsBytes(resp.bodyBytes);
      final result = await OpenFilex.open(f.path);
      if (result.type != ResultType.done) {
        return 'Нет приложения для открытия ${file.ext.toUpperCase()}. '
            'Установи Word или Google Документы.';
      }
      return null;
    } on SocketException {
      return 'Нет соединения с сервером.';
    } catch (e) {
      return 'Ошибка открытия: $e';
    }
  }
}
