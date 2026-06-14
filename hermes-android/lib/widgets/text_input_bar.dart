import 'package:flutter/material.dart';
import '../theme/troika_theme.dart';

/// Текстовое поле для ввода запроса (когда не хочется говорить голосом)
class TextInputBar extends StatefulWidget {
  final Future<void> Function(String text) onSubmit;

  const TextInputBar({super.key, required this.onSubmit});

  @override
  State<TextInputBar> createState() => _TextInputBarState();
}

class _TextInputBarState extends State<TextInputBar> {
  final _controller = TextEditingController();
  bool _loading = false;

  Future<void> _submit() async {
    final text = _controller.text.trim();
    if (text.isEmpty || _loading) return;

    setState(() => _loading = true);
    _controller.clear();

    try {
      await widget.onSubmit(text);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Container(
        decoration: BoxDecoration(
          color: TroikaColors.surface,
          borderRadius: BorderRadius.circular(28),
          border: Border.all(color: Colors.white10),
        ),
        child: Row(
          children: [
            Expanded(
              child: TextField(
                controller: _controller,
                style: const TextStyle(color: TroikaColors.text, fontSize: 14),
                decoration: const InputDecoration(
                  hintText: 'Написать…',
                  hintStyle: TextStyle(color: TroikaColors.textFaint),
                  border: InputBorder.none,
                  contentPadding: EdgeInsets.symmetric(horizontal: 20, vertical: 14),
                ),
                onSubmitted: (_) => _submit(),
              ),
            ),
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: _loading
                  ? const SizedBox(
                      width: 24,
                      height: 24,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: TroikaColors.brand,
                      ),
                    )
                  : IconButton(
                      icon: const Icon(Icons.send_rounded),
                      color: TroikaColors.brand,
                      onPressed: _submit,
                    ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }
}
