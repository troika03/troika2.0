import '../widgets/troika_page.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../services/capability_service.dart';

/// Account catalogue: skills, MCP servers and product tools.
class CapabilitiesScreen extends StatefulWidget {
  final CapabilityService? service;
  const CapabilitiesScreen({super.key, this.service});

  /// Opens a URL in the browser; overridable in tests.
  @visibleForTesting
  static Future<bool> Function(Uri) openUrl = (uri) =>
      launchUrl(uri, mode: LaunchMode.externalApplication);

  @override
  State<CapabilitiesScreen> createState() => _CapabilitiesScreenState();
}

enum _Filter { all, connected, available }

class _CapabilitiesScreenState extends State<CapabilitiesScreen>
    with WidgetsBindingObserver {
  late final CapabilityService _service;
  ExtensionCatalogue? _catalogue;
  String? _error;
  bool _loading = true;
  String? _saving;
  final _queries = <int, String>{0: '', 1: ''};
  final _filters = <int, _Filter>{0: _Filter.all, 1: _Filter.all};
  String? _signingIn;
  bool _cancelSignIn = false;

  @override
  void initState() {
    super.initState();
    _service = widget.service ?? CapabilityService();
    WidgetsBinding.instance.addObserver(this);
    _load();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && !_loading && _saving == null) {
      _load();
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final catalogue = await _service.loadCatalogue();
      if (mounted) setState(() => _catalogue = catalogue);
    } catch (error) {
      if (mounted) {
        setState(() {
          _catalogue = null;
          _error = error is CapabilityException
              ? error.message
              : 'Не удалось загрузить возможности. Попробуйте ещё раз.';
        });
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _save(
    String key,
    String done,
    Future<ExtensionCatalogue> Function() action,
  ) async {
    setState(() => _saving = key);
    try {
      final catalogue = await action();
      if (mounted) {
        setState(() => _catalogue = catalogue);
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(done)));
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              error is CapabilityException
                  ? error.message
                  : 'Изменение не сохранено. Попробуйте ещё раз.',
            ),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = null);
    }
  }

  Future<void> _toggleTool(TroikaCapability item, bool enabled) => _save(
    'tool:${item.id}',
    '${item.title}: ${enabled ? "включено" : "выключено"}',
    () => _service.setToolEnabled(item.id, enabled),
  );

  Future<void> _toggleEntry(int tab, CatalogueEntry item, bool connect) async {
    final host = Uri.tryParse(item.homepage)?.host ?? '';
    if (connect && tab == 1 && item.accountService) {
      await _connectService(item);
      return;
    }
    if (connect) {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text('Подключить «${item.title}»?'),
          content: Text(
            tab == 0
                ? 'Тройка сможет применять инструкции этого навыка в разговорах. '
                      'Навык работает только с включёнными инструментами и не '
                      'запускает программ. Отключить можно в любой момент.'
                : 'Тройка сможет искать и читать данные этого сервиса, когда '
                      'это нужно для задачи. Текст запросов будет отправляться в '
                      '${host.isEmpty ? "сервис" : host}. Ваши ключи, файлы и '
                      'история туда не передаются. Сервис только читает свои '
                      'данные. Отключить можно в любой момент.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Отмена'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Подключить'),
            ),
          ],
        ),
      );
      if (confirmed != true || !mounted) return;
    }
    await _save(
      '$tab:${item.id}',
      '${item.title}: ${connect ? "подключено" : "отключено"}',
      () => tab == 0
          ? _service.setSkillConnected(item.id, connect)
          : _service.setMcpConnected(item.id, connect),
    );
  }

  Future<void> _connectService(CatalogueEntry item) async {
    String? token;
    if (item.connect == 'token') {
      token = await showDialog<String>(
        context: context,
        builder: (context) =>
            _TokenDialog(item: item, openUrl: CapabilitiesScreen.openUrl),
      );
      if (token == null || token.isEmpty || !mounted) return;
    } else {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text('Подключить «${item.title}»?'),
          content: Text(
            'Откроется страница входа ${item.title}. После входа Тройка сможет '
            'читать данные сервиса, а изменять их — только после вашего '
            'подтверждения каждого действия. Доступ хранится зашифрованным '
            'на сервере Тройки для вашего аккаунта. Отключить можно в любой '
            'момент.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Отмена'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Войти'),
            ),
          ],
        ),
      );
      if (confirmed != true || !mounted) return;
    }
    final messenger = ScaffoldMessenger.of(context);
    setState(() {
      _saving = '1:${item.id}';
      _signingIn = token == null ? item.id : null;
      _cancelSignIn = false;
    });
    try {
      final start = await _service.connectService(item.id, token: token);
      if (start.status == 'waiting') {
        if (!await CapabilitiesScreen.openUrl(start.authorizationUrl!)) {
          throw const CapabilityException(
            'Не удалось открыть браузер для входа.',
          );
        }
        messenger.showSnackBar(
          const SnackBar(
            content: Text('Завершите вход в браузере и вернитесь сюда'),
          ),
        );
        var status = 'waiting';
        // Sign-in waits up to ten minutes on the server.
        for (var attempt = 0; attempt < 300 && status == 'waiting'; attempt++) {
          await Future<void>.delayed(const Duration(seconds: 2));
          if (!mounted || _cancelSignIn) return;
          status = await _service.serviceFlowStatus(start.flow);
        }
        if (status != 'connected') {
          throw CapabilityException(
            status == 'expired'
                ? 'Время входа истекло. Попробуйте ещё раз.'
                : 'Вход не завершён. Попробуйте ещё раз.',
          );
        }
      }
      final catalogue = await _service.loadCatalogue();
      if (!mounted) return;
      setState(() => _catalogue = catalogue);
      messenger.showSnackBar(
        SnackBar(content: Text('${item.title}: подключено')),
      );
    } catch (error) {
      if (mounted) {
        messenger.showSnackBar(
          SnackBar(
            content: Text(
              error is CapabilityException
                  ? error.message
                  : 'Сервис не подключён. Попробуйте ещё раз.',
            ),
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() {
          _saving = null;
          _signingIn = null;
        });
      }
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    if (widget.service == null) _service.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final catalogue = _catalogue;
    return DefaultTabController(
      length: 3,
      child: TroikaPage(
        appBar: AppBar(
          title: const Text('Возможности'),
          surfaceTintColor: Colors.transparent,
          actions: [
            IconButton(
              tooltip: 'Обновить',
              onPressed: _loading || _saving != null ? null : _load,
              icon: const Icon(Icons.refresh),
            ),
          ],
          bottom: TabBar(
            isScrollable: true,
            tabAlignment: TabAlignment.start,
            tabs: [
              Tab(text: _tabLabel('Скиллы', catalogue?.skills)),
              Tab(text: _tabLabel('MCP', catalogue?.mcp)),
              const Tab(text: 'Инструменты'),
            ],
          ),
        ),
        body: Align(
          alignment: Alignment.topCenter,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _error != null
                ? _errorView()
                : TabBarView(
                    children: [
                      _entries(0, catalogue!.skills),
                      _entries(1, catalogue.mcp),
                      _tools(catalogue.tools),
                    ],
                  ),
          ),
        ),
      ),
    );
  }

  String _tabLabel(String label, List<CatalogueEntry>? items) {
    final count = items?.where((item) => item.connected).length ?? 0;
    return count == 0 ? label : '$label · $count';
  }

  Widget _errorView() => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(_error!, textAlign: TextAlign.center),
          const SizedBox(height: 16),
          FilledButton(onPressed: _load, child: const Text('Повторить')),
        ],
      ),
    ),
  );

  Widget _entries(int tab, List<CatalogueEntry>? items) {
    if (items == null) {
      return const _Notice(
        'Обновите сервер Тройки, чтобы увидеть этот каталог.',
      );
    }
    final query = _queries[tab]!.trim().toLowerCase();
    final filter = _filters[tab]!;
    final visible = items.where((item) {
      if (filter == _Filter.connected && !item.connected) return false;
      if (filter == _Filter.available &&
          (!item.connectable || item.connected)) {
        return false;
      }
      if (query.isEmpty) return true;
      return '${item.title} ${item.description} ${item.category} ${item.id}'
          .toLowerCase()
          .contains(query);
    }).toList();
    final connectable = items.where((item) => item.connectable).length;
    final header = <Widget>[
      Text(
        tab == 0
            ? 'Навыков: ${items.length}, для облака: $connectable'
            : 'Серверов MCP: ${items.length}, для облака: $connectable',
        style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
      ),
      const SizedBox(height: 12),
      TextField(
        decoration: InputDecoration(
          hintText: tab == 0 ? 'Найти навык' : 'Найти сервер MCP',
          prefixIcon: const Icon(Icons.search),
          isDense: true,
        ),
        onChanged: (value) => setState(() => _queries[tab] = value),
      ),
      const SizedBox(height: 12),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          for (final (value, label) in [
            (_Filter.all, 'Все'),
            (_Filter.connected, 'Подключено'),
            (_Filter.available, 'Можно подключить'),
          ])
            ChoiceChip(
              label: Text(label),
              selected: filter == value,
              showCheckmark: false,
              onSelected: (_) => setState(() => _filters[tab] = value),
            ),
        ],
      ),
      const SizedBox(height: 12),
      if (_catalogue?.extensionsAllowed == false)
        const Padding(
          padding: EdgeInsets.only(bottom: 12),
          child: _Notice(
            'Скиллы и MCP доступны в тарифе Pro. Здесь видно, что он '
            'добавляет; подключить можно после перехода на Pro.',
            inline: true,
          ),
        )
      else if (tab == 1 && connectable == 0)
        const Padding(
          padding: EdgeInsets.only(bottom: 12),
          child: _Notice(
            'Серверы MCP пока нельзя подключить к облаку: им нужны запуск '
            'программ или вход в сервис. Причина указана у каждого сервера.',
            inline: true,
          ),
        ),
      if (tab == 1 && connectable > 0)
        const Padding(
          padding: EdgeInsets.only(bottom: 12),
          child: _Notice(
            'Публичные серверы работают без входа и только читают. Сервисы '
            'с аккаунтом подключаются входом или токеном; изменения в них '
            'Тройка делает только после вашего подтверждения.',
            inline: true,
          ),
        ),
      if (visible.isEmpty)
        const Padding(
          padding: EdgeInsets.all(24),
          child: Text('Ничего не найдено.', textAlign: TextAlign.center),
        ),
    ];
    return ListView.builder(
      key: PageStorageKey('capabilities-$tab'),
      padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
      itemCount: header.length + visible.length,
      itemBuilder: (context, index) => index < header.length
          ? header[index]
          : _entry(tab, visible[index - header.length]),
    );
  }

  Widget _entry(int tab, CatalogueEntry item) {
    final colors = Theme.of(context).colorScheme;
    final saving = _saving == '$tab:${item.id}';
    final status = item.connected
        ? 'Подключено'
        : item.connectable
        ? 'Можно подключить'
        : 'Недоступно в облаке';
    Widget action;
    if (saving && _signingIn == item.id) {
      action = Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const SizedBox(
            width: 20,
            height: 20,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(width: 12),
          TextButton(
            onPressed: () => setState(() => _cancelSignIn = true),
            child: const Text('Отменить вход'),
          ),
        ],
      );
    } else if (saving) {
      action = const SizedBox(
        width: 24,
        height: 24,
        child: CircularProgressIndicator(strokeWidth: 2),
      );
    } else if (item.connected) {
      action = OutlinedButton(
        onPressed: _saving != null
            ? null
            : () => _toggleEntry(tab, item, false),
        child: const Text('Отключить'),
      );
    } else if (item.connectable) {
      action = FilledButton.tonal(
        onPressed: _saving != null ? null : () => _toggleEntry(tab, item, true),
        child: Text(
          item.connect == 'oauth'
              ? 'Войти'
              : item.connect == 'token'
              ? 'Ввести токен'
              : 'Подключить',
        ),
      );
    } else {
      action = const SizedBox.shrink();
    }
    final hasAction = saving || item.connected || item.connectable;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: _Card(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                TroikaIcon(
                  icon: _entryIcon(item.icon),
                  size: 36,
                  color: item.connected || item.connectable
                      ? null
                      : colors.onSurfaceVariant,
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    item.title,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                if (!item.connectable && !item.connected)
                  Icon(
                    Icons.lock_outline,
                    size: 18,
                    color: colors.onSurfaceVariant,
                    semanticLabel: 'Недоступно в облаке',
                  )
                else if (item.connected)
                  Icon(
                    Icons.check_circle,
                    size: 20,
                    color: colors.primary,
                    semanticLabel: 'Подключено',
                  ),
              ],
            ),
            if (item.description.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                item.description,
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
              ),
            ],
            const SizedBox(height: 6),
            Text(
              [if (item.category.isNotEmpty) item.category, status].join(' · '),
              style: TextStyle(
                color: item.connected
                    ? colors.primary
                    : colors.onSurfaceVariant,
                fontSize: 12,
              ),
            ),
            if (!item.connectable && item.reason.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                item.reason,
                style: TextStyle(color: colors.onSurfaceVariant, fontSize: 12),
              ),
            ],
            if (hasAction) ...[
              const SizedBox(height: 8),
              Align(alignment: Alignment.centerRight, child: action),
            ],
          ],
        ),
      ),
    );
  }

  Widget _tools(List<TroikaCapability> items) {
    final colors = Theme.of(context).colorScheme;
    return ListView(
      key: const PageStorageKey('capabilities-tools'),
      padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
      children: [
        Text(
          'Тройка сама выбирает нужный инструмент. Выключенные она не '
          'использует на всех устройствах.',
          style: TextStyle(color: colors.onSurfaceVariant),
        ),
        const SizedBox(height: 12),
        if (items.isEmpty)
          const Padding(
            padding: EdgeInsets.all(24),
            child: Text('В этом аккаунте пока нет доступных инструментов.'),
          ),
        for (final item in items) _toolGroup(item),
      ],
    );
  }

  Widget _toolGroup(TroikaCapability item) {
    final colors = Theme.of(context).colorScheme;
    final active = item.available && item.enabled;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: _Card(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(item.title),
              subtitle: Text(
                item.available ? item.description : 'Не настроено на сервере',
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
              value: active,
              onChanged: !item.available || _saving != null
                  ? null
                  : (enabled) => _toggleTool(item, enabled),
              secondary: _saving == 'tool:${item.id}'
                  ? const SizedBox(
                      width: 24,
                      height: 24,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : TroikaIcon(icon: _icon(item.id)),
            ),
            for (final tool in item.tools)
              Padding(
                padding: const EdgeInsets.only(left: 4, top: 4),
                child: Row(
                  children: [
                    Icon(
                      tool.available && active
                          ? Icons.check_circle_outline
                          : Icons.remove_circle_outline,
                      color: colors.onSurfaceVariant,
                      size: 18,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        tool.available
                            ? tool.title
                            : '${tool.title} · не настроено',
                        style: TextStyle(
                          color: colors.onSurfaceVariant,
                          fontSize: 13,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }

  IconData _entryIcon(String key) => switch (key) {
    'code' => Icons.code,
    'docs' => Icons.menu_book_outlined,
    'ai' => Icons.psychology_outlined,
    'search' => Icons.travel_explore,
    'tasks' => Icons.checklist_outlined,
    'money' => Icons.payments_outlined,
    'chat' => Icons.chat_bubble_outline,
    'chart' => Icons.insights_outlined,
    'design' => Icons.palette_outlined,
    'globe' => Icons.language,
    'files' => Icons.folder_outlined,
    'computer' => Icons.computer_outlined,
    'media' => Icons.play_circle_outline,
    'heart' => Icons.favorite_border,
    'lock' => Icons.shield_outlined,
    'device' => Icons.devices_other_outlined,
    'idea' => Icons.lightbulb_outline,
    _ => Icons.extension_outlined,
  };

  IconData _icon(String id) => switch (id) {
    'assistant' => Icons.checklist_outlined,
    'web' => Icons.travel_explore,
    'documents' => Icons.description_outlined,
    'development' => Icons.code,
    'files' => Icons.folder_outlined,
    'phone' => Icons.phone_android_outlined,
    'images' => Icons.brush_outlined,
    'vision' => Icons.image_outlined,
    'screen' => Icons.screenshot_monitor_outlined,
    _ => Icons.extension_outlined,
  };
}

class _Card extends StatelessWidget {
  final Widget child;
  const _Card({required this.child});
  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Material(
      color: colors.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: colors.outlineVariant.withValues(alpha: 0.5)),
      ),
      clipBehavior: Clip.antiAlias,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: child,
      ),
    );
  }
}

class _Notice extends StatelessWidget {
  final String text;
  final bool inline;
  const _Notice(this.text, {this.inline = false});
  @override
  Widget build(BuildContext context) {
    final body = Text(
      text,
      textAlign: inline ? TextAlign.start : TextAlign.center,
      style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
    );
    return inline
        ? body
        : Center(
            child: Padding(padding: const EdgeInsets.all(24), child: body),
          );
  }
}

class _TokenDialog extends StatefulWidget {
  final CatalogueEntry item;
  final Future<bool> Function(Uri) openUrl;
  const _TokenDialog({required this.item, required this.openUrl});
  @override
  State<_TokenDialog> createState() => _TokenDialogState();
}

class _TokenDialogState extends State<_TokenDialog> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final help = Uri.tryParse(widget.item.tokenHelp);
    return AlertDialog(
      title: Text('Подключить «${widget.item.title}»'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Вставьте ${widget.item.tokenName.isEmpty ? "личный токен" : widget.item.tokenName}. '
            'Выдайте только нужные права. Токен хранится зашифрованным на '
            'сервере Тройки; изменения в сервисе Тройка делает только после '
            'вашего подтверждения.',
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _controller,
            obscureText: true,
            autocorrect: false,
            enableSuggestions: false,
            decoration: const InputDecoration(labelText: 'Токен'),
          ),
          if (help != null && help.scheme == 'https')
            TextButton.icon(
              onPressed: () => widget.openUrl(help),
              icon: const Icon(Icons.open_in_new, size: 18),
              label: const Text('Где взять токен'),
            ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Отмена'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(context, _controller.text.trim()),
          child: const Text('Подключить'),
        ),
      ],
    );
  }
}
