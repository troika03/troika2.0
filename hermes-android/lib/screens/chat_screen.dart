import '../widgets/troika_page.dart';
import 'dart:convert';
import '../widgets/web_sources_view.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';
import 'package:file_picker/file_picker.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:provider/provider.dart';
import '../config/troika_config.dart';
import '../services/assistant_service.dart';
import '../services/troika_api_service.dart';
import '../services/thought_translator.dart';
import '../theme/troika_theme.dart';

/// Полноценный чат-экран: общая лента голоса и текста, прокрутка,
/// картинки в пузырях, кликабельные ссылки, отправка фото/файлов.
class ChatScreen extends StatefulWidget {
  final VoidCallback? onOpenCommands;
  final VoidCallback? onOpenDocuments;

  const ChatScreen({super.key, this.onOpenCommands, this.onOpenDocuments});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final TextEditingController _input = TextEditingController();
  final ScrollController _scroll = ScrollController();
  final ImagePicker _picker = ImagePicker();
  RunApprovalRequest? _shownApproval;

  // Прикреплённые, но ещё не отправленные картинки (data-url).
  final List<String> _pendingImages = [];
  int _lastCount = 0;

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _scrollToBottom({bool animated = true}) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      final target = _scroll.position.maxScrollExtent;
      if (animated) {
        _scroll.animateTo(
          target,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      } else {
        _scroll.jumpTo(target);
      }
    });
  }

  Future<void> _send(AssistantService a) async {
    final text = _input.text.trim();
    if (text.isEmpty && _pendingImages.isEmpty) return;
    final images = List<String>.of(_pendingImages);
    _input.clear();
    setState(() => _pendingImages.clear());
    await a.sendTextQuery(text, imageDataUrls: images);
    _scrollToBottom();
  }

  Future<void> _pickImage(ImageSource source) async {
    try {
      final XFile? file = await _picker.pickImage(
        source: source,
        maxWidth: 1600,
        imageQuality: 80,
      );
      if (file == null) return;
      final bytes = await file.readAsBytes();
      final mime = _mimeFromPath(file.path);
      final dataUrl = 'data:$mime;base64,${base64Encode(bytes)}';
      setState(() => _pendingImages.add(dataUrl));
    } catch (e) {
      _toast('Не получилось взять фото: $e');
    }
  }

  Future<void> _pickFile() async {
    try {
      final result = await FilePicker.platform.pickFiles(withData: true);
      if (result == null || result.files.isEmpty) return;
      final f = result.files.first;
      // Картинки — отправляем как vision. Прочие файлы сервер как вложение
      // не принимает (только text/image) — шлём имя файла текстом.
      final ext = (f.extension ?? '').toLowerCase();
      if (['jpg', 'jpeg', 'png', 'webp', 'gif'].contains(ext) &&
          f.bytes != null) {
        final mime = 'image/${ext == 'jpg' ? 'jpeg' : ext}';
        final dataUrl = 'data:$mime;base64,${base64Encode(f.bytes!)}';
        setState(() => _pendingImages.add(dataUrl));
      } else {
        _toast('Файл «${f.name}» — Тройка пока понимает только фото/картинки.');
      }
    } catch (e) {
      _toast('Не получилось взять файл: $e');
    }
  }

  static String _mimeFromPath(String path) {
    final p = path.toLowerCase();
    if (p.endsWith('.png')) return 'image/png';
    if (p.endsWith('.webp')) return 'image/webp';
    if (p.endsWith('.gif')) return 'image/gif';
    return 'image/jpeg';
  }

  void _attachSheet() {
    showModalBottomSheet(
      context: context,
      backgroundColor: TroikaPalette.of(context).surface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
      ),
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            _sheetItem(Icons.photo_library_outlined, 'Галерея', () {
              Navigator.pop(context);
              _pickImage(ImageSource.gallery);
            }),
            _sheetItem(Icons.photo_camera_outlined, 'Камера', () {
              Navigator.pop(context);
              _pickImage(ImageSource.camera);
            }),
            _sheetItem(Icons.attach_file, 'Файл', () {
              Navigator.pop(context);
              _pickFile();
            }),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }

  Widget _sheetItem(IconData icon, String label, VoidCallback onTap) {
    return ListTile(
      leading: Icon(icon, color: Theme.of(context).colorScheme.primary),
      title: Text(
        label,
        style: TextStyle(color: TroikaPalette.of(context).text),
      ),
      onTap: onTap,
    );
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<void> _showApprovalDialog(
    AssistantService assistant,
    RunApprovalRequest request,
  ) async {
    if (!mounted) {
      assistant.resolvePendingApproval('deny');
      return;
    }
    final allowOnce = request.choices.contains('once');
    final choice = await showDialog<String>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: TroikaPalette.of(context).surface,
        title: Text(
          'Подтвердить действие?',
          style: TextStyle(color: TroikaPalette.of(context).text),
        ),
        content: Text(
          request.description,
          style: TextStyle(color: TroikaPalette.of(context).textMuted),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, 'deny'),
            child: const Text('Отмена'),
          ),
          if (allowOnce)
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, 'once'),
              child: const Text('Разрешить один раз'),
            ),
        ],
      ),
    );
    assistant.resolvePendingApproval(choice ?? 'deny');
  }

  @override
  Widget build(BuildContext context) {
    final a = context.watch<AssistantService>();
    final messages = a.messages;
    final approval = a.pendingApproval;
    if (approval == null) {
      _shownApproval = null;
    } else if (!identical(_shownApproval, approval)) {
      _shownApproval = approval;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _showApprovalDialog(a, approval);
      });
    }
    if (messages.length != _lastCount) {
      _lastCount = messages.length;
      _scrollToBottom();
    }
    final isBusy =
        a.state == AssistantState.processing ||
        a.state == AssistantState.recording ||
        a.state == AssistantState.speaking;

    return Column(
      children: [
        Expanded(
          child: messages.isEmpty
              ? _emptyState(a)
              : ListView.builder(
                  controller: _scroll,
                  padding: const EdgeInsets.fromLTRB(12, 12, 12, 8),
                  itemCount: messages.length,
                  itemBuilder: (_, i) => _MessageBubble(message: messages[i]),
                ),
        ),
        if (a.state == AssistantState.error && a.errorMessage.isNotEmpty)
          _errorBar(a.errorMessage),
        _attachments(),
        _inputBar(a, isBusy),
      ],
    );
  }

  Widget _emptyState(AssistantService a) {
    final hour = DateTime.now().hour;
    final greeting = hour < 6
        ? 'Доброй ночи'
        : hour < 12
        ? 'Доброе утро'
        : hour < 18
        ? 'Добрый день'
        : 'Добрый вечер';
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(22, 34, 22, 20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                greeting,
                style: const TextStyle(
                  fontSize: 34,
                  height: 1.05,
                  fontWeight: FontWeight.w600,
                  letterSpacing: -0.8,
                ),
              ),
              const SizedBox(height: 9),
              Text(
                'Локальные команды готовы. Интернет не нужен.',
                style: TextStyle(
                  color: TroikaPalette.of(context).textMuted,
                  fontSize: 15,
                ),
              ),
              const SizedBox(height: 26),
              Wrap(
                spacing: 10,
                runSpacing: 10,
                children: [
                  _QuickCard(
                    icon: Icons.grid_view_outlined,
                    title: 'Команды',
                    subtitle: 'Телефон и компьютер',
                    onTap: widget.onOpenCommands,
                  ),
                  _QuickCard(
                    icon: Icons.description_outlined,
                    title: 'Документ',
                    subtitle: 'Создать DOCX локально',
                    onTap: widget.onOpenDocuments,
                  ),
                  _QuickCard(
                    icon: Icons.slideshow_outlined,
                    title: 'Презентация',
                    subtitle: 'Создать PPTX локально',
                    onTap: widget.onOpenDocuments,
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _errorBar(String msg) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: TroikaColors.error.withOpacity(0.12),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: TroikaColors.error.withOpacity(0.3)),
      ),
      child: Text(
        msg,
        style: const TextStyle(color: TroikaColors.error, fontSize: 13),
      ),
    );
  }

  Widget _attachments() {
    if (_pendingImages.isEmpty) return const SizedBox.shrink();
    return Container(
      height: 76,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      alignment: Alignment.centerLeft,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: _pendingImages.length,
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemBuilder: (_, i) {
          final bytes = _decodeDataUrl(_pendingImages[i]);
          return Stack(
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: bytes != null
                    ? Image.memory(
                        bytes,
                        width: 64,
                        height: 64,
                        fit: BoxFit.cover,
                      )
                    : Container(
                        width: 64,
                        height: 64,
                        color: TroikaPalette.of(context).surfaceHi,
                      ),
              ),
              Positioned(
                top: -6,
                right: -6,
                child: IconButton(
                  icon: Icon(
                    Icons.cancel,
                    size: 18,
                    color: TroikaPalette.of(context).textMuted,
                  ),
                  onPressed: () => setState(() => _pendingImages.removeAt(i)),
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _inputBar(AssistantService a, bool isBusy) {
    final p = TroikaPalette.of(context);
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
        child: Container(
          decoration: BoxDecoration(
            color: p.surface,
            borderRadius: BorderRadius.circular(26),
            border: Border.all(color: p.line),
          ),
          padding: const EdgeInsets.fromLTRB(8, 4, 8, 8),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: _input,
                style: TextStyle(color: p.text, fontSize: 16),
                minLines: 1,
                maxLines: 5,
                textInputAction: TextInputAction.newline,
                decoration: InputDecoration(
                  hintText: 'Сообщение…',
                  hintStyle: TextStyle(color: p.textMuted),
                  filled: false,
                  border: InputBorder.none,
                  enabledBorder: InputBorder.none,
                  focusedBorder: InputBorder.none,
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 12,
                  ),
                ),
              ),
              Row(
                children: [
                  IconButton(
                    tooltip: 'Прикрепить',
                    icon: const Icon(Icons.add_rounded, size: 22),
                    color: p.textMuted,
                    onPressed: _attachSheet,
                  ),
                  const Spacer(),
                  IconButton(
                    tooltip: isBusy ? 'Остановить' : 'Говорить',
                    icon: Icon(
                      isBusy ? Icons.stop_rounded : Icons.mic_none_rounded,
                    ),
                    color: p.text,
                    onPressed: () {
                      if (a.state == AssistantState.recording) {
                        a.stopRecordingAndProcess();
                      } else if (isBusy) {
                        a.interrupt();
                      } else {
                        a.startManualRecording();
                      }
                    },
                  ),
                  ValueListenableBuilder<TextEditingValue>(
                    valueListenable: _input,
                    builder: (context, value, _) => _SendButton(
                      onTap:
                          isBusy ||
                              a.pendingApproval != null ||
                              (value.text.trim().isEmpty &&
                                  _pendingImages.isEmpty)
                          ? null
                          : () => _send(a),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

Uint8List? _decodeDataUrl(String dataUrl) {
  final idx = dataUrl.indexOf(',');
  if (idx < 0) return null;
  try {
    return base64Decode(dataUrl.substring(idx + 1));
  } catch (_) {
    return null;
  }
}

class _QuickCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback? onTap;

  const _QuickCard({
    required this.icon,
    required this.title,
    required this.subtitle,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 210,
      child: Material(
        color: TroikaPalette.of(context).surface,
        borderRadius: BorderRadius.circular(14),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(14),
          child: Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: TroikaPalette.of(context).line),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  icon,
                  color: Theme.of(context).colorScheme.primary,
                  size: 22,
                ),
                const SizedBox(height: 16),
                Text(
                  title,
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 3),
                Text(
                  subtitle,
                  style: TextStyle(
                    color: TroikaPalette.of(context).textMuted,
                    fontSize: 12,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _SendButton extends StatelessWidget {
  final VoidCallback? onTap;
  const _SendButton({required this.onTap});

  @override
  Widget build(BuildContext context) => IconButton.filled(
    tooltip: 'Отправить',
    onPressed: onTap,
    style: IconButton.styleFrom(minimumSize: const Size(48, 48)),
    icon: const Icon(Icons.arrow_upward_rounded, size: 22),
  );
}

class _MessageBubble extends StatelessWidget {
  final ChatMessage message;
  const _MessageBubble({required this.message});

  @override
  Widget build(BuildContext context) {
    final isUser = message.isUser;
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.78,
        ),
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          color: isUser
              ? Theme.of(context).colorScheme.primary.withOpacity(0.14)
              : TroikaPalette.of(context).surface,
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(16),
            topRight: const Radius.circular(16),
            bottomLeft: Radius.circular(isUser ? 16 : 4),
            bottomRight: Radius.circular(isUser ? 4 : 16),
          ),
          border: Border.all(
            color: isUser
                ? Theme.of(context).colorScheme.primary.withOpacity(0.28)
                : TroikaPalette.of(context).line,
          ),
        ),
        child: Column(
          crossAxisAlignment: isUser
              ? CrossAxisAlignment.end
              : CrossAxisAlignment.start,
          children: [
            // Картинки
            for (final url in message.imageDataUrls) _imageThumb(url),
            if (message.hasImages && message.text.trim().isNotEmpty)
              const SizedBox(height: 6),
            // Internal diagnostics exist only in explicit developer builds.
            if (TroikaConfig.developerDiagnosticsEnabled &&
                !isUser &&
                message.hasThoughts)
              _ThoughtsView(thoughts: message.thoughts, live: message.pending),
            // Текст / индикатор «печатает»
            if (message.pending &&
                (!TroikaConfig.developerDiagnosticsEnabled ||
                    !message.hasThoughts))
              const _TypingDots()
            else if (message.text.trim().isNotEmpty)
              _LinkifiedText(
                text: message.text,
                color: isUser
                    ? TroikaPalette.of(context).text.withOpacity(0.92)
                    : TroikaPalette.of(context).text,
              ),
            if (!isUser) WebSourcesView(trace: message.webSources),
            if (message.fromVoice)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Icon(
                  Icons.graphic_eq,
                  size: 12,
                  color: TroikaPalette.of(context).textFaint,
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _imageThumb(String dataUrl) {
    final bytes = _decodeDataUrl(dataUrl);
    if (bytes == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(10),
        child: Image.memory(bytes, fit: BoxFit.cover),
      ),
    );
  }
}

class _TypingDots extends StatefulWidget {
  const _TypingDots();
  @override
  State<_TypingDots> createState() => _TypingDotsState();
}

class _TypingDotsState extends State<_TypingDots>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 900),
  )..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _c,
      builder: (_, __) {
        final t = _c.value;
        return Row(
          mainAxisSize: MainAxisSize.min,
          children: List.generate(3, (i) {
            final phase = (t + i * 0.2) % 1.0;
            final op = 0.3 + 0.7 * (1 - (phase - 0.5).abs() * 2).clamp(0, 1);
            return Padding(
              padding: const EdgeInsets.symmetric(horizontal: 2),
              child: Opacity(
                opacity: op.toDouble(),
                child: CircleAvatar(
                  radius: 3,
                  backgroundColor: TroikaPalette.of(context).textMuted,
                ),
              ),
            );
          }),
        );
      },
    );
  }
}

/// Текст с кликабельными ссылками. URL открываются во внешнем браузере;
/// если не удалось — копируются в буфер.
class _LinkifiedText extends StatefulWidget {
  final String text;
  final Color color;
  const _LinkifiedText({required this.text, required this.color});

  @override
  State<_LinkifiedText> createState() => _LinkifiedTextState();
}

class _LinkifiedTextState extends State<_LinkifiedText> {
  static final RegExp _urlRe = RegExp(
    r'((https?:\/\/|www\.)[^\s<>()]+)',
    caseSensitive: false,
  );

  final List<TapGestureRecognizer> _recognizers = [];

  @override
  void dispose() {
    for (final r in _recognizers) {
      r.dispose();
    }
    super.dispose();
  }

  Future<void> _open(String url) async {
    final uri = Uri.tryParse(url);
    if (uri == null) return;
    try {
      final ok = await launchUrl(uri, mode: LaunchMode.externalApplication);
      if (ok) return;
    } catch (_) {}
    await Clipboard.setData(ClipboardData(text: url));
    if (mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('Ссылка скопирована')));
    }
  }

  @override
  Widget build(BuildContext context) {
    // пересоздаём recognizer'ы под текущий текст
    for (final r in _recognizers) {
      r.dispose();
    }
    _recognizers.clear();

    final text = widget.text;
    final spans = <TextSpan>[];
    int last = 0;
    for (final m in _urlRe.allMatches(text)) {
      if (m.start > last) {
        spans.add(TextSpan(text: text.substring(last, m.start)));
      }
      final raw = m.group(0)!;
      final url = raw.startsWith('http') ? raw : 'https://$raw';
      final rec = TapGestureRecognizer()..onTap = () => _open(url);
      _recognizers.add(rec);
      spans.add(
        TextSpan(
          text: raw,
          style: TextStyle(
            color: Theme.of(context).colorScheme.primary,
            decoration: TextDecoration.underline,
          ),
          recognizer: rec,
        ),
      );
      last = m.end;
    }
    if (last < text.length) {
      spans.add(TextSpan(text: text.substring(last)));
    }
    return SelectableText.rich(
      TextSpan(
        style: TextStyle(color: widget.color, fontSize: 15, height: 1.4),
        children: spans,
      ),
    );
  }
}

/// Лента «как думает Тройка»: размышления и вызовы инструментов.
/// Пока ответ генерится (live) — раскрыта и пульсирует заголовок.
/// Когда ответ готов — сворачивается в компактную строку, тап разворачивает.
class _ThoughtsView extends StatefulWidget {
  final List<ThoughtStep> thoughts;
  final bool live;
  const _ThoughtsView({required this.thoughts, required this.live});

  @override
  State<_ThoughtsView> createState() => _ThoughtsViewState();
}

class _ThoughtsViewState extends State<_ThoughtsView> {
  bool _expanded = true;

  @override
  void didUpdateWidget(covariant _ThoughtsView old) {
    super.didUpdateWidget(old);
    // Когда генерация закончилась — автоматически свернуть.
    if (old.live && !widget.live) {
      _expanded = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final count = widget.thoughts.length;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: TroikaPalette.of(context).surface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: TroikaPalette.of(context).line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            onTap: () => setState(() => _expanded = !_expanded),
            borderRadius: BorderRadius.circular(10),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
              child: Row(
                children: [
                  Text(
                    widget.live ? '💭' : '🧠',
                    style: const TextStyle(fontSize: 13),
                  ),
                  const SizedBox(width: 6),
                  Text(
                    widget.live ? 'Размышляет…' : 'Ход мыслей ($count)',
                    style: TextStyle(
                      color: TroikaPalette.of(context).textMuted,
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const Spacer(),
                  Icon(
                    _expanded ? Icons.expand_less : Icons.expand_more,
                    size: 16,
                    color: TroikaPalette.of(context).textFaint,
                  ),
                ],
              ),
            ),
          ),
          if (_expanded)
            Padding(
              padding: const EdgeInsets.fromLTRB(10, 0, 10, 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [for (final s in widget.thoughts) _stepRow(s)],
              ),
            ),
        ],
      ),
    );
  }

  Widget _stepRow(ThoughtStep s) {
    String icon;
    Color color;
    String text = s.text;
    switch (s.kind) {
      case ThoughtKind.thinking:
        icon = '·';
        color = TroikaPalette.of(context).text.withOpacity(0.75);
        break;
      case ThoughtKind.toolStart:
        icon = '🔧';
        color = Theme.of(context).colorScheme.primary;
        text = 'вызываю $text';
        break;
      case ThoughtKind.toolDone:
        icon = s.isError ? '⚠️' : '✅';
        color = s.isError
            ? TroikaColors.error
            : TroikaPalette.of(context).textMuted;
        text = s.isError ? '$text — ошибка' : '$text — готово';
        break;
    }
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 18,
            child: Text(icon, style: TextStyle(fontSize: 12, color: color)),
          ),
          const SizedBox(width: 2),
          Expanded(
            child: s.kind == ThoughtKind.thinking
                ? _TranslatedText(
                    text: text,
                    style: TextStyle(
                      color: color,
                      fontSize: 12.5,
                      height: 1.35,
                    ),
                  )
                : Text(
                    text,
                    style: TextStyle(
                      color: color,
                      fontSize: 12.5,
                      height: 1.35,
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}

/// Текст мысли с ленивым офлайн-переводом EN→RU (ML Kit).
/// Сначала показывает оригинал, затем подменяет переводом, когда готов.
/// Если перевод недоступен — остаётся оригинал.
class _TranslatedText extends StatefulWidget {
  final String text;
  final TextStyle style;
  const _TranslatedText({required this.text, required this.style});

  @override
  State<_TranslatedText> createState() => _TranslatedTextState();
}

class _TranslatedTextState extends State<_TranslatedText> {
  late String _shown = widget.text;

  @override
  void initState() {
    super.initState();
    _translate();
  }

  @override
  void didUpdateWidget(covariant _TranslatedText old) {
    super.didUpdateWidget(old);
    if (old.text != widget.text) {
      _shown = widget.text;
      _translate();
    }
  }

  Future<void> _translate() async {
    final src = widget.text;
    final ru = await ThoughtTranslator.instance.translate(src);
    if (mounted && ru != _shown) {
      setState(() => _shown = ru);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Text(_shown, style: widget.style);
  }
}
