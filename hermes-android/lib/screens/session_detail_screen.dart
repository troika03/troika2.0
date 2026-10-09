import '../widgets/troika_page.dart';
import 'package:flutter/material.dart';
import '../services/troika_api_service.dart';

/// Полный транскрипт одной сессии — user-сообщения справа, ответы Тройки слева.
class SessionDetailScreen extends StatefulWidget {
  final String sessionId;
  final String headerTitle;
  const SessionDetailScreen({
    super.key,
    required this.sessionId,
    required this.headerTitle,
  });

  @override
  State<SessionDetailScreen> createState() => _SessionDetailScreenState();
}

class _SessionDetailScreenState extends State<SessionDetailScreen> {
  late final TroikaApiService _api;
  Future<List<SessionMessage>>? _future;

  @override
  void initState() {
    super.initState();
    _api = TroikaApiService();
    _future = _api.getSessionMessages(widget.sessionId);
  }

  @override
  Widget build(BuildContext context) {
    final accent = Theme.of(context).colorScheme.primary;
    return TroikaPage(
      backgroundColor: TroikaPalette.of(context).bg,
      appBar: AppBar(
        backgroundColor: TroikaPalette.of(context).bg,
        elevation: 0,
        iconTheme: IconThemeData(color: accent),
        title: Text(
          widget.headerTitle,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
            color: TroikaPalette.of(context).text,
            fontSize: 20,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
      body: FutureBuilder<List<SessionMessage>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return Center(
              child: CircularProgressIndicator(color: accent),
            );
          }
          if (snap.hasError) {
            return SingleChildScrollView(
                child: TroikaEmptyState(
                    icon: Icons.cloud_off_outlined,
                    title: 'Разговор пока недоступен',
                    message: snap.error.toString(),
                    actionLabel: 'Повторить',
                    onAction: () => setState(() =>
                        _future = _api.getSessionMessages(widget.sessionId))));
          }
          final msgs = snap.data ?? const [];
          if (msgs.isEmpty) {
            return Center(
              child: Text(
                'Сообщений нет',
                style: TextStyle(color: TroikaPalette.of(context).textMuted),
              ),
            );
          }
          return ListView.builder(
            padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 12),
            itemCount: msgs.length,
            itemBuilder: (context, i) => _MessageBubble(msg: msgs[i]),
          );
        },
      ),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  final SessionMessage msg;
  const _MessageBubble({required this.msg});

  @override
  Widget build(BuildContext context) {
    final isUser = msg.role == 'user';
    final bg = isUser
        ? Theme.of(context).colorScheme.primary.withOpacity(0.18)
        : TroikaPalette.of(context).surface;
    final align = isUser ? Alignment.centerRight : Alignment.centerLeft;
    final crossAxis =
        isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Align(
        alignment: align,
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxWidth: MediaQuery.of(context).size.width * 0.82,
          ),
          child: Column(
            crossAxisAlignment: crossAxis,
            children: [
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                decoration: BoxDecoration(
                  color: bg,
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Text(
                  msg.content,
                  style: TextStyle(
                      color: TroikaPalette.of(context).text,
                      fontSize: 16,
                      height: 1.45),
                ),
              ),
              if (msg.timestamp != null)
                Padding(
                  padding: const EdgeInsets.only(top: 2, left: 4, right: 4),
                  child: Text(
                    _formatTime(msg.timestamp!),
                    style: TextStyle(
                      color: TroikaPalette.of(context).textMuted,
                      fontSize: 12,
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }

  String _formatTime(double ts) {
    final dt = DateTime.fromMillisecondsSinceEpoch((ts * 1000).round());
    final hh = dt.hour.toString().padLeft(2, '0');
    final mm = dt.minute.toString().padLeft(2, '0');
    return '$hh:$mm';
  }
}
