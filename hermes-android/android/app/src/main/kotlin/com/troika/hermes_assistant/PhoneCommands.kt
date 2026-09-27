package com.troika.hermes_assistant

import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.view.KeyEvent
import android.net.Uri
import android.provider.AlarmClock
import android.provider.MediaStore
import android.provider.Settings
import android.os.Build
import java.math.BigDecimal
import java.util.Calendar

/**
 * Локальный матчер голосовых команд телефона.
 * Возвращает текст-результат для озвучки или null, если команда не распознана.
 * Тогда дальше идёт обычный вызов сетевого агента.
 */
object PhoneCommands {

    // Карта "название по-русски/синонимы" -> package name. Расширяется по мере надобности.
    // Все известные приложения, которые обычно есть на телефонах.
    private val APP_ALIASES: Map<String, List<String>> = mapOf(
        "com.google.android.youtube" to listOf("ютуб", "youtube", "юутб", "ютюб"),
        "org.telegram.messenger" to listOf("телеграм", "telegram", "тг", "telega"),
        "com.whatsapp" to listOf("вотсап", "ватсап", "whatsapp", "whats up", "вацап"),
        "com.instagram.android" to listOf("инстаграм", "инста", "instagram"),
        "com.spotify.music" to listOf("спотифай", "spotify", "спотик"),
        "com.google.android.apps.maps" to listOf("карты", "гугл карты", "google maps", "maps", "map"),
        "com.yandex.yandexmaps" to listOf("яндекс карты", "yandex maps"),
        "com.google.android.gm" to listOf("гмаил", "gmail", "почта", "почту", "почты"),
        "com.android.chrome" to listOf("хром", "chrome", "браузер"),
        "com.sec.android.app.samsungapps" to listOf("галакси стор", "galaxy store"),
        "com.android.vending" to listOf("плей маркет", "google play", "плей", "плэй"),
        "com.google.android.calendar" to listOf("календарь", "calendar"),
        "com.google.android.deskclock" to listOf("часы", "будильник", "clock"),
        "com.sec.android.app.clockpackage" to listOf("часы", "будильник"),
        "com.android.contacts" to listOf("контакты", "contacts"),
        "com.samsung.android.app.contacts" to listOf("контакты"),
        "com.android.dialer" to listOf("телефон", "набор", "звонилка"),
        "com.samsung.android.dialer" to listOf("телефон", "набор", "звонилка"),
        "com.android.mms" to listOf("сообщения", "смс", "sms"),
        "com.samsung.android.messaging" to listOf("сообщения", "смс"),
        "com.google.android.apps.messaging" to listOf("сообщения", "смс"),
        "com.android.settings" to listOf("настройки", "settings"),
        "com.google.android.apps.translate" to listOf("переводчик", "google translate", "translate"),
        "com.yandex.translate" to listOf("яндекс переводчик"),
        "com.google.android.apps.photos" to listOf("фотки", "галерея", "фото", "photos"),
        "com.sec.android.gallery3d" to listOf("галерея", "фотки"),
        "com.android.camera" to listOf("камера", "camera"),
        "com.sec.android.app.camera" to listOf("камера"),
        "ru.sberbankmobile" to listOf("сбер", "сбербанк", "sber"),
        "com.tinkoff.app" to listOf("тинькофф", "тинек"),
        "ru.alfabank.mobile.android" to listOf("альфа", "альфабанк"),
        "ru.vtb24.mobilebanking.android" to listOf("втб"),
        "com.discord" to listOf("дискорд", "discord"),
        "com.zhiliaoapp.musically" to listOf("тикток", "tiktok"),
        "com.facebook.katana" to listOf("фейсбук", "facebook"),
        "com.twitter.android" to listOf("твиттер", "twitter", "x"),
        "com.reddit.frontpage" to listOf("реддит", "reddit"),
        "com.netflix.mediaclient" to listOf("нетфликс", "netflix"),
        "ru.kinopoisk" to listOf("кинопоиск"),
        "com.vkontakte.android" to listOf("вконтакте", "вк", "vk"),
        "com.google.android.apps.bard" to listOf("bard", "gemini", "джемини"),
        "com.openai.chatgpt" to listOf("чат гпт", "chatgpt", "gpt"),
        "com.anthropic.claude" to listOf("клод", "claude"),
    )

