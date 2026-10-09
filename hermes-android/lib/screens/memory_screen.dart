import '../widgets/troika_page.dart';
import 'package:flutter/material.dart';
import '../services/troika_api_service.dart';
import '../theme/troika_theme.dart';

class MemoryScreen extends StatefulWidget {
  const MemoryScreen({super.key});

  @override
  State<MemoryScreen> createState() => _MemoryScreenState();
}

class _MemoryScreenState extends State<MemoryScreen> {
  final TroikaApiService _api = TroikaApiService();
  List<TroikaMemory> _memories = const [];
  bool _loading = true;
  bool _busy = false;
  String? _error;

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
      final memories = await _api.listMemories();
      if (!mounted) return;
      setState(() {
        _memories = memories;
        _loading = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = error.toString();
      });
    }
  }

  Future<void> _edit([TroikaMemory? memory]) async {
    final draft = await _memorySheet(memory);
    if (draft == null || _busy) return;
    setState(() => _busy = true);
    try {
      if (memory == null) {
        await _api.createMemory(
            kind: draft.kind, title: draft.title, content: draft.content);
      } else {
        await _api.updateMemory(memory.id,
            kind: draft.kind, title: draft.title, content: draft.content);
      }
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(memory == null
              ? 'Тройка запомнила эту запись.'
              : 'Память обновлена.')));
      await _load();
    } catch (error) {
      _showError(error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<_MemoryDraft?> _memorySheet(TroikaMemory? memory) async {
    final title = TextEditingController(text: memory?.title ?? '');
    final content = TextEditingController(text: memory?.content ?? '');
    var kind = memory?.kind ?? 'fact';
    String? validation;
    final result = await showModalBottomSheet<_MemoryDraft>(
        context: context,
        isScrollControlled: true,
        backgroundColor: TroikaPalette.of(context).surface,
        shape: const RoundedRectangleBorder(
            borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
        builder: (sheetContext) => StatefulBuilder(
            builder: (sheetContext, setSheetState) => SafeArea(
                top: false,
                child: Padding(
                    padding: EdgeInsets.fromLTRB(24, 16, 24,
                        MediaQuery.viewInsetsOf(sheetContext).bottom + 24),
                    child: SingleChildScrollView(
                        child: Column(
                            mainAxisSize: MainAxisSize.min,
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                          Center(
                              child: Container(
                                  width: 40,
                                  height: 4,
                                  decoration: BoxDecoration(
                                      color:
                                          TroikaPalette.of(context).textFaint,
                                      borderRadius: BorderRadius.circular(2)))),
                          const SizedBox(height: 24),
                          Text(
                              memory == null
                                  ? 'Что запомнить'
                                  : 'Исправить запись',
                              style: TextStyle(
                                  color: TroikaPalette.of(context).text,
                                  fontSize: 22,
                                  fontWeight: FontWeight.w600)),
                          const SizedBox(height: 8),
                          Text(
                              'Эта информация будет учитываться в будущих ответах. Не сохраняй пароли и платёжные данные.',
                              style: TextStyle(
                                  color: TroikaPalette.of(context).textMuted)),
                          const SizedBox(height: 24),
                          Wrap(spacing: 8, runSpacing: 8, children: [
                            for (final option in const [
                              ('fact', 'Факт', Icons.person_outline),
                              ('preference', 'Предпочтение', Icons.tune),
                              (
                                'instruction',
                                'Правило',
                                Icons.chat_bubble_outline
                              ),
                            ])
                              ChoiceChip(
                                  avatar: Icon(option.$3,
                                      size: 18,
                                      color: kind == option.$1
                                          ? Theme.of(context)
                                              .colorScheme
                                              .primary
                                          : TroikaPalette.of(context)
                                              .textMuted),
                                  label: Text(option.$2),
                                  selected: kind == option.$1,
                                  onSelected: (_) =>
                                      setSheetState(() => kind = option.$1))
                          ]),
                          const SizedBox(height: 24),
                          TextField(
                              controller: title,
                              maxLength: 80,
                              textInputAction: TextInputAction.next,
                              style: TextStyle(
                                  color: TroikaPalette.of(context).text),
                              decoration: const InputDecoration(
                                  labelText: 'Короткий заголовок',
                                  hintText: 'Например: Формат ответов')),
                          const SizedBox(height: 8),
                          TextField(
                              controller: content,
                              minLines: 3,
                              maxLines: 6,
                              maxLength: 1200,
                              style: TextStyle(
                                  color: TroikaPalette.of(context).text),
                              decoration: const InputDecoration(
                                  labelText: 'Что учитывать',
                                  hintText:
                                      'Например: Предпочитаю короткие ответы на русском языке')),
                          if (validation != null) ...[
                            const SizedBox(height: 8),
                            Text(validation!,
                                style:
                                    const TextStyle(color: TroikaColors.error)),
                          ],
                          const SizedBox(height: 16),
                          SizedBox(
                              width: double.infinity,
                              height: 48,
                              child: FilledButton.icon(
                                  onPressed: () {
                                    final cleanTitle = title.text.trim();
                                    final cleanContent = content.text.trim();
                                    if (cleanTitle.isEmpty ||
                                        cleanContent.isEmpty) {
                                      setSheetState(() => validation =
                                          'Заполни заголовок и текст записи.');
                                      return;
                                    }
                                    Navigator.pop(
                                        sheetContext,
                                        _MemoryDraft(
                                            kind, cleanTitle, cleanContent));
                                  },
                                  icon: const Icon(Icons.check),
                                  label: const Text('Сохранить')))
                        ]))))));
    title.dispose();
    content.dispose();
    return result;
  }

  Future<void> _delete(TroikaMemory memory) async {
    final confirmed = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
                backgroundColor: TroikaPalette.of(context).surface,
                title: Text('Удалить из памяти?',
                    style: TextStyle(color: TroikaPalette.of(context).text)),
                content: Text(
                    '«${memory.title}» больше не будет учитываться в ответах.',
                    style:
                        TextStyle(color: TroikaPalette.of(context).textMuted)),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(dialogContext, false),
                      child: const Text('Отмена')),
                  FilledButton(
                      style: FilledButton.styleFrom(
                          backgroundColor: TroikaColors.error),
                      onPressed: () => Navigator.pop(dialogContext, true),
                      child: const Text('Удалить'))
                ]));
    if (confirmed != true || _busy) return;
    setState(() => _busy = true);
    try {
      await _api.deleteMemory(memory.id);
      if (!mounted) return;
      setState(() =>
          _memories = _memories.where((item) => item.id != memory.id).toList());
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Запись удалена из памяти.')));
    } catch (error) {
      _showError(error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _showError(String message) {
    if (mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(message)));
    }
  }

  @override
  Widget build(BuildContext context) => TroikaPage(
      backgroundColor: TroikaPalette.of(context).bg,
      appBar: AppBar(title: const Text('Память'), actions: [
        IconButton(
            tooltip: 'Обновить',
            onPressed: _busy ? null : _load,
            icon: const Icon(Icons.refresh))
      ]),
      floatingActionButton: FloatingActionButton.extended(
          onPressed: _busy ? null : () => _edit(),
          icon: _busy
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2))
              : const Icon(Icons.add),
          label: const Text('Добавить')),
      body: _loading && _memories.isEmpty
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 104),
                  children: [
                    Container(
                        padding: const EdgeInsets.all(20),
                        decoration: BoxDecoration(
                            color: TroikaPalette.of(context).surface,
                            borderRadius: BorderRadius.circular(20),
                            border: Border.all(
                                color: Theme.of(context)
                                    .colorScheme
                                    .primary
                                    .withValues(alpha: 0.12))),
                        child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Icon(Icons.psychology_outlined,
                                  color: Theme.of(context).colorScheme.primary,
                                  size: 28),
                              SizedBox(width: 16),
                              Expanded(
                                  child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                    Text('Ты управляешь памятью',
                                        style: TextStyle(
                                            color:
                                                TroikaPalette.of(context).text,
                                            fontSize: 18,
                                            fontWeight: FontWeight.w600)),
                                    SizedBox(height: 8),
                                    Text(
                                        'Здесь видны факты, предпочтения и правила общения, которые Тройка учитывает в ответах.',
                                        style: TextStyle(
                                            color: TroikaPalette.of(context)
                                                .textMuted))
                                  ]))
                            ])),
                    if (_error != null) ...[
                      const SizedBox(height: 16),
                      _StateCard(
                          icon: Icons.cloud_off,
                          text: _error!,
                          actionLabel: 'Повторить',
                          onAction: _load)
                    ],
                    const SizedBox(height: 24),
                    Row(children: [
                      Text('Сохранённое',
                          style: TextStyle(
                              color: TroikaPalette.of(context).text,
                              fontSize: 18,
                              fontWeight: FontWeight.w600)),
                      const Spacer(),
                      Text('${_memories.length}',
                          style: TextStyle(
                              color: TroikaPalette.of(context).textMuted))
                    ]),
                    const SizedBox(height: 12),
                    if (_memories.isEmpty && _error == null)
                      _StateCard(
                          icon: Icons.auto_awesome_outlined,
                          text:
                              'Память пока пуста. Добавь то, что поможет Тройке отвечать точнее.',
                          actionLabel: 'Добавить запись',
                          onAction: () => _edit()),
                    for (final memory in _memories)
                      _MemoryCard(
                          memory: memory,
                          onEdit: () => _edit(memory),
                          onDelete: () => _delete(memory))
                  ])));
}

