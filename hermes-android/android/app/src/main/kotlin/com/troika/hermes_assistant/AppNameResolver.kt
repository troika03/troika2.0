package com.troika.hermes_assistant

import java.util.Locale

/** Shared names for local and server-issued app launches. No fuzzy first match. */
object AppNameResolver {
    val aliases: Map<String, List<String>> = mapOf(
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

    private fun normalize(value: String) = value.trim().lowercase(Locale.ROOT).replace(Regex("\\s+"), " ")

    fun resolve(query: String, apps: List<Pair<String, String>>, canLaunch: (String) -> Boolean): String? {
        val q = normalize(query)
        if (q.isBlank()) return null
        if (canLaunch(q)) return q
        val named = aliases.filterValues { names -> names.any { normalize(it) == q } }.keys
        named.firstOrNull(canLaunch)?.let { return it }
        val available = apps.filter { canLaunch(it.first) }.distinctBy { it.first }
        val exact = available.filter { normalize(it.second) == q }
        if (exact.isNotEmpty()) return exact.singleOrNull()?.first
        if (q.length < 3) return null
        // A partial title must identify exactly one installed launcher app.
        return available.filter { normalize(it.second).contains(q) }.singleOrNull()?.first
    }
}
