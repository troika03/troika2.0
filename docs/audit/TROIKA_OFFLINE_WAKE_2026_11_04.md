# Локальное пробуждение Android

Владелец после установки зелёной APK вручную разрешил микрофон и подтвердил,
что фоновые звуки включения/выключения продолжаются. Ремонт lifecycle не
устранял штатные циклы Android SpeechRecognizer. Этот этап заменяет именно
фоновое ожидание слова «Тройка».

## Реализация

Vosk Android 0.3.75 и JNA 5.18.1 используют один AudioRecord: 16 kHz, mono,
PCM16, источник VOICE_RECOGNITION. Silence и конец посторонней реплики
сбрасывают только декодер. Grammar ["тройка", "[unk]"] и точные токены
отсекают подстроки; partial требует двух подтверждений. Это не гарантия
акустической точности: она проверяется на телефоне.

Один worker владеет моделью, Recognizer и освобождением AudioRecord. Stop,
pause и close сразу инвалидируют поколение. Callback пробуждения/ошибки и
подтверждение handoff приходят после освобождения записи. UI-запрос ожидает
подтверждение вместо фиксированных 300 ms, отклоняет уже активный диалог и
поздние callbacks старого recognizer. Resume lease привязан к живой instance:
после Stop/destroy он не создаёт новый сервис.

Выключение wake и изменение EventIdentity останавливают запись. Старый
callback не остаётся активным и не начинает разговор в новом аккаунте.
После смены аккаунта требуется явный start/retry. Legacy ambient recorder
и отправка фоновой записи в server STT удалены. Системный SpeechRecognizer
остаётся для пользовательских реплик после wake и ввода с экрана; его разовые
сигналы в ходе разговора не скрываются. Громкость и privacy indicators не меняются.

Русская модель vosk-model-small-ru-0.22 входит в APK: archive SHA-256
`961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4`,
14 файлов, 91,289,240 байт без сжатия. В Gr.fst независимо проверены символы
«тройка» и [unk]. Manifest SHA-256
`5f45cd2377e3523554f20311bd0c18bbb2e9bcefef26b1f0fc98c0754151b236`.
На первом запуске модель атомарно копируется в noBackupFilesDir; SHA проверяются
при установке и загрузке. Повреждённая копия сохраняется отдельно и заменяется.
Audio/text не сохраняются и не передаются движком. Размер и RAM/battery на
Samsung остаются измерением, а не выводом из сборки.

Перед fresh build запускается `hermes-android/tool/prepare_offline_wake.py`.
Official HTTPS downloads, exact byte lengths, AAR/model SHA и per-file manifest
закреплены lock-файлом. Gradle повторно проверяет AAR, manifest и каждый model
file. Большие binaries не входят в Git; модель, Vosk/JNA и Apache notices
входят в APK. Runtime не скачивает модель и не требует ключа.

## Проверки

- 70 pure Kotlin/JUnit tests прошли: прежние 62 и 8 новых lifecycle/matcher.
- 6 provisioning tests прошли: corruption, offline missing, zip traversal/link/
  case collision, modified model и сохранность неизвестного existing AAR.
- Actual engine с Android SDK 36, Vosk/JNA/core скомпилирован без errors/warnings.
- Независимый read-only review замороженных пяти Kotlin sources: открытых
  замечаний нет. Оба arm64 native ELF имеют 16 KB PT_LOAD alignment.
- Полная arm64 release сборка и APK verification прошли. 339 input hashes
  сохранены; модель и лицензии совпадают с frozen input во всех APK members.
- Flutter 299/2 skips, production config 15 и analyze 0 errors/0 warnings
  относятся к предшествующей зелёной сборке. Здесь они не повторялись: Dart/UI
  не менялись. Это отдельно от новой native compilation и 70 JVM tests.

APK: 157558162 байт, SHA-256 `811d234f13730af80d47965f1df1ba0f49c483da8d0730dae64a30887704aecf`. Package
`com.troika.hermes_assistant`, production `https://api.zhulebino-teahouse.ru`,
non-debuggable, прежний signer SHA-256
`848fc21c869cb54698d6040743c01eba7487a726af5a5b681fd5945d5f7a1a91`.
Native Vosk/JNA и offline engine markers проверены.

## Поставка и границы

4 ноября новая APK установлена на Samsung SM-A225F без удаления и сброса.
Установленный SHA совпал; UID 10431, dataDir, current user 0 и первая установка
13 августа сохранены. RECORD_AUDIO=true до и после; разрешения и настройки
оператором не менялись. Прежняя APK сохранена для отката. Владелец подтвердил:
фоновые звуки прекратились, «Тройка» откликается и отвечает.
В 74,8 секунды наблюдения приложение было в фоне, процесс не менялся, ошибок
не было; окно включило пробуждение и диалог, поэтому непрерывные 75 секунд
тишины им не доказаны. Финальный отдельный снимок подтвердил возврат в локальное
ожидание: одна активная запись без системного заглушения VOICE_RECOGNITION, ready=3, wake=2,
dialog=2 и ноль FATAL/permission/unavailable. Содержание речи и raw audio/logs
не сохранялись; голосовой запрос оператором не запускался.

Владелец принял устранение фоновых звуков и пробуждение с ответом; возврат
в локальное ожидание подтверждён отдельным снимком. Это отдельные доказательства
от tests/build. Изолированное ненарушенное 75-секундное окно, locked screen,
полный foreground mic handoff, Stop/выключение wake, смена аккаунта/revoke,
standby/reboot и длительная точность/расход батареи остаются проверками.
Логи с аудио или содержанием речи не сохраняются.

Backend, Windows, account data, API model и естественный голос сервиса этой
задачей не менялись. Прежний WIP команд/презентаций/Telegram/сайта не включается
в commit; APK сохраняет текущий deployed runtime клиента. Доказательства,
snapshots, frozen manifests и receipts — `.git/troika-offline-wake-20261104/`.

Источники зависимостей и условия лицензий:
[официальный Vosk Android demo](https://github.com/alphacep/vosk-android-demo/blob/master/app/build.gradle),
[официальные модели](https://alphacephei.com/vosk/models),
[точный POM Vosk](https://repo.maven.apache.org/maven2/com/alphacephei/vosk-android/0.3.75/vosk-android-0.3.75.pom).
