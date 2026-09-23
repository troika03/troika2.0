import 'package:flutter/material.dart';
import '../services/troika_api_service.dart';
import 'session_detail_screen.dart';

/// Экран истории диалогов: список всех сессий из state.db на сервере.
/// Тап по элементу → детальный экран с полным транскриптом.
class HistoryScreen extends StatefulWidget {
  const HistoryScreen({super.key});

  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  late final TroikaApiService _api;
  Future<List<SessionSummary>>? _future;

  @override
  void initState() {
    super.initState();
    _api = TroikaApiService();
    _reload();
  }

  void _reload() {
    setState(() {
      _future = _api.listSessions(limit: 100);
    });
  }

  @override
  Widget build(BuildContext context) {
    const accent = Color(0xFFF5A623);
    return Scaffold(
      backgroundColor: const Color(0xFF0C0B0A),
      appBar: AppBar(
        backgroundColor: const Color(0xFF0C0B0A),
        elevation: 0,
        title: const Text(
          'И С Т О Р И Я',
          style: TextStyle(
            letterSpacing: 6,
            fontWeight: FontWeight.w300,
            fontFamily: 'monospace',
            color: accent,
          ),
        ),
        iconTheme: const IconThemeData(color: accent),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: accent),
            onPressed: _reload,
          ),
        ],
      ),
      body: FutureBuilder<List<SessionSummary>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(
              child: CircularProgressIndicator(color: accent),
            );
          }
          if (snap.hasError) {
            return _ErrorView(
              error: snap.error.toString(),
              onRetry: _reload,
            );
          }
          final sessions = snap.data ?? const [];
          if (sessions.isEmpty) {
            return const Center(
              child: Text(
                'Сессий пока нет',
                style: TextStyle(color: Colors.white54),
              ),
            );
          }
          return ListView.separated(
            padding: const EdgeInsets.symmetric(vertical: 8),
            itemCount: sessions.length,
            separatorBuilder: (_, __) => Divider(
              color: Colors.white.withOpacity(0.06),
              height: 1,
            ),
            itemBuilder: (context, i) => _SessionTile(session: sessions[i]),
          );
        },
      ),
    );
  }
}

class _SessionTile extends StatelessWidget {
  final SessionSummary session;
  const _SessionTile({required this.session});

  @override
  Widget build(BuildContext context) {
    final preview = (session.preview ?? '').trim();
    final title = (session.title ?? '').trim();
    final shown =
        title.isNotEmpty ? title : (preview.isNotEmpty ? preview : '(пусто)');
    final time = _formatTime(session.lastActive);
    return ListTile(
      title: Text(
        shown,
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
        style: const TextStyle(color: Colors.white, fontSize: 14),
      ),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: 4),
        child: Row(
          children: [
            Text(
              '${session.messageCount} реплик',
              style: const TextStyle(color: Colors.white38, fontSize: 11),
            ),
            const SizedBox(width: 12),
            if (session.source != null && session.source!.isNotEmpty)
              Text(
                session.source!,
                style: const TextStyle(
                  color: Color(0xFFF5A623),
                  fontSize: 11,
                  fontFamily: 'monospace',
                ),
              ),
            const Spacer(),
            Text(
              time,
              style: const TextStyle(color: Colors.white38, fontSize: 11),
            ),
          ],
        ),
      ),
      onTap: () => Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => SessionDetailScreen(
            sessionId: session.id,
            headerTitle: shown,
          ),
        ),
      ),
    );
  }

  String _formatTime(double? ts) {
    if (ts == null) return '';
    final dt = DateTime.fromMillisecondsSinceEpoch((ts * 1000).round());
    final now = DateTime.now();
    final sameDay =
        dt.year == now.year && dt.month == now.month && dt.day == now.day;
    final yesterday = now.subtract(const Duration(days: 1));
    final isYesterday = dt.year == yesterday.year &&
        dt.month == yesterday.month &&
        dt.day == yesterday.day;
    final hh = dt.hour.toString().padLeft(2, '0');
    final mm = dt.minute.toString().padLeft(2, '0');
    if (sameDay) return '$hh:$mm';
    if (isYesterday) return 'вчера $hh:$mm';
    return '${dt.day.toString().padLeft(2, '0')}.${dt.month.toString().padLeft(2, '0')} $hh:$mm';
  }
}

class _ErrorView extends StatelessWidget {
  final String error;
  final VoidCallback onRetry;
  const _ErrorView({required this.error, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(Icons.error_outline, color: Colors.redAccent, size: 48),
          const SizedBox(height: 12),
          Text(
            error,
            style: const TextStyle(color: Colors.white70),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 16),
          TextButton(onPressed: onRetry, child: const Text('Повторить')),
        ],
      ),
    );
  }
}
