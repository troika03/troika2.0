import '../widgets/troika_page.dart';
import 'package:flutter/material.dart';

import '../services/capability_service.dart';

class CapabilitiesScreen extends StatefulWidget {
  final CapabilityService? service;
  const CapabilitiesScreen({super.key, this.service});

  @override
  State<CapabilitiesScreen> createState() => _CapabilitiesScreenState();
}

class _CapabilitiesScreenState extends State<CapabilitiesScreen>
    with WidgetsBindingObserver {
  late final CapabilityService _service;
  List<TroikaCapability>? _items;
  String? _error;
  bool _loading = true;
  String? _saving;
  int _tab = 0;

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
      final items = await _service.load();
      if (mounted) setState(() => _items = items);
    } catch (error) {
      if (mounted) {
        setState(() {
          _items = null;
          _error = error is CapabilityException
              ? error.message
              : 'Не удалось загрузить возможности. Попробуйте ещё раз.';
        });
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _toggle(TroikaCapability item, bool enabled) async {
    setState(() => _saving = item.id);
    try {
      final items = await _service.setEnabled(item.id, enabled);
      if (mounted) {
        setState(() => _items = items);
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('${item.title}: ${enabled ? "включено" : "выключено"}'),
        ));
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(error is CapabilityException
              ? error.message
              : 'Изменение не сохранено. Попробуйте ещё раз.'),
        ));
      }
    } finally {
      if (mounted) setState(() => _saving = null);
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
    final colors = Theme.of(context).colorScheme;
    return TroikaPage(
      appBar: AppBar(
        title: const Text('Возможности'),
        surfaceTintColor: Colors.transparent,
        actions: [
          IconButton(
              tooltip: 'Обновить',
              onPressed: _loading || _saving != null ? null : _load,
              icon: const Icon(Icons.refresh))
        ],
      ),
      body: Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 640),
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _error != null
                  ? Center(
                      child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(mainAxisSize: MainAxisSize.min, children: [
                        Text(_error!, textAlign: TextAlign.center),
                        const SizedBox(height: 16),
                        FilledButton(
                            onPressed: _load, child: const Text('Повторить')),
                      ]),
                    ))
                  : ListView(
                      padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
                      children: [
                        const TroikaIntro(
                            icon: Icons.extension_outlined,
                            title: 'Больше возможностей',
                            subtitle:
                                'Тройка сама выбирает нужное для задачи. Ты решаешь, что ей доступно.'),
                        Text(
                            'Настройки общие для аккаунта. Данные сохраняются.',
                            style: TextStyle(color: colors.onSurfaceVariant)),
                        const SizedBox(height: 16),
                        Wrap(
                          spacing: 8,
                          runSpacing: 8,
                          children: [
                            for (final (index, label) in [
                              (0, 'Плагины'),
                              (1, 'Навыки'),
                              (2, 'Инструменты'),
                            ])
                              ChoiceChip(
                                label: Text(label),
                                selected: _tab == index,
                                showCheckmark: false,
                                onSelected: (_) => setState(() => _tab = index),
                              ),
                          ],
                        ),
                        const SizedBox(height: 16),
                        if (_items!.isEmpty)
                          const Padding(
                              padding: EdgeInsets.all(24),
                              child: Text(
                                  'В этом аккаунте пока нет доступных возможностей.')),
                        for (final item in _items!) _entry(item),
                      ],
                    ),
        ),
      ),
    );
  }

  Widget _entry(TroikaCapability item) {
    final colors = Theme.of(context).colorScheme;
    final active = item.available && item.enabled;
    final status = !item.available
        ? 'Не настроено на сервере'
        : active
            ? 'Подключено'
            : 'Выключено';
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Material(
        color: colors.surface,
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
            side: BorderSide(
                color: colors.outlineVariant.withValues(alpha: 0.5))),
        clipBehavior: Clip.antiAlias,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          child:
              Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (_tab == 0)
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: Text(item.title),
                subtitle:
                    Text('${item.description}\n$status · Встроенный плагин'),
                isThreeLine: true,
                value: active,
                onChanged: !item.available || _saving != null
                    ? null
                    : (enabled) => _toggle(item, enabled),
                secondary: _saving == item.id
                    ? const SizedBox(
                        width: 24,
                        height: 24,
                        child: CircularProgressIndicator(strokeWidth: 2))
                    : TroikaIcon(icon: _icon(item.id)),
              )
            else ...[
              Text(item.title, style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 4),
              Text(status, style: TextStyle(color: colors.onSurfaceVariant)),
              const SizedBox(height: 12),
              if (_tab == 1)
                for (final skill in item.skills)
                  Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Text(skill))
              else
                for (final tool in item.tools)
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text(tool.title),
                    subtitle: Text(!tool.available
                        ? 'Не настроено на сервере'
                        : active
                            ? 'Доступен Тройке'
                            : 'Плагин выключен'),
                    leading: Icon(
                        tool.available && active
                            ? Icons.check_circle_outline
                            : Icons.remove_circle_outline,
                        color: colors.onSurfaceVariant,
                        size: 20),
                  ),
            ],
          ]),
        ),
      ),
    );
  }

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
