import 'package:flutter/material.dart';
import '../services/troika_api_service.dart';
import '../widgets/troika_page.dart';
import 'session_detail_screen.dart';

class HistoryScreen extends StatefulWidget {
  final TroikaApiService? api;
  const HistoryScreen({super.key, this.api});
  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  late final TroikaApiService _api;
  Future<List<SessionSummary>>? _future;
  String _query = '';

  @override
  void initState() {
    super.initState();
    _api = widget.api ?? TroikaApiService();
    _reload();
  }

  void _reload() => setState(() => _future = _api.listSessions(limit: 100));

  @override
  Widget build(BuildContext context) => TroikaPage(
        appBar: AppBar(title: const Text('История'), actions: [
          IconButton(
              tooltip: 'Обновить',
              onPressed: _reload,
              icon: const Icon(Icons.refresh_rounded)),
        ]),
        body: FutureBuilder<List<SessionSummary>>(
            future: _future,
            builder: (context, snap) {
              if (snap.connectionState == ConnectionState.waiting) {
                return const Center(child: CircularProgressIndicator());
              }
              if (snap.hasError)
                return SingleChildScrollView(
                    child: TroikaEmptyState(
                        icon: Icons.cloud_off_outlined,
                        title: 'История пока недоступна',
                        message: snap.error.toString(),
                        actionLabel: 'Повторить',
                        onAction: _reload));
              final sessions = [...(snap.data ?? <SessionSummary>[])];
              sessions.sort(
                  (a, b) => (b.lastActive ?? 0).compareTo(a.lastActive ?? 0));
              final filtered = sessions
                  .where((s) => '${s.title ?? ''} ${s.preview ?? ''}'
                      .toLowerCase()
                      .contains(_query.toLowerCase()))
                  .toList();
              return ListView(
                  padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
                  children: [
                    const TroikaIntro(
                        icon: Icons.history_rounded,
                        title: 'Продолжим с того места',
                        subtitle:
                            'Разговоры и результаты, к которым можно вернуться.'),
                    if (sessions.isNotEmpty) ...[
                      TextField(
                          onChanged: (v) => setState(() => _query = v),
                          decoration: const InputDecoration(
                              hintText: 'Найти разговор',
                              prefixIcon: Icon(Icons.search))),
                      const SizedBox(height: 24),
                    ],
                    if (sessions.isEmpty)
                      const TroikaEmptyState(
                          icon: Icons.chat_bubble_outline,
                          title: 'Первый разговор впереди',
                          message:
                              'Поговори с Тройкой голосом или напиши в разделе «Текст». Диалог появится здесь.'),
                    if (sessions.isNotEmpty && filtered.isEmpty)
                      const TroikaEmptyState(
                          icon: Icons.search_off,
                          title: 'Не нашли такой разговор',
                          message:
                              'Попробуй другое слово из названия или начала разговора.'),
                    for (var i = 0; i < filtered.length; i++) ...[
                      if (i == 0 ||
                          _day(filtered[i].lastActive) !=
                              _day(filtered[i - 1].lastActive))
                        Padding(
                            padding: const EdgeInsets.only(top: 8, bottom: 12),
                            child: Text(_day(filtered[i].lastActive),
                                style: const TextStyle(
                                    fontSize: 16,
                                    fontWeight: FontWeight.w600))),
                      _SessionTile(session: filtered[i]),
                    ],
                  ]);
            }),
      );
}

String _day(double? ts) {
  if (ts == null) return 'Ранее';
  final date = DateTime.fromMillisecondsSinceEpoch((ts * 1000).round());
  final now = DateTime.now();
  final today = DateTime(now.year, now.month, now.day);
  final day = DateTime(date.year, date.month, date.day);
  if (day == today) return 'Сегодня';
  if (day == today.subtract(const Duration(days: 1))) return 'Вчера';
  const months = [
    'января',
    'февраля',
    'марта',
    'апреля',
    'мая',
    'июня',
    'июля',
    'августа',
    'сентября',
    'октября',
    'ноября',
    'декабря'
  ];
  return '${date.day} ${months[date.month - 1]}${date.year != now.year ? ' ${date.year}' : ''}';
}

class _SessionTile extends StatelessWidget {
  final SessionSummary session;
  const _SessionTile({required this.session});
  @override
  Widget build(BuildContext context) {
    final p = TroikaPalette.of(context);
    final title = (session.title ?? '').trim();
    final preview = (session.preview ?? '').trim();
    final shown = title.isNotEmpty
        ? title
        : preview.isNotEmpty
            ? preview
            : 'Новый разговор';
    return Card(
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () => Navigator.push(
              context,
              MaterialPageRoute(
                  builder: (_) => TroikaPageScope(
                      child: SessionDetailScreen(
                          sessionId: session.id, headerTitle: shown)))),
          child: Padding(
              padding: const EdgeInsets.all(20),
              child:
                  Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const TroikaIcon(icon: Icons.chat_bubble_outline, size: 40),
                const SizedBox(width: 12),
                Expanded(
                    child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                      Text(shown,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                              color: p.text,
                              fontSize: 16,
                              fontWeight: FontWeight.w600)),
                      if (preview.isNotEmpty &&
                          title.isNotEmpty &&
                          preview != title) ...[
                        const SizedBox(height: 8),
                        Text(preview,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(color: p.textMuted, height: 1.4)),
                      ],
                      const SizedBox(height: 12),
                      Text('${session.messageCount} реплик',
                          style: TextStyle(color: p.textMuted)),
                    ])),
                const SizedBox(width: 8),
                Icon(Icons.chevron_right, color: p.textMuted, size: 20),
              ])),
        ));
  }
}