    private val OPEN_VERBS = listOf("открой", "открыть", "запусти", "запустить", "включи", "включить", "загрузи", "покажи")
    private val CALL_VERBS = listOf("позвони", "позвонить", "набери", "набрать")
    private val NAVIGATE_VERBS = listOf("проложи маршрут", "построй маршрут", "маршрут", "поехали", "навигация")
    private val SEARCH_VERBS = listOf("найди", "поищи", "загугли", "погугли", "поиск")

    /**
     * Главная точка входа. norm — lowercase-версия фразы (для матчинга), raw — исходник (для подсказок).
     * Возвращает результат или null, если не распознали.
     */
    fun tryExecute(ctx: Context, norm: String, raw: String): String? {
        commonReply(norm)?.let { return it }

        // Открыть приложение
        OPEN_VERBS.firstOrNull { norm.contains(it) }?.let { verb ->
            val rest = norm.substringAfter(verb).trim().trim('.', '!', '?', ',', ' ')
            if (rest.isNotEmpty()) {
                val pkg = findAppPackage(ctx, rest)
                if (pkg != null) {
                    return openApp(ctx, pkg, rest)
                }
                // Не нашли в карте — но даём шанс попробовать через Play Store search
                if (rest.length in 2..30) {
                    val opened = tryLaunchByName(ctx, rest)
                    if (opened != null) return opened
                }
            }
        }

        // Камера открывается без автоматического снимка: кнопку нажимает пользователь.
        if (norm.contains("сделай фото") || norm.contains("сфотографируй")) {
            return openCamera(ctx)
        }

        // Открываем редактор SMS. Отправка остаётся действием пользователя.
        if (norm.contains("напиши смс") || norm.contains("создай сообщение") ||
            norm.contains("новое сообщение")) {
            return openMessageComposer(ctx)
        }

        // Позвонить (открывает dialer с номером/именем)
        CALL_VERBS.firstOrNull { norm.contains(it) }?.let { verb ->
            val rest = norm.substringAfter(verb).trim().trim('.', '!', '?', ',', ' ')
            if (rest.isNotEmpty()) {
                return openDialer(ctx, rest)
            }
        }

        // Будильник: "поставь будильник на 7 утра", "разбуди в 8"
        if (norm.contains("будильник") || norm.matches(Regex(".*разбуди.*в \\d.*"))) {
            return setAlarm(ctx, norm)
        }

        // Таймер: "поставь таймер на 5 минут"
        if (norm.contains("таймер")) {
            return setTimer(ctx, norm)
        }

        // Навигация
        NAVIGATE_VERBS.firstOrNull { norm.contains(it) }?.let { verb ->
            var dest = norm.substringAfter(verb).trim().trim('.', '!', '?', ',', ' ')
            // Срезаем предлоги "в ", "к ", "до " в начале
            for (prep in listOf("до ", "в ", "к ", "на ")) {
                if (dest.startsWith(prep)) {
                    dest = dest.substring(prep.length).trim()
                    break
                }
            }
            if (dest.isNotEmpty()) {
                return openMaps(ctx, dest)
            }
        }

        // Поиск в браузере
        SEARCH_VERBS.firstOrNull { norm.contains(it) }?.let { verb ->
            val q = norm.substringAfter(verb).trim().trim('.', '!', '?', ',', ' ')
            if (q.isNotEmpty() && q.length <= 100) {
                return webSearch(ctx, q)
            }
        }

        // Громкость
        if (norm.contains("громкость") || norm.contains("звук") ||
            norm.contains("громче") || norm.contains("тише") ||
            norm.contains("прибавь") || norm.contains("убавь")) {
            return adjustVolume(ctx, norm)
        }

        // Яркость
        if (norm.contains("яркость") || norm.contains("ярче") ||
            norm.contains("тусклее")) {
            return adjustBrightness(ctx, norm)
        }

        // Bluetooth / Wi-Fi — открываем настройки (прямое включение требует системных прав)
        if (norm.contains("wi-fi") || norm.contains("вайфай") || norm.contains("вай фай") || norm.contains("wifi")) {
            return openSettings(ctx, Settings.ACTION_WIFI_SETTINGS, "настройки Wi-Fi")
        }
        if (norm.contains("блютуз") || norm.contains("bluetooth")) {
            return openSettings(ctx, Settings.ACTION_BLUETOOTH_SETTINGS, "настройки Bluetooth")
        }
        if (norm.contains("режим полета") || norm.contains("режим самолета") ||
            norm.contains("авиарежим")) {
            return openSettings(ctx, Settings.ACTION_AIRPLANE_MODE_SETTINGS, "режим полёта")
        }
        if (norm.contains("мобильная сеть") || norm.contains("мобильные данные")) {
            return openSettings(ctx, Settings.ACTION_DATA_ROAMING_SETTINGS, "мобильную сеть")
        }

        // Фонарик
        if (norm.contains("фонарик") || norm.contains("вспышку")) {
            val on = !(norm.contains("выключ") || norm.contains("погаси"))
            val result = PhoneSystem.torch(ctx, on)
            return if (result.optBoolean("ok")) {
                if (on) "Фонарик включён" else "Фонарик выключен"
            } else {
                "Не удалось переключить фонарик"
            }
        }

        // Состояние устройства
        if (norm.contains("заряд") || norm.contains("батаре")) {
            val result = PhoneSystem.battery(ctx)
            return "Заряд ${result.optInt("level_percent", 0)}%"
        }
        if (norm.contains("какая сеть") ||
            norm.contains("есть интернет") ||
            norm.contains("подключение к интернету")) {
            val result = PhoneSystem.network(ctx)
            if (!result.optBoolean("connected")) return "Сеть не подключена"
            val transport = when (result.optString("transport")) {
                "wifi" -> "Wi-Fi"
                "cellular" -> "мобильная сеть"
                "ethernet" -> "Ethernet"
                "vpn" -> "VPN"
                else -> "сеть"
            }
            return "Подключена $transport"
        }

        // Время и дата
        if (norm.contains("который час") || norm.contains("который сейчас час") ||
            norm.contains("каторый час") || norm.contains("сколько времени")) {
            val now = java.util.Calendar.getInstance()
            return "Сейчас ${"%02d:%02d".format(
                now.get(java.util.Calendar.HOUR_OF_DAY),
                now.get(java.util.Calendar.MINUTE)
            )}"
        }
        if (norm.contains("какая дата") || norm.contains("какое сегодня число")) {
            val now = java.util.Calendar.getInstance()
            return "Сегодня ${"%02d.%02d.%04d".format(
                now.get(java.util.Calendar.DAY_OF_MONTH),
                now.get(java.util.Calendar.MONTH) + 1,
                now.get(java.util.Calendar.YEAR)
            )}"
        }

        // Управление медиаплеером через стандартные media keys.
        if (norm.contains("пауза") || norm.contains("продолжи музыку") ||
            norm.contains("возобнови музыку") || norm.contains("включи музыку") ||
            norm.contains("останови музыку")) {
            dispatchMediaKey(ctx, KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE)
            return "Готово"
        }
        if (norm.contains("следующий трек") || norm.contains("следующая песня")) {
            dispatchMediaKey(ctx, KeyEvent.KEYCODE_MEDIA_NEXT)
            return "Следующий трек"
        }
        if (norm.contains("предыдущий трек") || norm.contains("предыдущая песня")) {
            dispatchMediaKey(ctx, KeyEvent.KEYCODE_MEDIA_PREVIOUS)
            return "Предыдущий трек"
        }

        // Системная навигация. Требует отдельно включённый AccessibilityService.
        if (norm == "назад" || norm.contains("вернись назад")) {
            return accessibilityResult("Назад") { it.pressBack() }
        }
        if (norm == "домой" || norm.contains("на главный экран")) {
            return accessibilityResult("Открываю главный экран") { it.pressHome() }
        }
        if (norm.contains("последние приложения") || norm.contains("недавние приложения")) {
            return accessibilityResult("Открываю недавние приложения") { it.pressRecents() }
        }
        if (norm.contains("покажи уведомления") || norm.contains("открой уведомления")) {
            return accessibilityResult("Открываю уведомления") { it.openNotifications() }
        }
        if (norm.contains("прокрути вверх") || norm.contains("листай вверх")) {
            return accessibilityResult("Прокручиваю вверх") { it.swipe("down") }
        }
        if (norm.contains("прокрути вниз") || norm.contains("листай вниз")) {
            return accessibilityResult("Прокручиваю вниз") { it.swipe("up") }
        }

        // Часто используемые разделы настроек.
        val settingsTarget = when {
            norm.contains("настройки звука") -> Settings.ACTION_SOUND_SETTINGS to "настройки звука"
            norm.contains("настройки экрана") -> Settings.ACTION_DISPLAY_SETTINGS to "настройки экрана"
            norm.contains("настройки батареи") -> Settings.ACTION_BATTERY_SAVER_SETTINGS to "настройки батареи"
            norm.contains("настройки приложений") -> Settings.ACTION_APPLICATION_SETTINGS to "настройки приложений"
            norm.contains("настройки уведомлений") ->
                "android.settings.NOTIFICATION_SETTINGS" to "настройки уведомлений"
            norm.contains("настройки геолокации") || norm.contains("настройки местоположения") ->
                Settings.ACTION_LOCATION_SOURCE_SETTINGS to "настройки геолокации"
            norm.contains("специальные возможности") ->
                Settings.ACTION_ACCESSIBILITY_SETTINGS to "специальные возможности"
            else -> null
        }
        if (settingsTarget != null) {
            return openSettings(ctx, settingsTarget.first, settingsTarget.second)
        }

        return null
    }

    /**
     * Короткие ответы, которые должны работать без сервера и из фонового
     * voice-сервиса. Набор намеренно совпадает с Flutter local matcher.
     */
    private fun commonReply(input: String): String? {
        val normalized = withoutAssistantAddress(normalizeCommon(input))

        if (normalized in setOf(
                "привет", "приветик", "здравствуй", "здравствуйте",
                "доброе утро", "добрый день", "добрый вечер",
            )) {
            return "Привет! Я рядом. Что сделать?"
        }
        if (normalized in setOf(
                "пока", "до свидания", "до встречи", "увидимся", "спокойной ночи",
            )) {
            return "Пока! Позови, когда понадоблюсь."
        }
        if (normalized in setOf(
                "спасибо", "благодарю", "спасибо большое", "большое спасибо",
            )) {
            return "Пожалуйста."
        }
        if (normalized in setOf(
                "как дела", "как ты", "ты тут", "ты здесь", "ты работаешь",
            )) {
            return "Я на связи и готова помочь."
        }
        if (normalized in setOf("кто ты", "как тебя зовут", "представься")) {
            return "Я Тройка, твой локальный голосовой помощник."
        }
        if (normalized in setOf(
                "помощь", "помоги", "команды", "список команд", "покажи команды",
                "что ты умеешь", "что я могу сказать",
            )) {
            return "Без интернета умею отвечать на простые фразы, считать, " +
                "называть время и дату, открывать приложения, искать в браузере, " +
                "строить маршрут, ставить таймер и будильник, управлять фонариком, " +
                "звуком, яркостью и музыкой. Например: включи фонарик."
        }
        if (normalized.contains("день недели") ||
            normalized == "какой сегодня день" ||
            normalized == "сегодня какой день") {
            val weekdays = listOf(
                "воскресенье", "понедельник", "вторник", "среда",
                "четверг", "пятница", "суббота",
            )
            val day = Calendar.getInstance().get(Calendar.DAY_OF_WEEK) - 1
            return "Сегодня ${weekdays[day]}"
        }

        return calculateReply(normalized)
    }

    private fun calculateReply(normalized: String): String? {
        val match = Regex(
            "^(?:сколько будет|посчитай|вычисли|рассчитай)\\s+" +
                "(-?\\d+(?:\\.\\d+)?)\\s*" +
                "(плюс|минус|умножить на|умножь на|делить на|разделить на|[+\\-*/xх])\\s*" +
                "(-?\\d+(?:\\.\\d+)?)$",
        ).find(normalized) ?: return null
        val left = match.groupValues[1].toDouble()
        val operator = match.groupValues[2]
        val right = match.groupValues[3].toDouble()
        if (operator in setOf("/", "делить на", "разделить на") && right == 0.0) {
            return "На ноль делить нельзя."
        }
        val value = when (operator) {
            "плюс", "+" -> left + right
            "минус", "-" -> left - right
            "умножить на", "умножь на", "*", "x", "х" -> left * right
            else -> left / right
        }
        val answer = BigDecimal.valueOf(value).stripTrailingZeros().toPlainString()
        return "Ответ: $answer"
    }

    private fun normalizeCommon(input: String): String {
        return input
            .lowercase()
            .replace('ё', 'е')
            .replace(Regex("(\\d),(\\d)")) { match ->
                "${match.groupValues[1]}.${match.groupValues[2]}"
            }
            .replace(Regex("[^a-zа-я0-9:+*/\\-.\\s]"), " ")
            .replace(Regex("\\s+"), " ")
            .trim()
    }

    private fun withoutAssistantAddress(input: String): String {
        var value = input
        for (prefix in listOf("эй тройка ", "слушай тройка ", "тройка ")) {
            if (value.startsWith(prefix)) {
                value = value.removePrefix(prefix).trim()
                break
            }
        }
        if (value.endsWith(" тройка")) {
            value = value.removeSuffix(" тройка").trim()
        }
        return value
    }

    private fun dispatchMediaKey(ctx: Context, keyCode: Int) {
        val audio = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        audio.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, keyCode))
        audio.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_UP, keyCode))
    }

    private inline fun accessibilityResult(
        successText: String,
        action: (HermesAccessibilityService) -> org.json.JSONObject,
    ): String {
        val service = HermesAccessibilityService.instance
            ?: return "Включи Тройку в разделе специальных возможностей"
        return if (action(service).optBoolean("ok")) successText
        else "Не удалось выполнить действие"
    }

    private fun findAppPackage(ctx: Context, query: String): String? {
        val q = query.lowercase()
        val matches = mutableListOf<String>()
        for ((pkg, aliases) in APP_ALIASES) {
            if (aliases.any { alias -> q == alias || q.contains(alias) || alias.contains(q) }) {
                matches.add(pkg)
            }
        }
        return matches.firstOrNull { ctx.packageManager.getLaunchIntentForPackage(it) != null }
            ?: matches.firstOrNull()
    }

    private fun openCamera(ctx: Context): String {
        val intent = Intent(MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        return if (intent.resolveActivity(ctx.packageManager) != null) {
            ctx.startActivity(intent)
            "Открываю камеру. Снимок сделаешь ты."
        } else {
            "Камера недоступна"
        }
    }

    private fun openMessageComposer(ctx: Context): String {
        val intent = Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:")).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        return if (intent.resolveActivity(ctx.packageManager) != null) {
            ctx.startActivity(intent)
            "Открываю новое сообщение. Отправка только вручную."
        } else {
            "Приложение сообщений недоступно"
        }
    }

    private fun openApp(ctx: Context, pkg: String, name: String): String {
        val pm = ctx.packageManager
        val intent = pm.getLaunchIntentForPackage(pkg)
        return if (intent != null) {
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            ctx.startActivity(intent)
            "Открываю"
        } else {
            "Приложение $name не установлено"
        }
    }

    /** Пробуем найти приложение по части имени через PackageManager (без алиаса) */
    private fun tryLaunchByName(ctx: Context, query: String): String? {
        val pm = ctx.packageManager
        val launcher = Intent(Intent.ACTION_MAIN).apply { addCategory(Intent.CATEGORY_LAUNCHER) }
        val apps = try { pm.queryIntentActivities(launcher, 0) } catch (e: Exception) { return null }
        val q = query.lowercase()
        for (info in apps) {
            val label = info.loadLabel(pm).toString().lowercase()
            if (label == q || label.contains(q) || q.contains(label)) {
                val pkg = info.activityInfo.packageName
                val intent = pm.getLaunchIntentForPackage(pkg) ?: continue
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                ctx.startActivity(intent)
                return "Открываю"
            }
        }
        return null
    }

    private fun openDialer(ctx: Context, target: String): String {
        // Пытаемся извлечь только цифры из фразы
        val digits = target.filter { it.isDigit() || it == '+' }
        val uri = if (digits.length >= 5) Uri.parse("tel:$digits") else Uri.parse("tel:")
        val intent = Intent(Intent.ACTION_DIAL, uri).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        ctx.startActivity(intent)
        return if (digits.length >= 5) "Набираю $digits" else "Открываю набор номера"
    }

    private fun setAlarm(ctx: Context, phrase: String): String {
        // Парсим "на 7 утра", "в 7:30", "в 8 часов"
        val timeMatch = Regex("(\\d{1,2})[:\\.]?(\\d{0,2})").find(phrase)
        if (timeMatch == null) {
            // Просто открываем приложение часов
            val i = Intent(AlarmClock.ACTION_SHOW_ALARMS).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            ctx.startActivity(i)
            return "Открыл будильники"
        }
        var hour = timeMatch.groupValues[1].toInt()
        val minute = timeMatch.groupValues[2].toIntOrNull() ?: 0
        // Утро/вечер
        if (phrase.contains("вечера") || phrase.contains("вечером")) {
            if (hour < 12) hour += 12
        }
        // Полночь = 0
        if (hour == 24) hour = 0

        val i = Intent(AlarmClock.ACTION_SET_ALARM).apply {
            putExtra(AlarmClock.EXTRA_HOUR, hour)
            putExtra(AlarmClock.EXTRA_MINUTES, minute)
            putExtra(AlarmClock.EXTRA_SKIP_UI, true)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        ctx.startActivity(i)
        return "Будильник на ${"%02d:%02d".format(hour, minute)}"
    }

    private fun setTimer(ctx: Context, phrase: String): String {
        // "на 5 минут", "5 секунд", "1 час"
        val m = Regex("(\\d+)\\s*(минут|секунд|час|сек|мин)").find(phrase)
        if (m == null) {
            val i = Intent(AlarmClock.ACTION_SET_TIMER).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }
            ctx.startActivity(i)
            return "Открыл таймер"
        }
        val value = m.groupValues[1].toInt()
        val unit = m.groupValues[2]
        val seconds = when {
            unit.startsWith("час") -> value * 3600
            unit.startsWith("мин") -> value * 60
            else -> value
        }
        val i = Intent(AlarmClock.ACTION_SET_TIMER).apply {
            putExtra(AlarmClock.EXTRA_LENGTH, seconds)
            putExtra(AlarmClock.EXTRA_SKIP_UI, true)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        ctx.startActivity(i)
        return "Таймер на $value $unit"
    }

    private fun openMaps(ctx: Context, destination: String): String {
        val uri = Uri.parse("google.navigation:q=${Uri.encode(destination)}")
        val intent = Intent(Intent.ACTION_VIEW, uri).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        ctx.startActivity(intent)
        return "Прокладываю маршрут до $destination"
    }

    private fun webSearch(ctx: Context, query: String): String {
        val uri = Uri.parse("https://www.google.com/search?q=${Uri.encode(query)}")
        val intent = Intent(Intent.ACTION_VIEW, uri).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        ctx.startActivity(intent)
        return "Ищу: $query"
    }

    private fun adjustVolume(ctx: Context, phrase: String): String {
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val max = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
        val current = am.getStreamVolume(AudioManager.STREAM_MUSIC)
        val newVol = when {
            phrase.contains("макс") || phrase.contains("полная") -> max
            phrase.contains("тишина") || phrase.contains("выключи") ||
                phrase.contains("без звука") || phrase.contains("убери звук") ||
                phrase.contains("ноль") -> 0
            phrase.contains("тише") || phrase.contains("убавь") || phrase.contains("уменьши") -> (current - max / 5).coerceAtLeast(0)
            phrase.contains("громче") || phrase.contains("прибавь") || phrase.contains("увеличь") -> (current + max / 5).coerceAtMost(max)
            else -> {
                // "поставь громкость 50" - процент
                val pct = Regex("(\\d{1,3})").find(phrase)?.groupValues?.get(1)?.toIntOrNull()
                if (pct != null) (max * pct / 100).coerceIn(0, max) else return "Не понял уровень громкости"
            }
        }
        am.setStreamVolume(AudioManager.STREAM_MUSIC, newVol, AudioManager.FLAG_SHOW_UI)
        return "Громкость ${newVol * 100 / max}%"
    }

    private fun adjustBrightness(ctx: Context, phrase: String): String {
        // Прямое изменение яркости требует WRITE_SETTINGS — открываем экран настроек если нет прав
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.System.canWrite(ctx)) {
            val i = Intent(Settings.ACTION_MANAGE_WRITE_SETTINGS).apply {
                data = Uri.parse("package:${ctx.packageName}")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            ctx.startActivity(i)
            return "Дай разрешение на изменение яркости в настройках"
        }
        val cr = ctx.contentResolver
        val current = try {
            Settings.System.getInt(cr, Settings.System.SCREEN_BRIGHTNESS)
        } catch (e: Exception) { 128 }
        val target = when {
            phrase.contains("макс") -> 255
            phrase.contains("мин") -> 10
            phrase.contains("ярче") || phrase.contains("прибавь") -> (current + 50).coerceAtMost(255)
            phrase.contains("тусклее") || phrase.contains("убавь") -> (current - 50).coerceAtLeast(0)
            else -> {
                val pct = Regex("(\\d{1,3})").find(phrase)?.groupValues?.get(1)?.toIntOrNull()
                if (pct != null) (255 * pct / 100).coerceIn(0, 255) else return "Не понял уровень яркости"
            }
        }
        Settings.System.putInt(cr, Settings.System.SCREEN_BRIGHTNESS, target)
        return "Яркость ${target * 100 / 255}%"
    }

    private fun openSettings(ctx: Context, action: String, label: String): String {
        val i = Intent(action).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }
        ctx.startActivity(i)
        return "Открываю $label"
    }
}
