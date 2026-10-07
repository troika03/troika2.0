import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../services/web_sources.dart';

class WebSourcesView extends StatelessWidget {
  final WebSourceTrace trace;
  const WebSourcesView({super.key, required this.trace});

  String _siteInitial(String host) {
    final name =
        host.startsWith('www.') && host.length > 4 ? host.substring(4) : host;
    return name.isEmpty ? '?' : name.substring(0, 1).toUpperCase();
  }

  @override
  Widget build(BuildContext context) {
    if (trace.isEmpty) return const SizedBox.shrink();
    final count = trace.sources.length;
    final noun = count % 100 >= 11 && count % 100 <= 14
        ? 'страниц'
        : switch (count % 10) {
            1 => 'страница',
            2 || 3 || 4 => 'страницы',
            _ => 'страниц',
          };
    final label = trace.phase == 'failed' ||
            trace.phase == 'searching' ||
            trace.phase == 'reading' ||
            count == 0
        ? trace.label
        : 'Найдено $count $noun';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: ExpansionTile(
        tilePadding: EdgeInsets.zero,
        childrenPadding: EdgeInsets.zero,
        shape: const Border(),
        collapsedShape: const Border(),
        leading: const Icon(Icons.search, size: 20),
        title: Text(label, style: Theme.of(context).textTheme.bodyMedium),
        trailing: count == 0
            ? null
            : Row(mainAxisSize: MainAxisSize.min, children: [
                for (final host
                    in trace.sources.map((s) => s.uri.host).toSet().take(3))
                  Padding(
                    padding: const EdgeInsets.only(left: 3),
                    child: Tooltip(
                      message: host,
                      child: CircleAvatar(
                        radius: 10,
                        backgroundColor: Theme.of(context)
                            .colorScheme
                            .surfaceContainerHighest,
                        child: Text(_siteInitial(host),
                            style: Theme.of(context).textTheme.labelSmall),
                      ),
                    ),
                  ),
                const SizedBox(width: 4),
                const Icon(Icons.expand_more, size: 18),
              ]),
        children: [
          for (final source in trace.sources)
            ListTile(
              contentPadding: EdgeInsets.zero,
              minVerticalPadding: 8,
              title: Text(source.title.isEmpty ? source.uri.host : source.title,
                  maxLines: 2, overflow: TextOverflow.ellipsis),
              subtitle: Text('${source.uri.host} · ${source.statusLabel}'),
              trailing: const Icon(Icons.open_in_new, size: 18),
              tileColor: Colors.transparent,
              leading: Tooltip(
                message: source.uri.toString(),
                child: const Icon(Icons.link, size: 18),
              ),
              onTap: () async {
                try {
                  final opened = await launchUrl(source.uri,
                      mode: LaunchMode.externalApplication);
                  if (opened || !context.mounted) return;
                } catch (_) {
                  if (!context.mounted) return;
                }
                if (context.mounted) {
                  ScaffoldMessenger.maybeOf(context)?.showSnackBar(
                    const SnackBar(content: Text('Не удалось открыть ссылку.')),
                  );
                }
              },
            ),
        ],
      ),
    );
  }
}
