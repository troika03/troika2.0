# Повседневные исправления клиента — 29 октября 2026

Основная Тройка обновлена поверх прежней установки с сохранением данных.
Передача файлов и история сохраняют исходный аккаунт, а прерванный ответ больше
не превращается в успешный результат. Естественный голос и бесплатная модель
не менялись. Новая физическая проверка разговора и напоминания ещё открыта.

## Что исправлено

- Файл, список, download и ACK сохраняют одну identity через ожидания сети и
  локального хранилища. Redirects запрещены, ответы ограничены по размеру.
  Старый file handle и поздний UI callback не действуют в новой identity.
- При повторной передаче проверенная локальная копия получает валидные metadata
  до подтверждения серверу, включая отсутствующие или повреждённые metadata.
  Конфликтующая передача не перезаписывает сохранённый оригинал. Offline чтение
  локальных файлов сохраняется; прежние account directories не мигрировались.
- Запоздалая история не затирает новый turn или более новый snapshot. Смена
  аккаунта очищает ленту, последний текст, результат и pending UI context.
  Сохранённые result cards разделены по origin и владельцу; для local режима
  используется session. Старый unscoped result остаётся на устройстве непрочитанным.
- Частичный текст при run.failed/cancelled и незавершённый EOF не дают успех.
  Восстановление ответа требует completed status и canonical output. Terminal
  completion заканчивает чтение; history/run/status redirects запрещены.
- Timezone sync сохраняет identity до и после GET/PUT, ограничивает preferences
  JSON до 64 KiB и HTTP exchange до 15 с. Отказ не выдаёт успех в новом аккаунте.
- Native диалог захватывает event identity атомарно. Четыре voice-message sends
  проверяют её до постановки в очередь и внутри main-loop callback; Dart проверяет
  metadata и listener epoch после reload preferences. Отложенный старый текст не
  попадает в другой аккаунт. Access/refresh credential в событие не передаются.
  Local/manual gateway пути сохранены; перед phone command повторяется guard.

## Проверки и поставка

| Проверка | Результат |
|---|---|
| Новые file cases на исходном FilesService | 3 passed/7 failed; два отказа также достигли неполного path-provider fixture |
| Первый целевой повтор после file patch | 10 passed |
| Первый полный Flutter набор | 265 passed/2 skipped |
| Окончательный полный Flutter набор | 282 passed/2 skipped |
| Окончательный analyze | 0 errors, 0 warnings, 61 info |
| Release plugin generation | Passed; integration plugin не зарегистрирован |
| Окончательный assembleRelease | Passed |
| URL, release mode, прежний signer, новые Dart/DEX markers | Проверены в APK |
| Main package update | Exact SHA совпал; firstInstallTime/dataDir сохранены |
| Запуск основного приложения | Status ok; процесс продолжает работать |

Первый APK 29 октября прошёл сборку, но не устанавливался: независимое review
нашло старую native-event утечку. После исправления полный набор повторён и
окончательный APK собран в том же каталоге. Проверки не ослаблялись; прежние
fixtures получили явный completed event/status для успешного сценария.
Реальные MethodChannel tests проверяют задержанные события, смену identity,
Stop/restart, token rotation и совместимость local/manual gateway.

Текущая APK: `com.troika.hermes_assistant`, 81,456,991 байт.
SHA-256: `0cac9025674c33a8d1535301672505f55256c4b136afd8e3414c8835d9293048`.
Сертификат: `848fc21c869cb54698d6040743c01eba7487a726af5a5b681fd5945d5f7a1a91`.
Предыдущая APK 28 октября `b044d2cc…6495` сохранена для отката.
Uninstall, clear data и автоматическая выдача разрешений не выполнялись.
Запуск приложения не является измерением голосовой задержки.

## Границы результата и очередь

Владелец подтвердил фоновый голос на предыдущей основной APK 28 октября. Новый
APK требует физической проверки звука, reminder, Stop, standby/reboot и реальных
expiry/revoke. Стабильный полный ответ за 1–2 с не доказан. 38 тестов JVM прошли
предыдущую поставку; их исходники здесь не менялись. Новый native adapter
скомпилирован Android release; весь Python baseline остаётся прежним красным.

Backend, deployment, ключи, модель и server data этой поставкой не менялись.
Доставка с другого устройства без нового snapshot и новый push не добавлены.
Source audit обнаружил оставшиеся reminder gaps: quiet hours не перепроверяются
при фактической поздней доставке; DST scan на 1441 минуту не имеет финального
allows_delivery postcondition; полная замена preferences может потерять
одновременную правку другого устройства. Эти gaps этим APK не закрыты.

Импорт non-image вложений/RAM extraction, полный Office edit/version, история и
offline на двух физических устройствах, development resume, production backups/
restore/monitoring и safe update gates остаются следующими задачами. Billing и
SMTP отложены владельцем. Это завершённая клиентская поставка, не закрытие всех
разделов 1–20. Один checkout и прежний каталог сборки; посторонний WIP сохранён.