class _MemoryDraft {
  final String kind, title, content;
  const _MemoryDraft(this.kind, this.title, this.content);
}

class _StateCard extends StatelessWidget {
  final IconData icon;
  final String text, actionLabel;
  final VoidCallback onAction;
  const _StateCard(
      {required this.icon,
      required this.text,
      required this.actionLabel,
      required this.onAction});

  @override
  Widget build(BuildContext context) => Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
          color: TroikaPalette.of(context).surface,
          borderRadius: BorderRadius.circular(16)),
      child: Column(children: [
        Icon(icon, color: Theme.of(context).colorScheme.primary, size: 32),
        const SizedBox(height: 12),
        Text(text,
            textAlign: TextAlign.center,
            style: TextStyle(color: TroikaPalette.of(context).textMuted)),
        const SizedBox(height: 12),
        TextButton(onPressed: onAction, child: Text(actionLabel))
      ]));
}

class _MemoryCard extends StatelessWidget {
  final TroikaMemory memory;
  final VoidCallback onEdit, onDelete;
  const _MemoryCard(
      {required this.memory, required this.onEdit, required this.onDelete});

  (String, IconData) get _kind => switch (memory.kind) {
        'preference' => ('Предпочтение', Icons.tune),
        'instruction' => ('Правило общения', Icons.chat_bubble_outline),
        _ => ('Факт', Icons.person_outline),
      };

