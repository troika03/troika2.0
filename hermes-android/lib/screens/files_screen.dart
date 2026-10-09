import '../widgets/troika_page.dart';
import 'package:flutter/material.dart';
import '../services/files_service.dart';
import 'local_documents_screen.dart';

/// Личные документы текущего аккаунта Тройки.
class FilesScreen extends StatefulWidget {
  const FilesScreen({super.key});

  @override
  State<FilesScreen> createState() => _FilesScreenState();
}

class _FilesScreenState extends State<FilesScreen> {
  final FilesService _svc = FilesService();
  List<TroikaFile> _items = [];
  bool _loading = true;
  String? _error;
  String _busyId = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final items = await _svc.list();
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

  Future<void> _openFile(TroikaFile f) async {
    setState(() => _busyId = f.id);
    final err = await _svc.openFile(f);
    if (!mounted) return;
    setState(() => _busyId = '');
    if (err != null) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(err)));
    }
  }

  Future<void> _shareFile(TroikaFile f) async {
    setState(() => _busyId = f.id);
    final err = await _svc.shareFile(f);
    if (!mounted) return;
    setState(() => _busyId = '');
    if (err != null) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(err)));
    }
  }

  Future<void> _saveFile(TroikaFile f) async {
    setState(() => _busyId = f.id);
    final result = await _svc.saveToDevice(f);
    if (!mounted) return;
    setState(() => _busyId = '');
    if (result.error != null) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(result.error!)));
      return;
    }
    if (result.saved) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('«${f.name}» сохранён на телефоне')),
      );
    }
  }

  Future<void> _deleteFile(TroikaFile f) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Удалить файл?'),
        content: Text('«${f.name}» будет удалён из личных файлов Тройки.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Удалить'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _busyId = f.id);
    final err = await _svc.deleteFile(f);
    if (!mounted) return;
    setState(() => _busyId = '');
    if (err != null) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(err)));
      return;
    }
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    return TroikaPage(
      backgroundColor: TroikaPalette.of(context).bg,
      appBar: AppBar(
        backgroundColor: TroikaPalette.of(context).bg,
        title: const Text('Файлы Тройки'),
        actions: [
          IconButton(
            tooltip: 'Обновить',
            icon: const Icon(Icons.refresh),
            onPressed: _load,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: _buildBody(),
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
          TroikaEmptyState(
              icon: Icons.cloud_off_outlined,
              title: 'Не удалось загрузить файлы',
              message: _error!,
              actionLabel: 'Повторить',
              onAction: _load),
        ],
      );
    }
    if (_items.isEmpty) {
      return ListView(
        children: [
          TroikaEmptyState(
              icon: Icons.folder_open_outlined,
              title: 'Здесь пока пусто',
              message:
                  'Создай документ или попроси Тройку подготовить файл. Сохранённые результаты появятся здесь.',
              actionLabel: 'Создать документ',
              onAction: () => Navigator.push(
                  context,
                  MaterialPageRoute(
                      builder: (_) => const TroikaPageScope(
                          child: LocalDocumentsScreen())))),
        ],
      );
    }
    return ListView.separated(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
      itemCount: _items.length,
      separatorBuilder: (_, __) => const SizedBox(height: 12),
      itemBuilder: (_, i) => _row(_items[i]),
    );
  }

  Widget _row(TroikaFile f) {
    final isBusy = _busyId == f.id;
    return Card(
        clipBehavior: Clip.antiAlias,
        child: ListTile(
          leading:
              TroikaIcon(icon: _iconForExt(f.ext), color: _colorForExt(f.ext)),
          title: Text(
            f.name,
            style:
                TextStyle(color: TroikaPalette.of(context).text, fontSize: 15),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
          subtitle: Text(
            '${_fmtSize(f.size)} · ${_fmtDate(f.time)}',
            style: TextStyle(
                color: TroikaPalette.of(context).textFaint, fontSize: 12),
          ),
          trailing: isBusy
              ? const SizedBox(
                  width: 24,
                  height: 24,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    IconButton(
                      tooltip: 'Сохранить на телефон',
                      icon: const Icon(Icons.download_outlined),
                      onPressed: () => _saveFile(f),
                    ),
                    PopupMenuButton<String>(
                      tooltip: 'Другие действия',
                      onSelected: (action) {
                        if (action == 'open') _openFile(f);
                        if (action == 'save') _saveFile(f);
                        if (action == 'share') _shareFile(f);
                        if (action == 'delete') _deleteFile(f);
                      },
                      itemBuilder: (_) => const [
                        PopupMenuItem(value: 'open', child: Text('Открыть')),
                        PopupMenuItem(
                          value: 'save',
                          child: Text('Сохранить на телефон'),
                        ),
                        PopupMenuItem(
                            value: 'share', child: Text('Поделиться')),
                        PopupMenuDivider(),
                        PopupMenuItem(value: 'delete', child: Text('Удалить')),
                      ],
                    ),
                  ],
                ),
          onTap: isBusy ? null : () => _openFile(f),
        ));
  }

  static IconData _iconForExt(String ext) {
    switch (ext) {
      case 'docx':
      case 'doc':
        return Icons.description;
      case 'pdf':
        return Icons.picture_as_pdf;
      case 'pptx':
      case 'ppt':
        return Icons.slideshow;
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

  Color _colorForExt(String ext) {
    switch (ext) {
      case 'docx':
      case 'doc':
        return const Color(0xFF4A90D9); // Word-синий
      case 'pdf':
        return const Color(0xFFD9534F);
      case 'pptx':
      case 'ppt':
        return const Color(0xFFE88732);
      default:
        return TroikaPalette.of(context).textMuted;
    }
  }

  static String _fmtSize(int bytes) {
    if (bytes < 1024) return '$bytes Б';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(0)} КБ';
    return '${(bytes / 1024 / 1024).toStringAsFixed(1)} МБ';
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
