import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:crypto/crypto.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:open_filex/open_filex.dart';
import 'account_service.dart';
import 'request_identity.dart';

/// Один личный документ, созданный Тройкой для текущего аккаунта.
class TroikaFile {
  final String id;
  final String name;
  final int size;
  final double created; // unix-время
  final String ext;
  final String mimeType;
  final String? localPath;
  final TroikaRequestIdentity? _identity;

  TroikaFile({
    required this.id,
    required this.name,
    required this.size,
    required this.created,
    required this.ext,
    required this.mimeType,
    this.localPath,
    TroikaRequestIdentity? identity,
  }) : _identity = identity;

  factory TroikaFile.fromJson(
    Map<String, dynamic> j, {
    TroikaRequestIdentity? identity,
  }) => TroikaFile(
    id: (j['id'] ?? '').toString(),
    name: (j['filename'] ?? '').toString(),
    size: (j['size'] as num?)?.toInt() ?? 0,
    created: (j['created_at'] as num?)?.toDouble() ?? 0,
    ext: (j['kind'] ?? '').toString(),
    mimeType: (j['mime_type'] ?? 'application/octet-stream').toString(),
    localPath: j['local_path'] as String?,
    identity: identity,
  );

  DateTime get time =>
      DateTime.fromMillisecondsSinceEpoch((created * 1000).round());
}

class FileSaveResult {
  final bool saved;
  final String? error;

  const FileSaveResult._({required this.saved, this.error});

  const FileSaveResult.saved() : this._(saved: true);
  const FileSaveResult.cancelled() : this._(saved: false);
  const FileSaveResult.failed(String message)
    : this._(saved: false, error: message);
}

/// Доступ только к личным документам аутентифицированного пользователя.
class FilesService {
  final http.Client? _client;
  final Future<Directory> Function()? _documentsDirectory;
  FilesService({
    http.Client? client,
    Future<Directory> Function()? documentsDirectory,
  }) : _client = client,
       _documentsDirectory = documentsDirectory;

  static const Duration _timeout = Duration(seconds: 20);
  static const int _maxFileBytes = 50 * 1024 * 1024;
  static const MethodChannel _platform = MethodChannel(
    'com.troika.hermes/background',
  );

  Future<http.Response> _request(
    String method,
    TroikaRequestIdentity identity,
    String path, {
    int maxBytes = 4 * 1024 * 1024,
  }) async {
    identity.check();
    await AccountService().ensureFreshSession(checkRequest: identity.check);
    identity.check();
    final client = _client ?? http.Client();
    try {
      final request = http.Request(method, identity.uri(path))
        ..followRedirects = false
        ..headers.addAll(identity.headers());
      final response = await client.send(request).timeout(_timeout);
      identity.check();
      if ((response.contentLength ?? 0) > maxBytes) {
        throw const FormatException('Файл или список файлов слишком большой.');
      }
      final bytes = BytesBuilder(copy: false);
      await (() async {
        await for (final chunk in response.stream) {
          identity.check();
          if (bytes.length + chunk.length > maxBytes) {
            throw const FormatException(
              'Файл или список файлов слишком большой.',
            );
          }
          bytes.add(chunk);
        }
      })().timeout(const Duration(seconds: 60));
      identity.check();
      return http.Response.bytes(
        bytes.takeBytes(),
        response.statusCode,
        headers: response.headers,
        request: request,
      );
    } finally {
      if (_client == null) client.close();
    }
  }

  Future<Directory> localRoot() => _localRoot(TroikaRequestIdentity());

  Future<Directory> _localRoot(TroikaRequestIdentity identity) async {
    identity.check();
    final dir =
        await (_documentsDirectory?.call() ??
            getApplicationDocumentsDirectory());
    identity.check();
    final owner = sha256
        .convert(
          utf8.encode(
            identity.owner.isEmpty
                ? identity.session
                : identity.owner.toLowerCase(),
          ),
        )
        .toString();
    final root = Directory('${dir.path}/troika_files/$owner');
    await root.create(recursive: true);
    identity.check();
    return root;
  }

