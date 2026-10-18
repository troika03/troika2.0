import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/services/development_checkpoint_store.dart';
import 'package:troika_assistant/services/development_autopilot_service.dart';
import 'package:troika_assistant/services/files_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late Directory directory;
  late DevelopmentCheckpointStore store;
  const id = 'run_0123456789abcdef0123456789abcdef';
  final state = <String, dynamic>{
    'version': 1,
    'task': 'Пример с кириллицей',
    'files': [],
    'plan': null,
    'design': <String, dynamic>{},
    'completed': []
  };
  setUp(() async {
    SharedPreferences.setMockInitialValues(
        {'troika_account_email': 'owner@example.com'});
    await TroikaConfig.init();
    directory = await Directory.systemTemp.createTemp('troika-checkpoint-');
    store = DevelopmentCheckpointStore(FilesService(),
        directory: () async => directory);
  });
  tearDown(() async {
    await directory.delete(recursive: true);
  });

  test('atomic copies reject corruption and retain previous saved version',
      () async {
    final value = {
      'revision': 1,
      'digest': DevelopmentCheckpointStore.digest(state),
      'checkpoint': state
    };
    await store.save(id, value);
    expect((await store.read(id))!['checkpoint'], state);
    await store.save(id, {...value, 'revision': 2});
    await File('${directory.path}/$id.json').writeAsString('{interrupted');
    expect((await store.read(id))!['revision'], 1);
    await expectLater(
        store.save(id, {...value, 'digest': 'corrupt'}), throwsFormatException);
    await expectLater(store.read('../other'), throwsFormatException);
    await expectLater(
        store.read(id, owner: 'foreign@example.com'), throwsStateError);
  });

  test(
      'restart resume carries the saved version and reuses the original budget only',
      () async {
    final digest = DevelopmentCheckpointStore.digest(state);
    await store.save(id, {
      'revision': 1,
      'digest': digest,
      'checkpoint': state,
      'title': 'Example'
    });
    Map<String, dynamic>? resumed;
    final controller = DevelopmentAutopilotService(
        checkpointStore: store,
        requestForTesting: (method, path, body) async {
          if (path.endsWith('/resume')) {
            resumed = body;
            return {'run_id': 'new-run'};
          }
          return {
            'enabled': true,
            'projects': [
              {
                'project_id': id,
                'run_id': id,
                'status': 'interrupted',
                'stage': 'interrupted',
                'created_at': 1,
                'checkpoint_revision': 1,
                'checkpoint_digest': digest,
                'reports': [],
                'workers': []
              }
            ]
          };
        });
    addTearDown(controller.dispose);
    await controller.observe();
    expect(resumed!['reuse_budget'], true);
    expect(resumed!['revision'], 1);
    expect(jsonEncode(resumed!['checkpoint']), jsonEncode(state));
    expect(controller.projects.single['title'], 'Example');
  });
}
