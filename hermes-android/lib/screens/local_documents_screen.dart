import '../widgets/troika_page.dart';
import 'dart:io' show Platform;

import 'package:flutter/material.dart';

import '../services/local_document_service.dart';
import '../services/windows_shell_service.dart';

class LocalDocumentsScreen extends StatefulWidget {
  final bool initialPresentation;
  final String initialPrompt;

  const LocalDocumentsScreen({
    super.key,
    this.initialPresentation = false,
    this.initialPrompt = '',
  });

  @override
  State<LocalDocumentsScreen> createState() => _LocalDocumentsScreenState();
}

class _LocalDocumentsScreenState extends State<LocalDocumentsScreen> {
  late final TextEditingController _title;
  late final TextEditingController _content;
  final _documents = LocalDocumentService();
  late bool _presentation;
  bool _saving = false;
  String? _savedPath;

  @override
  void initState() {
    super.initState();
    _presentation = widget.initialPresentation;
    final topic = _extractTopic(widget.initialPrompt, _presentation);
    _title = TextEditingController(text: topic.$1);
    _content = TextEditingController(text: topic.$2);
  }

  static (String, String) _extractTopic(String prompt, bool presentation) {
    var topic = prompt
        .toLowerCase()
        .replaceAll(RegExp(r'(пожалуйста|прошу)'), '')
        .replaceAll(RegExp(r'(создай|сделай|создать)'), '')
        .replaceAll(RegExp(r'(мне|презентацию|презентация|документ)'), '')
        .replaceAll(RegExp(r'\s+'), ' ')
        .trim();
    if (topic.startsWith('на тему ')) topic = topic.substring(8).trim();
    if (topic == 'на любую тему' || topic == 'любую тему') {
      topic = 'Как технологии упрощают повседневную жизнь';
    }
    if (topic.isEmpty) {
      return (
        presentation ? 'Новая презентация' : 'Новый документ',
        presentation
            ? 'Введение\n- Главная идея\n- Почему тема важна\n\n---\n\nОсновная часть\n- Первый тезис\n- Второй тезис\n\n---\n\nИтоги\n- Основной вывод'
            : '',
      );
    }
    final title = '${topic[0].toUpperCase()}${topic.substring(1)}';
    return (
      title,
      presentation
          ? '$title\n- Цель презентации\n- Ключевой вопрос\n\n---\n\nОсновная часть\n- Первый тезис\n- Второй тезис\n\n---\n\nИтоги\n- Основной вывод'
          : '',
    );
  }

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
      setState(() => _savedPath = _documents.lastSavedPath);
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
    return TroikaPage(
      appBar: AppBar(
        title: const Text('Документы'),
        backgroundColor: TroikaPalette.of(context).bg,
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
                TroikaIntro(
                    icon: _presentation
                        ? Icons.slideshow_outlined
                        : Icons.description_outlined,
                    title: _presentation
                        ? 'Собери свою историю'
                        : 'Мысли в документ',
                    subtitle:
                        'Добавь свой текст. Готовый файл сохранится на устройстве — интернет не нужен.'),
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
                  decoration: InputDecoration(
                    labelText: 'Название',
                    filled: true,
                    fillColor: TroikaPalette.of(context).surface,
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _content,
                  enabled: !_saving,
                  minLines: 5,
                  maxLines: 18,
                  decoration: InputDecoration(
                    labelText: _presentation ? 'Слайды' : 'Текст',
                    hintText: _presentation
                        ? 'Название слайда\n- первый пункт\n- второй пункт\n\n---\n\nСледующий слайд'
                        : 'Напиши текст документа',
                    alignLabelWithHint: true,
                    filled: true,
                    fillColor: TroikaPalette.of(context).surface,
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
                if (Platform.isWindows && _savedPath != null) ...[
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: () =>
                              WindowsShellService.openPath(_savedPath!),
                          icon: const Icon(Icons.open_in_new_rounded),
                          label: const Text('Открыть'),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: () =>
                              WindowsShellService.showInFolder(_savedPath!),
                          icon: const Icon(Icons.folder_open_outlined),
                          label: const Text('Показать в папке'),
                        ),
                      ),
                    ],
                  ),
                ],
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