  Future<List<TroikaFile>> localFiles() => _localFiles(TroikaRequestIdentity());

  Future<List<TroikaFile>> _localFiles(TroikaRequestIdentity identity) async {
    final root = await _localRoot(identity);
    final files = <TroikaFile>[];
    await for (final item in root.list(followLinks: false)) {
      identity.check();
      if (item is! File || !item.path.endsWith('.metadata.json')) continue;
      try {
        final value =
            json.decode(await item.readAsString()) as Map<String, dynamic>;
        identity.check();
        final file = TroikaFile.fromJson(value, identity: identity);
        // Never trust a persisted path outside this account's app directory.
        if (validLocalIdentity(file.id, file.ext) &&
            file.localPath == '${root.path}/${file.id}.${file.ext}' &&
            await FileSystemEntity.type(file.localPath!, followLinks: false) ==
                FileSystemEntityType.file &&
            await File(file.localPath!).exists()) {
          identity.check();
          files.add(file);
        }
      } on RequestIdentityChanged {
        rethrow;
      } catch (_) {
        /* Ignore incomplete or malformed metadata. */
      }
    }
    identity.check();
    files.sort((a, b) => b.created.compareTo(a.created));
    return files;
  }

  /// Save bytes first, then metadata, and only then acknowledge the RAM handoff.
  Future<TroikaFile> receiveDeviceFile(Map<String, dynamic> artifact) =>
      _receiveDeviceFile(artifact, TroikaRequestIdentity());

  Future<TroikaFile> _receiveDeviceFile(
    Map<String, dynamic> artifact,
    TroikaRequestIdentity identity,
  ) async {
    identity.check();
    final id = (artifact['id'] ?? '').toString();
    final kind = (artifact['kind'] ?? '').toString();
    final expectedSize = (artifact['size'] as num?)?.toInt() ?? 0;
    if (!validLocalIdentity(id, kind) ||
        expectedSize <= 0 ||
        expectedSize > _maxFileBytes) {
      throw const FormatException('Некорректный файл от Тройки.');
    }
    final root = await _localRoot(identity);
    final target = File('${root.path}/$id.$kind');
    final path = '/v1/device-files/$id';
    // Lost acknowledgements may leave a delivery pending although its local copy is complete.
    if (await FileSystemEntity.type(target.path, followLinks: false) ==
        FileSystemEntityType.file) {
      if (await target.length() > _maxFileBytes) {
        throw const FormatException('Сохранённый файл слишком большой.');
      }
      final bytes = await target.readAsBytes();
      identity.check();
      if (sha256.convert(bytes).toString() == artifact['sha256']) {
        validateDeviceBytes(bytes, kind, expectedSize);
        final metadata = await _commitMetadata(target, artifact, identity);
        try {
          await _request('POST', identity, '$path/received');
        } catch (_) {
          identity.check();
        }
        identity.check();
        return TroikaFile.fromJson(metadata, identity: identity);
      }
      throw const FormatException(
        'Сохранённый файл отличается. Оригинал сохранён; попроси новую версию.',
      );
    }
    final response = await _request(
      'GET',
      identity,
      path,
      maxBytes: _maxFileBytes,
    );
    identity.check();
    if (response.statusCode != 200) {
      throw const HttpException(
        'Не удалось получить файл. Попроси Тройку создать его заново.',
      );
    }
    validateDeviceBytes(response.bodyBytes, kind, expectedSize);
    if (artifact['sha256'] != sha256.convert(response.bodyBytes).toString()) {
      throw const FormatException('Контрольная сумма файла не совпадает.');
    }
    final partial = File('${target.path}.partial');
    identity.check();
    await partial.writeAsBytes(response.bodyBytes, flush: true);
    identity.check();
    await partial.rename(target.path);
    identity.check();
    final metadata = await _commitMetadata(target, artifact, identity);
    // A lost acknowledgement does not undo a successful local save. TTL cleans it up.
    try {
      await _request('POST', identity, '$path/received');
    } catch (_) {
      identity.check();
    }
    identity.check();
    return TroikaFile.fromJson(metadata, identity: identity);
  }