  @override
  Widget build(BuildContext context) => Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.fromLTRB(16, 16, 8, 16),
      decoration: BoxDecoration(
          color: TroikaPalette.of(context).surface,
          borderRadius: BorderRadius.circular(16)),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
                color: Theme.of(context)
                    .colorScheme
                    .primary
                    .withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(12)),
            child: Icon(_kind.$2,
                color: Theme.of(context).colorScheme.primary, size: 20)),
        const SizedBox(width: 12),
        Expanded(
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(_kind.$1.toUpperCase(),
              style: TextStyle(
                  color: Theme.of(context).colorScheme.primary,
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  letterSpacing: 0.7)),
          const SizedBox(height: 4),
          Text(memory.title,
              style: TextStyle(
                  color: TroikaPalette.of(context).text,
                  fontSize: 16,
                  fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          Text(memory.content,
              style: TextStyle(
                  color: TroikaPalette.of(context).textMuted, height: 1.35))
        ])),
        PopupMenuButton<String>(
            tooltip: 'Действия',
            icon: Icon(Icons.more_vert,
                color: TroikaPalette.of(context).textMuted),
            onSelected: (value) {
              if (value == 'edit') {
                onEdit();
              } else {
                onDelete();
              }
            },
            itemBuilder: (context) => const [
                  PopupMenuItem(value: 'edit', child: Text('Изменить')),
                  PopupMenuItem(value: 'delete', child: Text('Удалить'))
                ])
      ]));
}
