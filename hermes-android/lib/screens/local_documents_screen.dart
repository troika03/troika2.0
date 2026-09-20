import 'package:flutter/material.dart';

import '../services/local_document_service.dart';
import '../theme/troika_theme.dart';

class LocalDocumentsScreen extends StatefulWidget {
  const LocalDocumentsScreen({super.key});

  @override
  State<LocalDocumentsScreen> createState() => _LocalDocumentsScreenState();
}

class _LocalDocumentsScreenState extends State<LocalDocumentsScreen> {
  final _title = TextEditingController();
  final _content = TextEditingController();
  final _documents = LocalDocumentService();
  bool _presentation = false;
  bool _saving = false;

  Future<void> _create() async {
    if (_title.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Напиши название файла')),
      );
      return;
    }
    setState(() => _saving = true);
    try {
      final saved = _presentation
          ? await _documents.createPresentation(
              title: _title.text,
              content: _content.text,
            )
          : await _documents.createDocument(
              title: _title.text,
              content: _content.text,
            );
      if (!mounted || !saved) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
              _presentation ? 'Презентация сохранена' : 'Документ сохранён'),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Не удалось создать файл: $error')),
      );
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Документы'),
        backgroundColor: TroikaColors.bg,
        surfaceTintColor: Colors.transparent,
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Создать локально',
                  style: TextStyle(fontSize: 28, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Без модели и сервера. Файл создаётся на устройстве.',
                  style: TextStyle(color: TroikaColors.textMuted),
                ),
                const SizedBox(height: 24),
                SegmentedButton<bool>(
                  segments: const [
                    ButtonSegment(
                      value: false,
                      icon: Icon(Icons.description_outlined),
                      label: Text('DOCX'),
                    ),
                    ButtonSegment(
                      value: true,
                      icon: Icon(Icons.slideshow_outlined),
                      label: Text('PPTX'),
                    ),
                  ],
                  selected: {_presentation},
                  onSelectionChanged: _saving
                      ? null
                      : (value) => setState(() => _presentation = value.first),
                ),
                const SizedBox(height: 20),
                TextField(
                  controller: _title,
                  enabled: !_saving,
                  decoration: const InputDecoration(
                    labelText: 'Название',
                    filled: true,
                    fillColor: TroikaColors.surface,
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _content,
                  enabled: !_saving,
                  minLines: 8,
                  maxLines: 18,
                  decoration: InputDecoration(
                    labelText: _presentation ? 'Слайды' : 'Текст',
                    hintText: _presentation
                        ? 'Название слайда\n- первый пункт\n- второй пункт\n\n---\n\nСледующий слайд'
                        : 'Напиши текст документа',
                    alignLabelWithHint: true,
                    filled: true,
                    fillColor: TroikaColors.surface,
                    border: const OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 20),
                FilledButton.icon(
                  onPressed: _saving ? null : _create,
                  icon: _saving
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.save_outlined),
                  label: Text(_saving ? 'Создаю…' : 'Создать файл'),
                  style: FilledButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    _title.dispose();
    _content.dispose();
    super.dispose();
  }
}