  Future<Map<String, dynamic>> _commitMetadata(
    File target,
    Map<String, dynamic> artifact,
    TroikaRequestIdentity identity,
  ) async {
    identity.check();
    final metadata = {...artifact, 'local_path': target.path};
    final metaFile = File('${target.path}.metadata.json');
    final partial = File('${metaFile.path}.partial');
    await partial.writeAsString(json.encode(metadata), flush: true);
    identity.check();
    await partial.rename(metaFile.path);
    identity.check();
    return metadata;
  }

  static void validateDeviceBytes(
    Uint8List bytes,
    String kind,
    int expectedSize,
  ) {
    final signature = kind == 'pdf' ? [37, 80, 68, 70, 45] : [80, 75, 3, 4];
    if (bytes.length != expectedSize ||
        bytes.isEmpty ||
        bytes.length > 50 * 1024 * 1024 ||
        bytes.length < signature.length ||
        !List.generate(
          signature.length,
          (i) => bytes[i] == signature[i],
        ).every((v) => v)) {
      throw const FormatException('Файл повреждён или не завершён.');
    }
  }

  static bool validLocalIdentity(String id, String kind) =>
      RegExp(r'^delivery_[0-9a-f]{32}$').hasMatch(id) &&
      {'docx', 'pdf', 'pptx', 'zip'}.contains(kind);

  /// Recover deliveries missed when the app disconnected from a run's event stream.
  Future<void> recoverPending() => _recoverPending(TroikaRequestIdentity());

  Future<void> _recoverPending(TroikaRequestIdentity identity) async {
    final response = await _request('GET', identity, '/v1/device-files');
    identity.check();
    if (response.statusCode != 200) return;
    final body =
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    for (final artifact
        in (body['data'] as List? ?? []).whereType<Map<String, dynamic>>()) {
      identity.check();
      await _receiveDeviceFile(artifact, identity);
    }
  }

  Future<List<TroikaFile>> list() async {
    final identity = TroikaRequestIdentity();
    try {
      await _recoverPending(identity);
    } catch (_) {
      identity.check(); /* Local files remain available offline. */
    }
    final local = await _localFiles(identity);
    identity.check();
    try {
      final resp = await _request('GET', identity, '/v1/artifacts');
      identity.check();
      if (resp.statusCode == 404) return local;
      if (resp.statusCode != 200) {
        throw Exception('Не удалось получить файлы (${resp.statusCode}).');
      }
      final data =
          json.decode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      final raw = (data['data'] as List?) ?? const [];
      return [
        ...local,
        ...raw
            .whereType<Map<String, dynamic>>()
            .map((value) => TroikaFile.fromJson(value, identity: identity))
            .toList(),
      ];
    } on SocketException {
      identity.check();
      if (local.isNotEmpty) return local;
      rethrow;
    } catch (_) {
      identity.check();
      if (local.isNotEmpty) return local;
      rethrow;
    }
  }

