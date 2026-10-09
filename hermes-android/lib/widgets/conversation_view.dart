import 'package:flutter/material.dart';
import '../theme/troika_theme.dart';

/// Показывает последний диалог: что сказал пользователь и что ответила Тройка.
class ConversationView extends StatelessWidget {
  final String userText;
  final String troikaText;
  final String? errorText;

  const ConversationView({
    super.key,
    required this.userText,
    required this.troikaText,
    this.errorText,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          if (errorText != null) ...[
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: TroikaColors.error.withOpacity(0.1),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: TroikaColors.error.withOpacity(0.3)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.error_outline,
                      color: TroikaColors.error, size: 16),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      errorText!,
                      style: const TextStyle(
                          color: TroikaColors.error, fontSize: 13),
                    ),
                  ),
                ],
              ),
            ),
          ] else ...[
            // Последний запрос пользователя
            if (userText.isNotEmpty)
              _bubble(
                context: context,
                text: userText,
                isUser: true,
              ),
            const SizedBox(height: 8),
            // Ответ Тройки.
            if (troikaText.isNotEmpty)
              _bubble(
                context: context,
                text: troikaText,
                isUser: false,
              ),
          ],
        ],
      ),
    );
  }

  Widget _bubble({
    required BuildContext context,
    required String text,
    required bool isUser,
  }) {
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 300),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          color: isUser
              ? Theme.of(context).colorScheme.primary.withOpacity(0.13)
              : Theme.of(context).colorScheme.surface,
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(16),
            topRight: const Radius.circular(16),
            bottomLeft: Radius.circular(isUser ? 16 : 4),
            bottomRight: Radius.circular(isUser ? 4 : 16),
          ),
          border: Border.all(
            color: isUser
                ? Theme.of(context).colorScheme.primary.withOpacity(0.28)
                : Theme.of(context).dividerColor,
          ),
        ),
        child: Text(
          text,
          style: TextStyle(
            color: isUser
                ? Theme.of(context).colorScheme.onSurface.withOpacity(0.85)
                : Theme.of(context).colorScheme.onSurface,
            fontSize: 14,
            height: 1.4,
          ),
          maxLines: 4,
          overflow: TextOverflow.ellipsis,
        ),
      ),
    );
  }
}
