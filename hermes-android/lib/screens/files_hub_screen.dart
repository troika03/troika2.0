import 'package:flutter/material.dart';

import '../theme/troika_theme.dart';
import 'files_screen.dart';
import 'local_documents_screen.dart';

class FilesHubScreen extends StatelessWidget {
  const FilesHubScreen({super.key});

  Future<void> _open(BuildContext context, Widget screen) {
    return Navigator.push(context, MaterialPageRoute(builder: (_) => screen));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Файлы')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text(
            'Создавай, открывай и сохраняй результаты Тройки.',
            style: TextStyle(color: TroikaColors.textMuted),
          ),
          const SizedBox(height: 18),
          _FileAction(
            icon: Icons.description_outlined,
            title: 'Документ',
            subtitle: 'Создать DOCX локально',
            onTap: () => _open(context, const LocalDocumentsScreen()),
          ),
          _FileAction(
            icon: Icons.slideshow_outlined,
            title: 'Презентация',
            subtitle: 'Создать PPTX локально',
            onTap: () => _open(
              context,
              const LocalDocumentsScreen(initialPresentation: true),
            ),
          ),
          _FileAction(
            icon: Icons.cloud_outlined,
            title: 'Личные файлы',
            subtitle: 'Открыть, экспортировать или сохранить на телефон',
            onTap: () => _open(context, const FilesScreen()),
          ),
        ],
      ),
    );
  }
}

class _FileAction extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  const _FileAction({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: ListTile(
        minTileHeight: 68,
        leading: Icon(icon, color: TroikaColors.brand),
        title: Text(title),
        subtitle: Text(subtitle),
        trailing: const Icon(Icons.chevron_right),
        onTap: onTap,
      ),
    );
  }
}