  Future<File> _download(
    TroikaFile file,
    TroikaRequestIdentity identity,
  ) async {
    file._identity?.check();
    identity.check();
    if (file.localPath != null) {
      final root = await _localRoot(identity);
      if (!validLocalIdentity(file.id, file.ext) ||
          file.localPath != '${root.path}/${file.id}.${file.ext}' ||
          await FileSystemEntity.type(file.localPath!, followLinks: false) !=
              FileSystemEntityType.file) {
        throw const FormatException('Файл относится к другому аккаунту.');
      }
      identity.check();
      return File(file.localPath!);
    }
    if (!RegExp(r'^art_[0-9a-f]{32}$').hasMatch(file.id)) {
      throw const FormatException('Некорректный идентификатор файла.');
    }
    final resp = await _request(
      'GET',
      identity,
      '/v1/artifacts/${file.id}/download',
      maxBytes: _maxFileBytes,
    );
    identity.check();
    if (resp.statusCode != 200) {
      throw HttpException('Не удалось скачать файл (${resp.statusCode}).');
    }
    final dir = await getTemporaryDirectory();
    identity.check();
    final safeName = file.name.replaceAll(RegExp(r'[\\/:*?"<>|]'), '_');
    final target = File('${dir.path}/$safeName');
    await target.writeAsBytes(resp.bodyBytes, flush: true);
    identity.check();
    return target;
  }

  Future<String?> openFile(TroikaFile file) async {
    try {
      final identity = TroikaRequestIdentity();
      final downloaded = await _download(file, identity);
      identity.check();
      final result = await OpenFilex.open(downloaded.path);
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

  Future<String?> shareFile(TroikaFile file) async {
    try {
      final identity = TroikaRequestIdentity();
      final downloaded = await _download(file, identity);
      identity.check();
      final shared = await _platform.invokeMethod<bool>('shareFile', {
        'path': downloaded.path,
      });
      return shared == true ? null : 'Не удалось открыть меню «Поделиться».';
    } on PlatformException catch (e) {
      return 'Ошибка отправки: ${e.message ?? e.code}';
    } on SocketException {
      return 'Нет соединения с сервером.';
    } catch (e) {
      return 'Ошибка отправки: $e';
    }
  }

  /// Save a durable copy through the platform document picker.
  ///
  /// On Android/iOS file_picker writes [bytes] to the user-selected location.
  /// Desktop pickers return a path, so the copy is written here after choice.
  Future<FileSaveResult> saveToDevice(TroikaFile file) async {
    try {
      final identity = TroikaRequestIdentity();
      final downloaded = await _download(file, identity);
      final bytes = await downloaded.readAsBytes();
      identity.check();
      final isMobile = Platform.isAndroid || Platform.isIOS;
      final target = await FilePicker.platform.saveFile(
        dialogTitle: 'Сохранить файл на устройство',
        fileName: file.name,
        type: FileType.custom,
        allowedExtensions: [file.ext],
        bytes: isMobile ? bytes : null,
      );
      if (target == null) return const FileSaveResult.cancelled();
      identity.check();
      if (!isMobile) {
        await File(target).writeAsBytes(bytes, flush: true);
      }
      identity.check();
      return const FileSaveResult.saved();
    } on SocketException {
      return const FileSaveResult.failed('Нет соединения с сервером.');
    } catch (e) {
      return FileSaveResult.failed('Ошибка сохранения: $e');
    }
  }

  Future<String?> deleteFile(TroikaFile file) async {
    try {
      final identity = TroikaRequestIdentity();
      file._identity?.check();
      if (file.localPath != null) {
        final local = await _download(file, identity);
        identity.check();
        await local.delete();
        identity.check();
        final meta = File('${local.path}.metadata.json');
        if (await meta.exists()) await meta.delete();
        identity.check();
        return null;
      }
      if (!RegExp(r'^art_[0-9a-f]{32}$').hasMatch(file.id)) {
        return 'Некорректный идентификатор файла.';
      }
      final response = await _request(
        'DELETE',
        identity,
        '/v1/artifacts/${file.id}',
      );
      identity.check();
      if (response.statusCode == 200) return null;
      if (response.statusCode == 404) return 'Файл уже удалён.';
      return 'Не удалось удалить файл (${response.statusCode}).';
    } on SocketException {
      return 'Нет соединения с сервером.';
    } catch (e) {
      return 'Ошибка удаления: $e';
    }
  }
}
