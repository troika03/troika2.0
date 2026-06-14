import 'package:flutter/material.dart';
import '../services/hermes_api_service.dart';

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
  late final HermesApiService _api;
  Future<List<SessionMessage>>? _future;

  @override
  void initState() {
    super.initState();
    _api = HermesApiService();
    _future = _api.getSessionMessages(widget.sessionId);
  }

  @override
  Widget build(BuildContext context) {
    const accent = Color(0xFFF5A623);
    return Scaffold(
      backgroundColor: const Color(0xFF0C0B0A),
      appBar: AppBar(
        backgroundColor: const Color(0xFF0C0B0A),
        elevation: 0,
        iconTheme: const IconThemeData(color: accent),
        title: Text(
          widget.headerTitle,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(
            color: Colors.white,
            fontSize: 14,
            fontWeight: FontWeight.w400,
          ),
        ),
      ),
      body: FutureBuilder<List<SessionMessage>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(
              child: CircularProgressIndicator(color: accent),
            );
          }
          if (snap.hasError) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text(
                  snap.error.toString(),
                  style: const TextStyle(color: Colors.white70),
                  textAlign: TextAlign.center,
                ),
              ),
            );
          }
          final msgs = snap.data ?? const [];
          if (msgs.isEmpty) {
            return const Center(
              child: Text(
                'Сообщений нет',
                style: TextStyle(color: Colors.white54),
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
        ? const Color(0xFFF5A623).withOpacity(0.18)
        : Colors.white.withOpacity(0.05);
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
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(
                  msg.content,
                  style: const TextStyle(color: Colors.white, fontSize: 14),
                ),
              ),
              if (msg.timestamp != null)
                Padding(
                  padding: const EdgeInsets.only(top: 2, left: 4, right: 4),
                  child: Text(
                    _formatTime(msg.timestamp!),
                    style: const TextStyle(
                      color: Colors.white38,
                      fontSize: 10,
                      fontFamily: 'monospace',
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
