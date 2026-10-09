import 'package:flutter/material.dart';
import '../widgets/troika_page.dart';
import 'files_screen.dart';
import 'local_documents_screen.dart';
import 'development_screen.dart';

class FilesHubScreen extends StatelessWidget {
  const FilesHubScreen({super.key});

  Future<void> _open(BuildContext context, Widget screen) => Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => TroikaPageScope(child: screen)));

  @override
  Widget build(BuildContext context) => TroikaPage(
        appBar: AppBar(title: const Text('Файлы')),
        body: ListView(
            padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
            children: [
              const TroikaIntro(
                  icon: Icons.folder_open_rounded,
                  title: 'От идеи до результата',
                  subtitle:
                      'Документы, презентации и код. Создавай новое или возвращайся к сохранённому.'),
              TroikaActionCard(
                  icon: Icons.folder_outlined,
                  title: 'Личные файлы',
                  subtitle: 'Открыть, сохранить или поделиться',
                  onTap: () => _open(context, const FilesScreen())),
              const SizedBox(height: 12),
              Text('Создать новое',
                  style: TextStyle(
                      color: TroikaPalette.of(context).text,
                      fontSize: 20,
                      fontWeight: FontWeight.w600)),
              const SizedBox(height: 16),
              TroikaActionCard(
                  icon: Icons.description_outlined,
                  title: 'Документ',
                  subtitle: 'Текст в аккуратном файле DOCX · локально',
                  color: TroikaPalette.of(context).dark
                      ? const Color(0xFF94BDDD)
                      : const Color(0xFF376489),
                  onTap: () => _open(context, const LocalDocumentsScreen())),
              TroikaActionCard(
                  icon: Icons.slideshow_outlined,
                  title: 'Презентация',
                  subtitle: 'Слайды в формате PPTX · локально',
                  onTap: () => _open(context,
                      const LocalDocumentsScreen(initialPresentation: true))),
              TroikaActionCard(
                  icon: Icons.code_rounded,
                  title: 'Разработка',
                  subtitle: 'Проект с исходниками, проверкой и исправлениями',
                  color: TroikaPalette.of(context).dark
                      ? const Color(0xFFAEC9A2)
                      : const Color(0xFF526E43),
                  onTap: () => _open(context, const DevelopmentScreen())),
            ]),
      );
}
