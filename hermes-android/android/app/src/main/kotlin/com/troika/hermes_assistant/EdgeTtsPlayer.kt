package com.troika.hermes_assistant

import android.content.Context
import android.media.MediaDataSource
import android.media.MediaPlayer
import android.util.Log
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.CompletableFuture
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

/**
 * Воспроизведение голоса через серверный Edge TTS вместо локального Android TTS.
 *
 * Скачивает MP3 с сервера и играет из памяти через MediaPlayer.
 * Ответы пользователя и синтезированное аудио на диск не записываются.
 */
class EdgeTtsPlayer(
    private val ctx: Context,
    private val serverUrl: String,
    private val apiKey: String,
    private val voice: String = "ru-RU-SvetlanaNeural",
    private val rate: Double = 1.0,     // 0.5..1.5x — скорость речи
    private val pitch: Int = 0,         // -50..+50 Hz — тон (выше = женственнее)
    private val volume: Int = 0,        // -100..+100% — громкость
) {
    private val tag = "EdgeTts"
    private val player = AtomicReference<MediaPlayer?>(null)
    private val currentSource = AtomicReference<MediaDataSource?>(null)
    private val legacyCacheDir = File(ctx.cacheDir, "edge_tts")
    private val currentDoneCallback = AtomicReference<(() -> Unit)?>(null)
    private val streamCancelled = AtomicBoolean(false)

    // Эмоция текущей озвучки. Мозг ставит [emo:joy] в начале ПОЛНОГО ответа;
    // мы вырезаем тег один раз и прикладываем тон ко ВСЕМ предложениям этого
    // ответа, чтобы вся фраза звучала единым настроением (а не только первая).
    private val currentTone = AtomicReference<String?>(null)

    init {
        // Remove audio left by builds that used the old persistent TTS cache.
        try { legacyCacheDir.deleteRecursively() } catch (_: Exception) {}
    }

    private val emoTagRe = Regex("""\[emo:\s*([A-Za-zА-Яа-яЁё_]+)\s*]""")

    /** Достаёт [emo:...] из полного текста, ставит currentTone, возвращает текст без тега. */
    private fun extractTone(text: String): String {
        val m = emoTagRe.find(text)
        if (m == null) { currentTone.set(null); return text }
        currentTone.set(m.groupValues[1].trim().lowercase())
        return emoTagRe.replace(text, "").trim()
    }

    // «Поколение» текущей озвучки. Любой новый speak()/speakStream() инкрементит
    // его и глушит предыдущую речь. Потоки синтеза/проигрывания сверяют своё
    // поколение с актуальным — если устарело, тихо выходят и НЕ запускают звук.
    // Это убирает наложение нескольких голосов при быстрых повторных вызовах.
    private val generation = AtomicInteger(0)

    /**
     * Начать новую озвучку: глушит предыдущую (stop текущего плеера + отмена
     * стрима + отстрел старого onDone) и возвращает номер своего поколения.
     * Дальше каждый шаг проверяет generation.get() == myGen.
     */
    private fun beginPlayback(onDone: (() -> Unit)?): Int {
        val myGen = generation.incrementAndGet()
        // Прервать предыдущую речь, не трогая НАШ ещё-не-установленный колбэк.
        streamCancelled.set(true)
        try {
            player.getAndSet(null)?.let {
                try { if (it.isPlaying) it.stop() } catch (_: Exception) {}
                try { it.release() } catch (_: Exception) {}
            }
            try { currentSource.getAndSet(null)?.close() } catch (_: Exception) {}
        } catch (_: Exception) {}
        // Отстрелить колбэк прошлой озвучки (если был), чтобы её ожидающий
        // проснулся и не завис.
        currentDoneCallback.getAndSet(null)?.let {
            try { it() } catch (_: Exception) {}
        }
        // Теперь это наша озвучка.
        streamCancelled.set(false)
        currentDoneCallback.set(onDone)
        return myGen
    }

    /** Синхронно скачивает MP3 и проигрывает; колбэк вызывается когда озвучка закончилась. */
    fun speak(text: String, onDone: (() -> Unit)? = null) {
        val cleaned = extractTone(text.replace(Regex("[*#`]+"), "").trim())
        if (cleaned.isEmpty()) { onDone?.invoke(); return }
        speakResolved(cleaned, currentTone.get(), onDone)
    }

    /** Озвучить уже очищенный текст с явным тоном (тег уже вырезан). */
    private fun speakResolved(cleaned: String, tone: String?, onDone: (() -> Unit)?) {
        val myGen = beginPlayback(onDone)

        val t = Thread {
            try {
                val audio = synthesize(cleaned, tone)
                if (generation.get() != myGen) return@Thread  // нас перебили — молчим
                if (audio != null && audio.isNotEmpty()) {
                    playBytes(audio, myGen)
                } else {
                    Log.w(tag, "synth returned empty, fallback to silence")
                    invokeDoneOnce(myGen)
                }
            } catch (e: Exception) {
                Log.e(tag, "speak error: ${e.message}", e)
                invokeDoneOnce(myGen)
            }
        }
        t.name = "EdgeTtsFetch"
        t.start()
    }

    /** Прервать текущее воспроизведение. Вызовет onDone из текущего speak(), если он ещё не отстрелял. */
    fun stop() {
        // Инкремент поколения — любой in-flight синтез/проигрывание увидит, что
        // устарел, и не запустит звук.
        generation.incrementAndGet()
        streamCancelled.set(true)
        try {
            player.getAndSet(null)?.let {
                try { if (it.isPlaying) it.stop() } catch (_: Exception) {}
                it.release()
            }
            try { currentSource.getAndSet(null)?.close() } catch (_: Exception) {}
        } catch (_: Exception) {}
        // Отстрелить колбэк текущей озвучки (кто ждёт — проснётся).
        currentDoneCallback.getAndSet(null)?.let {
            try { it() } catch (e: Exception) { Log.e(tag, "stop onDone: ${e.message}") }
        }
    }

    /**
     * Stream-вариант speak: разбивает текст на предложения, синтезирует первое
     * сразу, воспроизводит, в фоне параллельно синтезирует следующие. Время до
     * первого звука падает с 2-3 сек (на длинном ответе) до ~500 мс.
     *
     * onDone вызывается ровно один раз — когда последнее предложение доиграло
     * или когда поток был прерван через stop().
     */
    fun speakStream(text: String, onDone: (() -> Unit)? = null) {
        // Тег [emo:...] вырезаем из ПОЛНОГО ответа один раз — currentTone теперь
        // действует на все предложения этой озвучки.
        val cleaned = extractTone(text.replace(Regex("[*#`]+"), "").trim())
        if (cleaned.isEmpty()) { onDone?.invoke(); return }

        val tone = currentTone.get()
        val sentences = splitSentences(cleaned)
        if (sentences.size <= 1) {
            speakResolved(cleaned, tone, onDone)
            return
        }

        val myGen = beginPlayback(onDone)

        // УПРЕЖДАЮЩИЙ ПАРАЛЛЕЛЬНЫЙ СИНТЕЗ.
        // Раньше предложения синтезировались строго по очереди — если синтез
        // медленнее проигрывания, между фразами появлялась дыра тишины.
        // Теперь синтезируем сразу несколько фраз вперёд (look-ahead), но играем
        // строго по порядку: для каждого предложения заводим Future-«слот», а
        // воркеры из пула заполняют их параллельно. Консьюмер просто ждёт слот N,
        // пока N+1, N+2 уже качаются. Порядок речи сохраняется, тишина исчезает.
        val n = sentences.size
        @Suppress("UNCHECKED_CAST")
        val slots = arrayOfNulls<CompletableFuture<ByteArray?>>(n) as Array<CompletableFuture<ByteArray?>>
        for (i in 0 until n) slots[i] = CompletableFuture()

        // Сколько фраз держим «в полёте» одновременно. 3 — компромисс: убирает
        // дыры даже на медленной сети, но не штурмует сервер десятком запросов.
        val lookahead = minOf(3, n)
        val pool = Executors.newFixedThreadPool(lookahead) { r ->
            Thread(r, "EdgeTtsSynth").apply { isDaemon = true }
        }
        val nextIndex = AtomicInteger(0)

        fun pump() {
            // Каждый воркер берёт следующий невзятый индекс, синтезирует, кладёт в слот,
            // затем берёт ещё один — пока предложения не кончатся или поток не отменён.
            while (true) {
                if (streamCancelled.get() || generation.get() != myGen) return
                val i = nextIndex.getAndIncrement()
                if (i >= n) return
                val audio: ByteArray? = try {
                    synthesize(sentences[i], tone)
                } catch (e: Exception) {
                    Log.e(tag, "stream synth #$i: ${e.message}"); null
                }
                slots[i].complete(audio)
            }
        }
        repeat(lookahead) { pool.submit { pump() } }

        // Консьюмер: играем слоты строго по порядку. Слот N может быть ещё не готов —
        // ждём его get(), пока следующие уже синтезируются параллельно.
        Thread {
            try {
                for (i in 0 until n) {
                    if (streamCancelled.get() || generation.get() != myGen) break
                    val audio = try {
                        slots[i].get(60, TimeUnit.SECONDS)
                    } catch (e: Exception) {
                        Log.e(tag, "stream slot #$i wait: ${e.message}"); null
                    }
                    if (streamCancelled.get() || generation.get() != myGen) break
                    if (audio != null && audio.isNotEmpty()) {
                        playBytesBlocking(audio, myGen)
                    } else {
                        Log.w(tag, "stream: empty audio for sentence #$i")
                    }
                }
            } catch (e: Exception) {
                Log.e(tag, "stream play: ${e.message}")
            } finally {
                pool.shutdownNow()
                invokeDoneOnce(myGen)
            }
        }.apply { name = "EdgeTtsStreamPlay"; isDaemon = true }.start()
    }

    /**
     * Разбивает на предложения по . ! ? \n. Короткие хвосты склеиваются с
     * предыдущим (минимальная длина куска 25 символов), чтобы не было
     * разрывов на каждой запятой и не платить за лишние TTS-вызовы.
     */
    private fun splitSentences(text: String): List<String> {
        val raw = text.split(Regex("(?<=[.!?\\n])\\s+"))
            .map { it.trim() }
            .filter { it.isNotEmpty() }
        if (raw.size <= 1) return raw

        val merged = mutableListOf<String>()
        val acc = StringBuilder()
        for (s in raw) {
            if (acc.isEmpty()) {
                acc.append(s)
            } else if (acc.length < 25) {
                acc.append(' ').append(s)
            } else {
                merged.add(acc.toString())
                acc.clear()
                acc.append(s)
            }
        }
        if (acc.isNotEmpty()) merged.add(acc.toString())
        return merged
    }

    /** Синхронное проигрывание аудио из памяти — блокирует до завершения. */
    private fun playBytesBlocking(audio: ByteArray, myGen: Int) {
        if (generation.get() != myGen) return  // нас перебили до старта
        val done = Object()
        val mp = MediaPlayer()
        val source = ByteArraySource(audio)
        try {
            val attrs = android.media.AudioAttributes.Builder()
                .setUsage(android.media.AudioAttributes.USAGE_ASSISTANT)
                .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SPEECH)
                .build()
            mp.setAudioAttributes(attrs)
            mp.setDataSource(source)
            mp.setOnCompletionListener {
                try { source.close() } catch (_: Exception) {}
                currentSource.compareAndSet(source, null)
                try { it.release() } catch (_: Exception) {}
                player.compareAndSet(it, null)
                synchronized(done) { done.notify() }
            }
            mp.setOnErrorListener { p, what, extra ->
                Log.e(tag, "MediaPlayer error: $what/$extra")
                try { source.close() } catch (_: Exception) {}
                currentSource.compareAndSet(source, null)
                try { p.release() } catch (_: Exception) {}
                player.compareAndSet(p, null)
                synchronized(done) { done.notify() }
                true
            }
            mp.prepare()
            // Финальная проверка: если за время prepare() нас перебили — не играем.
            if (generation.get() != myGen) {
                try { source.close() } catch (_: Exception) {}
                try { mp.release() } catch (_: Exception) {}
                return
            }
            player.set(mp)
            currentSource.set(source)
            mp.setVolume(1.0f, 1.0f)
            mp.start()
            synchronized(done) {
                val deadline = System.currentTimeMillis() + 120_000L
                while (generation.get() == myGen && player.get() === mp) {
                    val remaining = deadline - System.currentTimeMillis()
                    if (remaining <= 0L) break
                    try { done.wait(minOf(250L, remaining)) } catch (_: Exception) { break }
                }
            }
        } catch (e: Exception) {
            Log.e(tag, "playBlocking error: ${e.message}")
            try { source.close() } catch (_: Exception) {}
            try { mp.release() } catch (_: Exception) {}
        }
    }

    private fun invokeDoneOnce(myGen: Int) {
        // Колбэк отстреливаем только если мы всё ещё актуальная озвучка —
        // иначе beginPlayback() уже вызвал onDone предыдущего поколения.
        if (generation.get() != myGen) return
        val cb = currentDoneCallback.getAndSet(null) ?: return
        try { cb() } catch (e: Exception) { Log.e(tag, "onDone error: ${e.message}") }
    }

    private fun synthesize(text: String, tone: String? = null): ByteArray? {
        val url = "$serverUrl/v1/audio/speech"
        val body = JSONObject().apply {
            put("input", text)
            put("voice", voice)
            put("speed", rate)
            put("pitch", pitch)
            put("volume", volume)
            if (!tone.isNullOrBlank()) put("tone", tone)
        }.toString().toByteArray(Charsets.UTF_8)

        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            connectTimeout = 8000
            readTimeout = 60000
            setRequestProperty("Authorization", "Bearer $apiKey")
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("Accept", "audio/mpeg")
        }
        try {
            conn.outputStream.use { it.write(body) }

            if (conn.responseCode != 200) {
                Log.e(tag, "TTS HTTP ${conn.responseCode}")
                return null
            }

            val output = ByteArrayOutputStream()
            val buffer = ByteArray(8192)
            conn.inputStream.use { input ->
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    if (output.size() + count > MAX_AUDIO_BYTES) {
                        throw IllegalStateException("TTS response too large")
                    }
                    output.write(buffer, 0, count)
                }
            }
            return output.toByteArray()
        } finally {
            conn.disconnect()
        }
    }

    private fun playBytes(audio: ByteArray, myGen: Int) {
        if (generation.get() != myGen) return  // нас перебили до старта
        val mp = MediaPlayer()
        val source = ByteArraySource(audio)
        try {
            // КРИТИЧНО: на Android 11+ без AudioAttributes MediaPlayer может играть тихо
            // или быть подавлен системой если другое app держит audio focus.
            // USAGE_VOICE_COMMUNICATION + CONTENT_TYPE_SPEECH = Тройка обрабатывается
            // как голосовое сообщение, играет даже когда телефон в режиме ringer/silent
            // и громкость media низкая (использует voice-call volume canal).
            val attrs = android.media.AudioAttributes.Builder()
                .setUsage(android.media.AudioAttributes.USAGE_ASSISTANT)
                .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SPEECH)
                .build()
            mp.setAudioAttributes(attrs)
            mp.setDataSource(source)
            mp.setOnCompletionListener {
                try { source.close() } catch (_: Exception) {}
                currentSource.compareAndSet(source, null)
                try { it.release() } catch (_: Exception) {}
                player.compareAndSet(it, null)
                invokeDoneOnce(myGen)
            }
            mp.setOnErrorListener { p, what, extra ->
                Log.e(tag, "MediaPlayer error: $what/$extra")
                try { source.close() } catch (_: Exception) {}
                currentSource.compareAndSet(source, null)
                try { p.release() } catch (_: Exception) {}
                player.compareAndSet(p, null)
                invokeDoneOnce(myGen)
                true
            }
            mp.setOnPreparedListener {
                it.setVolume(1.0f, 1.0f)
                Log.i(tag, "MediaPlayer prepared: duration=${it.duration}ms")
            }
            mp.prepare()
            // Если за время prepare() пришёл новый speak() — не играем устаревшее.
            if (generation.get() != myGen) {
                try { source.close() } catch (_: Exception) {}
                try { mp.release() } catch (_: Exception) {}
                return
            }
            player.set(mp)
            currentSource.set(source)
            mp.start()
        } catch (e: Exception) {
            Log.e(tag, "play error: ${e.message}", e)
            try { source.close() } catch (_: Exception) {}
            try { mp.release() } catch (_: Exception) {}
            invokeDoneOnce(myGen)
        }
    }

    /** Remove audio files left by pre-product versions. */
    fun clearCache() {
        try {
            legacyCacheDir.deleteRecursively()
            Log.i(tag, "Legacy TTS cache cleared")
        } catch (e: Exception) {
            Log.w(tag, "clearCache failed: ${e.message}")
        }
    }

    private class ByteArraySource(private var bytes: ByteArray?) : MediaDataSource() {
        override fun readAt(position: Long, buffer: ByteArray, offset: Int, size: Int): Int {
            val current = bytes ?: return -1
            if (position >= current.size) return -1
            val count = minOf(size, current.size - position.toInt())
            System.arraycopy(current, position.toInt(), buffer, offset, count)
            return count
        }

        override fun getSize(): Long = bytes?.size?.toLong() ?: 0L

        override fun close() {
            bytes = null
        }
    }

    companion object {
        private const val MAX_AUDIO_BYTES = 10 * 1024 * 1024
    }
}
