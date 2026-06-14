package com.troika.hermes_assistant

import android.content.Context
import android.media.MediaPlayer
import android.util.Log
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/**
 * Воспроизведение голоса через серверный Edge TTS вместо локального Android TTS.
 *
 * Скачивает MP3 с PC, играет через MediaPlayer.
 * Кэширует последние ответы по хешу текста — избегаем повторного синтеза.
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
    private val cacheDir = File(ctx.cacheDir, "edge_tts").also { it.mkdirs() }
    private val currentDoneCallback = AtomicReference<(() -> Unit)?>(null)
    private val streamCancelled = AtomicBoolean(false)

    /** Синхронно скачивает MP3 и проигрывает; колбэк вызывается когда озвучка закончилась. */
    fun speak(text: String, onDone: (() -> Unit)? = null) {
        val cleaned = text.replace(Regex("[*#`]+"), "").trim()
        if (cleaned.isEmpty()) { onDone?.invoke(); return }

        currentDoneCallback.set(onDone)

        val t = Thread {
            try {
                val file = synthesizeOrCached(cleaned)
                if (file != null && file.length() > 0) {
                    playFile(file)
                } else {
                    Log.w(tag, "synth returned empty, fallback to silence")
                    invokeDoneOnce()
                }
            } catch (e: Exception) {
                Log.e(tag, "speak error: ${e.message}", e)
                invokeDoneOnce()
            }
        }
        t.name = "EdgeTtsFetch"
        t.start()
    }

    /** Прервать текущее воспроизведение. Вызовет onDone из текущего speak(), если он ещё не отстрелял. */
    fun stop() {
        streamCancelled.set(true)
        try {
            player.get()?.let {
                try { if (it.isPlaying) it.stop() } catch (_: Exception) {}
                it.release()
            }
        } catch (_: Exception) {}
        player.set(null)
        invokeDoneOnce()
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
        val cleaned = text.replace(Regex("[*#`]+"), "").trim()
        if (cleaned.isEmpty()) { onDone?.invoke(); return }

        val sentences = splitSentences(cleaned)
        if (sentences.size <= 1) {
            speak(cleaned, onDone)
            return
        }

        streamCancelled.set(false)
        currentDoneCallback.set(onDone)
        val queue = LinkedBlockingQueue<Any>()
        val endMarker = Any()

        // Продьюсер: качаем mp3 на каждое предложение последовательно, кладём в очередь
        Thread {
            try {
                for ((i, s) in sentences.withIndex()) {
                    if (streamCancelled.get()) break
                    try {
                        val file = synthesizeOrCached(s)
                        if (file != null && file.length() > 0) {
                            queue.put(file)
                        } else {
                            Log.w(tag, "stream: empty file for sentence #$i")
                        }
                    } catch (e: Exception) {
                        Log.e(tag, "stream synth #$i: ${e.message}")
                    }
                }
            } finally {
                queue.put(endMarker)
            }
        }.apply { name = "EdgeTtsStreamSynth"; isDaemon = true }.start()

        // Консьюмер: играем файлы по порядку, последний триггерит onDone
        Thread {
            try {
                while (!streamCancelled.get()) {
                    val item = queue.take()
                    if (item === endMarker) break
                    if (streamCancelled.get()) break
                    val file = item as File
                    playFileBlocking(file)
                }
            } catch (e: InterruptedException) {
                // ok
            } catch (e: Exception) {
                Log.e(tag, "stream play: ${e.message}")
            } finally {
                invokeDoneOnce()
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

    /** Синхронное проигрывание одного файла — блокирует до завершения. */
    private fun playFileBlocking(file: File) {
        val done = Object()
        val mp = MediaPlayer()
        try {
            mp.setDataSource(file.absolutePath)
            mp.setOnCompletionListener {
                try { it.release() } catch (_: Exception) {}
                player.compareAndSet(it, null)
                synchronized(done) { done.notify() }
            }
            mp.setOnErrorListener { p, what, extra ->
                Log.e(tag, "MediaPlayer error: $what/$extra")
                try { p.release() } catch (_: Exception) {}
                player.compareAndSet(p, null)
                synchronized(done) { done.notify() }
                true
            }
            mp.prepare()
            player.set(mp)
            mp.start()
            synchronized(done) {
                try { done.wait(120000) } catch (_: Exception) {}
            }
        } catch (e: Exception) {
            Log.e(tag, "playBlocking error: ${e.message}")
            try { mp.release() } catch (_: Exception) {}
        }
    }

    private fun invokeDoneOnce() {
        val cb = currentDoneCallback.getAndSet(null) ?: return
        try { cb() } catch (e: Exception) { Log.e(tag, "onDone error: ${e.message}") }
    }

    private fun synthesizeOrCached(text: String): File? {
        // Ключ кэша включает все параметры голоса — смена rate/pitch/volume = новый кэш
        val paramHash = "${voice}_r${(rate * 100).toInt()}_p${pitch}_v${volume}"
        val hash = text.hashCode().toString().replace("-", "n")
        val cached = File(cacheDir, "tts_${hash}_${paramHash}.mp3")
        if (cached.exists() && cached.length() > 100) {
            return cached
        }

        val url = "$serverUrl/v1/audio/speech"
        val body = JSONObject().apply {
            put("input", text)
            put("voice", voice)
            put("speed", rate)
            put("pitch", pitch)
            put("volume", volume)
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
        conn.outputStream.use { it.write(body) }

        if (conn.responseCode != 200) {
            val err = try { conn.errorStream?.bufferedReader()?.readText() } catch (_: Exception) { null }
            Log.e(tag, "TTS HTTP ${conn.responseCode}: ${err?.take(300)}")
            return null
        }

        val tmp = File(cacheDir, "tts_partial_$hash.mp3")
        FileOutputStream(tmp).use { out ->
            conn.inputStream.use { it.copyTo(out) }
        }
        // Атомарно переименовываем чтобы кэш не содержал недописанные файлы
        tmp.renameTo(cached)

        // Чистим старый кэш — оставляем последние 50 файлов
        val files = cacheDir.listFiles { f -> f.name.startsWith("tts_") }?.sortedBy { it.lastModified() }
        if (files != null && files.size > 50) {
            files.take(files.size - 50).forEach { it.delete() }
        }

        return cached
    }

    private fun playFile(file: File) {
        // Не вызываем stop() здесь — иначе текущий onDone отстрелит до начала проигрывания.
        // Достаточно того что предыдущий speak() уже отработал колбэк.
        val mp = MediaPlayer()
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
            mp.setDataSource(file.absolutePath)
            mp.setOnCompletionListener {
                try { it.release() } catch (_: Exception) {}
                player.compareAndSet(it, null)
                invokeDoneOnce()
            }
            mp.setOnErrorListener { p, what, extra ->
                Log.e(tag, "MediaPlayer error: $what/$extra (file=${file.name}, size=${file.length()})")
                // Удалим битый файл из кэша чтобы при следующем speak() пересинтезировать
                try { file.delete() } catch (_: Exception) {}
                try { p.release() } catch (_: Exception) {}
                player.compareAndSet(p, null)
                invokeDoneOnce()
                true
            }
            mp.setOnPreparedListener {
                // Громкость на максимум независимо от media volume — это голос ассистента,
                // он должен быть слышен. Если пользователь хочет тише — есть volume в JSON-теле.
                it.setVolume(1.0f, 1.0f)
                Log.i(tag, "MediaPlayer prepared: file=${file.name}, duration=${it.duration}ms")
            }
            mp.prepare()
            player.set(mp)
            mp.start()
        } catch (e: Exception) {
            Log.e(tag, "play error: ${e.message}", e)
            // Удалим битый файл
            try { file.delete() } catch (_: Exception) {}
            try { mp.release() } catch (_: Exception) {}
            invokeDoneOnce()
        }
    }

    /** Очистить весь TTS-кэш. Используется когда подозреваем что кэш содержит битые
     *  файлы (например после смены TTS-движка). Вызвать вручную при необходимости. */
    fun clearCache() {
        try {
            cacheDir.listFiles()?.forEach { it.delete() }
            Log.i(tag, "TTS cache cleared")
        } catch (e: Exception) {
            Log.w(tag, "clearCache failed: ${e.message}")
        }
    }
}
