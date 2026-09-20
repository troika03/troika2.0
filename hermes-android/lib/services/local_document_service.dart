import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';

class LocalDocumentService {
  Future<bool> createDocument({
    required String title,
    required String content,
  }) async {
    final bytes = _buildDocx(title.trim(), content.trim());
    return _save(bytes, '${_safeName(title, 'document')}.docx', 'docx');
  }

  Future<bool> createPresentation({
    required String title,
    required String content,
  }) async {
    final slides = content
        .split(RegExp(r'\n\s*---\s*\n'))
        .map((part) => part.trim())
        .where((part) => part.isNotEmpty)
        .toList();
    final bytes = _buildPptx(title.trim(), slides.isEmpty ? [title] : slides);
    return _save(bytes, '${_safeName(title, 'presentation')}.pptx', 'pptx');
  }

  Future<bool> _save(Uint8List bytes, String fileName, String extension) async {
    final mobile = Platform.isAndroid || Platform.isIOS;
    final target = await FilePicker.platform.saveFile(
      dialogTitle: 'Сохранить $fileName',
      fileName: fileName,
      type: FileType.custom,
      allowedExtensions: [extension],
      bytes: mobile ? bytes : null,
    );
    if (target == null) return false;
    if (!mobile) await File(target).writeAsBytes(bytes, flush: true);
    return true;
  }

  static String _safeName(String value, String fallback) {
    final clean = value
        .trim()
        .replaceAll(RegExp(r'[<>:"/\\|?*\x00-\x1F]'), '_')
        .replaceAll(RegExp(r'\s+'), ' ');
    return clean.isEmpty
        ? fallback
        : clean.substring(0, clean.length > 80 ? 80 : clean.length);
  }

  static Uint8List buildDocumentBytes(String title, String content) =>
      _buildDocx(title.trim(), content.trim());

  static Uint8List buildPresentationBytes(
    String title,
    List<String> slides,
  ) =>
      _buildPptx(title.trim(), slides);

  static Uint8List _buildDocx(String title, String content) {
    final paragraphs = <String>[
      if (title.isNotEmpty)
        '<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>${_xml(title)}</w:t></w:r></w:p>',
      for (final line in content.split('\n'))
        '<w:p><w:r><w:t xml:space="preserve">${_xml(line)}</w:t></w:r></w:p>',
    ].join();
    return _ZipStore.build({
      '[Content_Types].xml':
          '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>''',
      '_rels/.rels': '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>''',
      'word/document.xml':
          '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>$paragraphs<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr></w:body></w:document>''',
      'word/styles.xml':
          '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:sz w:val="24"/></w:rPr></w:style><w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="40"/></w:rPr></w:style></w:styles>''',
    });
  }

  static Uint8List _buildPptx(String title, List<String> slideBodies) {
    final files = <String, String>{};
    final overrides = StringBuffer();
    final slideIds = StringBuffer();
    final presentationRels = StringBuffer();
    for (var i = 0; i < slideBodies.length; i++) {
      final number = i + 1;
      overrides.write(
          '<Override PartName="/ppt/slides/slide$number.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>');
      slideIds.write('<p:sldId id="${255 + number}" r:id="rId${number + 1}"/>');
      presentationRels.write(
          '<Relationship Id="rId${number + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide$number.xml"/>');
      final lines = slideBodies[i]
          .split('\n')
          .where((line) => line.trim().isNotEmpty)
          .toList();
      final slideTitle = lines.isEmpty ? title : lines.first.trim();
      final bullets = lines
          .skip(1)
          .map((line) => line.replaceFirst(RegExp(r'^[-•]\s*'), '').trim())
          .where((line) => line.isNotEmpty)
          .toList();
      files['ppt/slides/slide$number.xml'] = _slideXml(slideTitle, bullets);
      files['ppt/slides/_rels/slide$number.xml.rels'] =
          '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/></Relationships>''';
    }
    files.addAll({
      '[Content_Types].xml':
          '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/><Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/><Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/><Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>$overrides</Types>''',
      '_rels/.rels':
          '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/></Relationships>''',
      'ppt/presentation.xml':
          '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:sldIdLst>$slideIds</p:sldIdLst><p:sldSz cx="12192000" cy="6858000" type="screen16x9"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>''',
      'ppt/_rels/presentation.xml.rels':
          '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>$presentationRels</Relationships>''',
      'ppt/slideMasters/slideMaster1.xml': _slideMaster,
      'ppt/slideMasters/_rels/slideMaster1.xml.rels':
          '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/></Relationships>''',
      'ppt/slideLayouts/slideLayout1.xml': _slideLayout,
      'ppt/slideLayouts/_rels/slideLayout1.xml.rels':
          '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/></Relationships>''',
      'ppt/theme/theme1.xml': _theme,
    });
    return _ZipStore.build(files);
  }

