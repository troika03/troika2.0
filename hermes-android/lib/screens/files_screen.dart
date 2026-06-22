import 'package:flutter/material.dart';
import '../services/files_service.dart';
import '../theme/troika_theme.dart';

/// Экран «Файлы» — документы, которые Тройка создаёт на сервере:
/// бизнес-разборы, research, отчёты (в .docx). Навигация по папкам,
/// тап на файл скачивает и открывает его (Word / Google Docs).
class FilesScreen extends StatefulWidget {
  const FilesScreen({super.key});

  @override
  State<FilesScreen> createState() => _FilesScreenState();
}

class _FilesScreenState extends State<FilesScreen> {
  final FilesService _svc = FilesService();
  final List<String> _crumbs = []; // стек папок (для «назад»)
  List<TroikaFile> _items = [];
  bool _loading = true;
  String? _error;
  String _openingPath = '';

  @override
  void initState() {
    super.initState();
    _load('');
  }

  String get _currentPath => _crumbs.isEmpty ? '' : _crumbs.last;

  Future<void> _load(String path) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final items = await _svc.list(path: path);
      if (!mounted) return;
      setState(() {
        _items = items;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  void _enterDir(TroikaFile dir) {
    _crumbs.add(dir.path);
    _load(dir.path);
  }

  Future<bool> _goBack() async {
    if (_crumbs.isEmpty) return true; // выйти с экрана
    _crumbs.removeLast();
    await _load(_currentPath);
    return false;
  }

  Future<void> _openFile(TroikaFile f) async {
    setState(() => _openingPath = f.path);
    final err = await _svc.openFile(f);
    if (!mounted) return;
    setState(() => _openingPath = '');
    if (err != null) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(err)));
    }
  }

  @override
  Widget build(BuildContext context) {
    return WillPopScope(
      onWillPop: _goBack,
      child: Scaffold(
        backgroundColor: TroikaColors.bg,
        appBar: AppBar(
          backgroundColor: TroikaColors.bg,
          title: Text(_crumbs.isEmpty ? 'Файлы Тройки' : _crumbs.last),
          leading: _crumbs.isEmpty
              ? null
              : IconButton(
                  icon: const Icon(Icons.arrow_back),
                  onPressed: _goBack,
                ),
          actions: [
            IconButton(
              icon: const Icon(Icons.refresh),
              onPressed: () => _load(_currentPath),
            ),
          ],
        ),
        body: RefreshIndicator(
          onRefresh: () => _load(_currentPath),
          child: _buildBody(),
        ),
      ),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return ListView(
        children: [
          const SizedBox(height: 80),
          Icon(Icons.cloud_off, size: 48, color: TroikaColors.textFaint),
          const SizedBox(height: 12),
          Center(
            child: Text(_error!,
                style: const TextStyle(color: TroikaColors.textMuted)),
          ),
        ],
      );
    }
    if (_items.isEmpty) {
      return ListView(
        children: [
          const SizedBox(height: 100),
          Center(
            child: Text('Здесь пока пусто',
                style: TextStyle(color: TroikaColors.textMuted)),
          ),
        ],
      );
    }
    return ListView.separated(
      padding: const EdgeInsets.symmetric(vertical: 6),
      itemCount: _items.length,
      separatorBuilder: (_, __) =>
          const Divider(height: 1, color: Colors.white10),
      itemBuilder: (_, i) => _row(_items[i]),
    );
  }

  Widget _row(TroikaFile f) {
    final isOpening = _openingPath == f.path;
    return ListTile(
      leading: Icon(
        f.isDir ? Icons.folder : _iconForExt(f.ext),
        color: f.isDir ? TroikaColors.brand : _colorForExt(f.ext),
      ),
      title: Text(
        f.name,
        style: const TextStyle(color: TroikaColors.text, fontSize: 15),
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
      ),
      subtitle: f.isDir
          ? null
          : Text(
              '${_fmtSize(f.size)} · ${_fmtDate(f.time)}',
              style: TextStyle(color: TroikaColors.textFaint, fontSize: 12),
            ),
      trailing: isOpening
          ? const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : (f.isDir
              ? const Icon(Icons.chevron_right, color: TroikaColors.textFaint)
              : null),
      onTap: () => f.isDir ? _enterDir(f) : _openFile(f),
    );
  }

  static IconData _iconForExt(String ext) {
    switch (ext) {
      case 'docx':
      case 'doc':
        return Icons.description;
      case 'pdf':
        return Icons.picture_as_pdf;
      case 'md':
      case 'txt':
        return Icons.article_outlined;
      case 'png':
      case 'jpg':
      case 'jpeg':
        return Icons.image_outlined;
      default:
        return Icons.insert_drive_file_outlined;
    }
  }

  static Color _colorForExt(String ext) {
    switch (ext) {
      case 'docx':
      case 'doc':
        return const Color(0xFF4A90D9); // Word-синий
      case 'pdf':
        return const Color(0xFFD9534F);
      default:
        return TroikaColors.textMuted;
    }
  }

  static String _fmtSize(int bytes) {
    if (bytes < 1024) return '$bytes Б';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(0)} КБ';
    return '${(bytes / 1024 / 1024).toStringAsFixed(1) } МБ';
  }

  static String _fmtDate(DateTime d) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final that = DateTime(d.year, d.month, d.day);
    final hm = '${d.hour.toString().padLeft(2, '0')}:'
        '${d.minute.toString().padLeft(2, '0')}';
    if (that == today) return 'сегодня $hm';
    return '${d.day.toString().padLeft(2, '0')}.'
        '${d.month.toString().padLeft(2, '0')} $hm';
  }
}