  static String _slideXml(String title, List<String> bullets) {
    final body = bullets.isEmpty
        ? '<a:p><a:r><a:rPr lang="ru-RU" sz="2400"/><a:t></a:t></a:r></a:p>'
        : bullets
            .map((text) =>
                '<a:p><a:pPr marL="342900" indent="-285750"><a:buChar char="•"/></a:pPr><a:r><a:rPr lang="ru-RU" sz="2400"/><a:t>${_xml(text)}</a:t></a:r></a:p>')
            .join();
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/><p:sp><p:nvSpPr><p:cNvPr id="2" name="Title"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="685800" y="457200"/><a:ext cx="10820400" cy="1143000"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="ru-RU" sz="3600" b="1"><a:solidFill><a:srgbClr val="F3F0EA"/></a:solidFill></a:rPr><a:t>${_xml(title)}</a:t></a:r></a:p></p:txBody></p:sp><p:sp><p:nvSpPr><p:cNvPr id="3" name="Content"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="914400" y="2057400"/><a:ext cx="10210800" cy="3886200"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/>$body</p:txBody></p:sp></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>''';
  }

  static String _xml(String value) =>
      const HtmlEscape(HtmlEscapeMode.element).convert(value);

  static const String _slideMaster =
      '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="0C0B0A"/></a:solidFill><a:effectLst/></p:bgPr></p:bg><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld><p:clrMap accent1="F5A623" accent2="E08A12" accent3="FFC65C" accent4="8C887F" accent5="55524B" accent6="211E16" bg1="0C0B0A" bg2="17150F" folHlink="FFC65C" hlink="F5A623" tx1="F3F0EA" tx2="8C887F"/><p:sldLayoutIdLst><p:sldLayoutId id="1" r:id="rId1"/></p:sldLayoutIdLst><p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>''';
  static const String _slideLayout =
      '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank"><p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>''';
  static const String _theme =
      '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Troika"><a:themeElements><a:clrScheme name="Troika"><a:dk1><a:srgbClr val="0C0B0A"/></a:dk1><a:lt1><a:srgbClr val="F3F0EA"/></a:lt1><a:dk2><a:srgbClr val="17150F"/></a:dk2><a:lt2><a:srgbClr val="8C887F"/></a:lt2><a:accent1><a:srgbClr val="F5A623"/></a:accent1><a:accent2><a:srgbClr val="E08A12"/></a:accent2><a:accent3><a:srgbClr val="FFC65C"/></a:accent3><a:accent4><a:srgbClr val="8C887F"/></a:accent4><a:accent5><a:srgbClr val="55524B"/></a:accent5><a:accent6><a:srgbClr val="211E16"/></a:accent6><a:hlink><a:srgbClr val="F5A623"/></a:hlink><a:folHlink><a:srgbClr val="FFC65C"/></a:folHlink></a:clrScheme><a:fontScheme name="Troika"><a:majorFont><a:latin typeface="Aptos Display"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Aptos"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme><a:fmtScheme name="Troika"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>''';
}

class _ZipStore {
  static Uint8List build(Map<String, String> files) {
    final output = BytesBuilder(copy: false);
    final central = BytesBuilder(copy: false);
    var offset = 0;
    var count = 0;
    for (final entry in files.entries) {
      final name = utf8.encode(entry.key);
      final data = utf8.encode(entry.value);
      final crc = _crc32(data);
      final local = BytesBuilder(copy: false)
        ..add(_u32(0x04034b50))
        ..add(_u16(20))
        ..add(_u16(0x0800))
        ..add(_u16(0))
        ..add(_u16(0))
        ..add(_u16(0))
        ..add(_u32(crc))
        ..add(_u32(data.length))
        ..add(_u32(data.length))
        ..add(_u16(name.length))
        ..add(_u16(0))
        ..add(name)
        ..add(data);
      final localBytes = local.takeBytes();
      output.add(localBytes);
      central
        ..add(_u32(0x02014b50))
        ..add(_u16(20))
        ..add(_u16(20))
        ..add(_u16(0x0800))
        ..add(_u16(0))
        ..add(_u16(0))
        ..add(_u16(0))
        ..add(_u32(crc))
        ..add(_u32(data.length))
        ..add(_u32(data.length))
        ..add(_u16(name.length))
        ..add(_u16(0))
        ..add(_u16(0))
        ..add(_u16(0))
        ..add(_u16(0))
        ..add(_u32(0))
        ..add(_u32(offset))
        ..add(name);
      offset += localBytes.length;
      count++;
    }
    final centralBytes = central.takeBytes();
    output
      ..add(centralBytes)
      ..add(_u32(0x06054b50))
      ..add(_u16(0))
      ..add(_u16(0))
      ..add(_u16(count))
      ..add(_u16(count))
      ..add(_u32(centralBytes.length))
      ..add(_u32(offset))
      ..add(_u16(0));
    return output.takeBytes();
  }

  static Uint8List _u16(int value) =>
      (ByteData(2)..setUint16(0, value, Endian.little)).buffer.asUint8List();
  static Uint8List _u32(int value) =>
      (ByteData(4)..setUint32(0, value, Endian.little)).buffer.asUint8List();

  static int _crc32(List<int> data) {
    var crc = 0xffffffff;
    for (final byte in data) {
      crc ^= byte;
      for (var i = 0; i < 8; i++) {
        crc = (crc & 1) != 0 ? (crc >> 1) ^ 0xedb88320 : crc >> 1;
      }
    }
    return (crc ^ 0xffffffff) & 0xffffffff;
  }
}
