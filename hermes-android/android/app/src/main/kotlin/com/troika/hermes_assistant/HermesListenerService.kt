package com.troika.hermes_assistant

import android.app.*
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import androidx.core.app.NotificationCompat
import io.flutter.embedding.engine.FlutterEngineCache
import io.flutter.plugin.common.MethodChannel
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.io.File
import java.io.FileWriter
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * Фоновый сервис с rolling buffer:
 *   - один поток постоянно читает с микрофона
 *   - все семплы накапливаются в кольцевой буфер на 4 секунды
 *   - когда амплитуда выше порога — копируем последние 3 сек и отправляем на STT
 *   - если в тексте есть "тройка" — будим UI
 */
class HermesListenerService : Service() {

    companion object {
        const val CHANNEL_ID = "hermes_listener"
        const val NOTIF_ID = 1001
        const val FLUTTER_CHANNEL = "com.troika.hermes/background"
        const val ACTION_START = "START"
        const val ACTION_STOP = "STOP"
        const val ACTION_TRIGGER_DIALOG = "TRIGGER_DIALOG"
        const val ACTION_INTERRUPT_TTS = "INTERRUPT_TTS"
        const val PREFS = "FlutterSharedPreferences"
        const val PREF_URL = "flutter.hermes_server_url"
        const val PREF_KEY = "flutter.hermes_api_key"
        const val PREF_TTS_VOICE = "flutter.hermes_tts_voice"
        const val PREF_BARGE_IN_ENABLED = "flutter.hermes_barge_in_enabled"
        const val PREF_BARGE_IN_THRESHOLD = "flutter.hermes_barge_in_threshold"

        const val AMPLITUDE_THRESHOLD = 800   // достаточный голос, но не шум
        // Порог для wake-word listener. 16.06.2026 поднят 450→600: слишком низкий
        // порог + триггер на 1 фрейме слал в облачный Whisper КАЖДЫЙ шорох, выжигая
        // дневной лимit Groq (2000/день) на тишине и ловя галлюцинации. 600 выше
        // фонового шума, но ловит нормально сказанное "Тройка".
        const val WAKE_AMPLITUDE_THRESHOLD = 600
        // Сколько подряд «голосовых» фреймов (~125мс каждый) нужно, чтобы вообще
        // отправить аудио в STT на проверку wake-word. 3 фрейма ≈ 375мс реальной
        // речи — короткий шум/щелчок такого не даёт. Это главный фикс расхода лимита.
        const val WAKE_MIN_VOICE_FRAMES = 3
        const val SAMPLE_RATE = 16000
        const val BUFFER_SECONDS = 3   // храним последние 3 сек
        // Кулдаун между попытками распознать wake-word. 16.06.2026 поднят 350→1200:
        // при 350мс получалось до ~2.8 STT-запросов/сек на шум. 1200мс = максимум
        // ~0.8/сек, отклик на «Тройка» при этом не страдает (слово длиннее).
        const val COOLDOWN_MS = 1200L

        // Покрываем основные ошибки распознавания Whisper'ом слова "Тройка".
        // Список расширен — лучше иметь немного ложных срабатываний (юзер
        // сразу скажет "стоп"), чем пропустить настоящее обращение.
        val WAKE_WORDS = listOf(
            // основное слово и его очевидные варианты
            "тройка", "троика", "троечка", "тройку", "троикa",
            "тройк", "троик", "троеч",
            // латиница (Whisper иногда переключается)
            "troika", "troyka", "troica", "troyca", "troike",
            // частые ошибки распознавания на тихом микрофоне
            "трой", "трои", "трое", "тройкa",
            // редкие соседние варианты
            "стройка", "тройки", "тройке"
        )
    }

    private val isRunning = AtomicBoolean(false)
    private val isTranscribing = AtomicBoolean(false)
    private val isInDialog = AtomicBoolean(false)
    private val listenerPaused = AtomicBoolean(false)
    private var wakeLock: PowerManager.WakeLock? = null
    private var listenerThread: Thread? = null
    private var tts: TextToSpeech? = null
    private var ttsReady = false
    private var phoneBridge: PhoneBridgeClient? = null
    private var edgeTts: EdgeTtsPlayer? = null

    // Rolling buffer: BUFFER_SECONDS секунд PCM
    private val ringSize = SAMPLE_RATE * BUFFER_SECONDS
    private val ringBuffer = ShortArray(ringSize)
    private var ringPos = 0
    private val ringLock = Any()

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        // TTS init может занять несколько секунд — Android даёт сервису
        // ровно 5-10 сек чтобы вызвать startForeground(). Поэтому всю
        // тяжёлую инициализацию выносим в фон, а startForeground вызываем
        // первым делом в onStartCommand.
        thread(name = "HermesTtsInit") { initTts() }
    }

    private fun initTts() {
        // Принудительно используем Google TTS — звучит намного приятнее самсунговского
        val googleTts = "com.google.android.tts"
        tts = TextToSpeech(this, { status ->
            if (status == TextToSpeech.SUCCESS) {
                val res = tts?.setLanguage(Locale("ru", "RU"))
                if (res == TextToSpeech.LANG_MISSING_DATA ||
                    res == TextToSpeech.LANG_NOT_SUPPORTED) {
                    android.util.Log.w("HermesListener", "Russian TTS not available")
                }
                pickFemaleRussianVoice()
                // Чуть медленнее и ниже тоном — спокойный, солидный голос
                tts?.setSpeechRate(0.95f)
                tts?.setPitch(0.9f)
                ttsReady = true
                android.util.Log.i("HermesListener", "TTS ready: voice=${tts?.voice?.name}")
            } else {
                android.util.Log.e("HermesListener", "TTS init failed status=$status")
            }
        }, googleTts)
    }

    /**
     * Переключиться на следующий русский голос (циклически).
     * Сохраняет выбор в SharedPreferences, чтобы он подхватился при перезапуске.
     */
    private fun switchToNextVoice(): String {
        val engine = tts ?: return "ошибка"
        val voices = try { engine.voices } catch (e: Exception) { null } ?: return "ошибка"
        val ruVoices = voices.filter { it.locale.language == "ru" }
            .sortedBy { it.name }
        if (ruVoices.isEmpty()) return "нет голосов"

        val current = engine.voice?.name
        val idx = ruVoices.indexOfFirst { it.name == current }
        val next = ruVoices[(idx + 1) % ruVoices.size]
        engine.voice = next

        val prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        prefs.edit().putString(PREF_TTS_VOICE, next.name).apply()
        android.util.Log.i("HermesListener", "Switched voice to ${next.name}")
        return next.name
    }

    /**
     * Выбираем женский русский голос Google TTS.
     * У Google TTS пол НЕ указан в имени голоса (ruf/rud/ruc/rue — это просто
     * идентификаторы), поэтому полагаемся на ручной приоритет голоса, который
     * пользователь установил через PREF_TTS_VOICE. Если не задан — берём
     * первый network-голос и логируем всё.
     */
    private fun pickFemaleRussianVoice() {
        val engine = tts ?: return
        val voices = try { engine.voices } catch (e: Exception) { null } ?: return

        val ruVoices = voices.filter { it.locale.language == "ru" }
        if (ruVoices.isEmpty()) {
            android.util.Log.w("HermesListener", "No Russian voices available")
            return
        }

        for (v in ruVoices) {
            android.util.Log.d(
                "HermesListener",
                "Voice avail: name=${v.name} q=${v.quality} net=${v.isNetworkConnectionRequired} features=${v.features}"
            )
        }

        // Читаем сохранённое предпочтение пользователя (название голоса)
        val prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val preferredName = prefs.getString(PREF_TTS_VOICE, null)

        val chosen = if (!preferredName.isNullOrBlank()) {
            ruVoices.firstOrNull { it.name == preferredName }
                ?: ruVoices.firstOrNull { it.isNetworkConnectionRequired }
                ?: ruVoices.first()
        } else {
            // По умолчанию ru-RU-language — это системный дефолт, обычно женский на современных Android
            ruVoices.firstOrNull { it.name == "ru-RU-language" }
                ?: ruVoices.firstOrNull { it.isNetworkConnectionRequired }
                ?: ruVoices.first()
        }

        engine.voice = chosen
        android.util.Log.i(
            "HermesListener",
            "Picked voice: ${chosen.name} quality=${chosen.quality} network=${chosen.isNetworkConnectionRequired}"
        )
    }

    /**
     * Озвучить и ДОЖДАТЬСЯ окончания (блокирует вызывающий поток). Заменяет
     * паттерн speak(x) + speak("") {wait}, который запускал ДВЕ озвучки подряд
     * и накладывал голоса. Один speak — одно ожидание.
     */
    private fun speakBlocking(text: String, timeoutMs: Long = 120000) {
        val cleaned = text.replace(Regex("[*#`]+"), "").trim()
        if (cleaned.isEmpty()) return
        val w = Object()
        speak(cleaned) { synchronized(w) { w.notify() } }
        synchronized(w) { try { w.wait(timeoutMs) } catch (_: Exception) {} }
    }

    private fun speak(text: String, onDone: (() -> Unit)? = null) {
        val cleaned = text.replace(Regex("[*#`]+"), "").trim()
        if (cleaned.isEmpty()) { onDone?.invoke(); return }

        // Сначала пробуем серверный Edge TTS — гораздо качественнее
        val edge = edgeTts
        if (edge != null) {
            // Колбэк может быть вызван либо при успешной озвучке, либо при ошибке/таймауте
            val fallbackInvoked = java.util.concurrent.atomic.AtomicBoolean(false)
            val done = { if (fallbackInvoked.compareAndSet(false, true)) onDone?.invoke() }
            // Streaming для всех средних/длинных ответов (>40 симв, любое число
            // предложений). Первое предложение играет пока синтезируется второе.
            // Очень короткие фразы (greeting, "Готово", "Поставил") идут целиком.
            val useStream = cleaned.length > 40
            if (useStream) edge.speakStream(cleaned, done) else edge.speak(cleaned, done)
            return
        }

        // Fallback на встроенный Android TTS если Edge недоступен
        if (!ttsReady) { onDone?.invoke(); return }
        tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(id: String?) {}
            override fun onDone(id: String?) { onDone?.invoke() }
            @Deprecated("Deprecated in Java")
            override fun onError(id: String?) { onDone?.invoke() }
        })
        tts?.speak(cleaned, TextToSpeech.QUEUE_FLUSH, null, "hermes-${System.currentTimeMillis()}")
    }

    /**
     * Если в настройках включён barge-in — запускает параллельный микрофонный монитор,
     * который остановит TTS как только пользователь начнёт говорить.
     * Колбэк нотифит ttsDone — runDialog проснётся раньше и сразу пойдёт писать вопрос.
     */
    private fun startBargeInMonitor(ttsDone: Object): BargeInMonitor? {
        val prefs = getSharedPreferences(PREFS, MODE_PRIVATE)
        val enabled = prefs.getBoolean(PREF_BARGE_IN_ENABLED, true)
        if (!enabled) return null
        // Был 1200 — слишком высокий, надо было орать. 700 даёт надёжное
        // срабатывание на обычную речь, и AEC отсекает эхо своего же динамика.
        val threshold = prefs.getInt(PREF_BARGE_IN_THRESHOLD, 700)
        val monitor = BargeInMonitor(threshold = threshold) {
            // barge-in сработал: рубим TTS и будим runDialog
            try { edgeTts?.stop() } catch (_: Exception) {}
            try { tts?.stop() } catch (_: Exception) {}
            synchronized(ttsDone) { ttsDone.notify() }
        }
        monitor.start()
        return monitor
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // КРИТИЧНО: startForeground() надо вызывать в первые 5 секунд жизни сервиса,
        // иначе Android кидает ForegroundServiceDidNotStartInTimeException и краш.
        // Вызываем ДО любой другой логики, даже для ACTION_STOP — иначе stopSelf()
        // тоже может не успеть.
        try {
            startForeground(NOTIF_ID, buildNotification())
        } catch (e: Exception) {
            android.util.Log.e("HermesListener", "startForeground failed: ${e.message}")
        }

        when (intent?.action) {
            ACTION_STOP -> { stopSelf(); return START_NOT_STICKY }
            ACTION_TRIGGER_DIALOG -> {
                startListening()  // если ещё не запущен — запустим
                if (isInDialog.compareAndSet(false, true)) {
                    thread(name = "HermesDialogManual") { runDialog() }
                }
            }
            ACTION_INTERRUPT_TTS -> {
                // Мгновенная остановка любой текущей речи (Edge TTS + Android TTS).
                // Вызывается тапом по орбу когда Тройка говорит.
                try { edgeTts?.stop() } catch (_: Exception) {}
                try { tts?.stop() } catch (_: Exception) {}
            }
            else -> startListening()
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun startListening() {
        // startForeground уже вызван в onStartCommand — здесь не дублируем
        if (wakeLock == null) {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = pm.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK,
                "Hermes:ListenerWakeLock"
            ).apply {
                setReferenceCounted(false)
                acquire()
            }
        }

        if (isRunning.compareAndSet(false, true)) {
            listenerThread = thread(start = true, name = "HermesListener") {
                runListenerLoop()
            }
        }

        // Подключаемся к PC через WebSocket чтобы Hermes-LLM мог управлять телефоном
        startPhoneBridge()

        // Инициализируем серверный Edge TTS (более качественный голос)
        startEdgeTts()
    }

    private fun startEdgeTts() {
        if (edgeTts != null) return
        val prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val url = prefs.getString(PREF_URL, null)
        val key = prefs.getString(PREF_KEY, "") ?: ""
        if (url.isNullOrBlank()) return
        val voice = prefs.getString("flutter.hermes_edge_voice", null) ?: "ru-RU-SvetlanaNeural"
        // SharedPreferences хранит числа как double/int; берём с fallback
        val rate = readDoublePref(prefs, "flutter.hermes_voice_rate", 1.0)
        val pitch = readIntPref(prefs, "flutter.hermes_voice_pitch", 0)
        val volume = readIntPref(prefs, "flutter.hermes_voice_volume", 0)
        edgeTts = EdgeTtsPlayer(applicationContext, url, key, voice, rate, pitch, volume)
        android.util.Log.i("HermesListener",
            "Edge TTS: voice=$voice rate=$rate pitch=$pitch volume=$volume")
    }

    private fun readDoublePref(prefs: SharedPreferences, key: String, default: Double): Double {
        return try {
            // Flutter shared_preferences хранит double как double
            val v = prefs.all[key]
            when (v) {
                is Double -> v
                is Float -> v.toDouble()
                is Int -> v.toDouble()
                is Long -> v.toDouble()
                is String -> v.toDoubleOrNull() ?: default
                else -> default
            }
        } catch (_: Exception) { default }
    }

    private fun readIntPref(prefs: SharedPreferences, key: String, default: Int): Int {
        return try {
            val v = prefs.all[key]
            when (v) {
                is Int -> v
                is Long -> v.toInt()
                is Double -> v.toInt()
                is Float -> v.toInt()
                is String -> v.toIntOrNull() ?: default
                else -> default
            }
        } catch (_: Exception) { default }
    }

    private fun startPhoneBridge() {
        if (phoneBridge != null) return
        val prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val url = prefs.getString(PREF_URL, null)
        val key = prefs.getString(PREF_KEY, "") ?: ""
        if (url.isNullOrBlank()) {
            android.util.Log.w("HermesListener", "PhoneBridge: no URL configured")
            return
        }
        phoneBridge = PhoneBridgeClient(applicationContext, url, key).also { it.start() }
        android.util.Log.i("HermesListener", "PhoneBridge started")
    }

    private fun runListenerLoop() {
        val bufferSize = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        ).coerceAtLeast(4096) * 2

        var recorder: AudioRecord? = null
        try {
            recorder = AudioRecord(
                MediaRecorder.AudioSource.MIC,
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufferSize
            )

            if (recorder.state != AudioRecord.STATE_INITIALIZED) {
                android.util.Log.e("HermesListener", "AudioRecord init failed")
                return
            }

            recorder.startRecording()
            android.util.Log.d("HermesListener", "Recording started, buf=$bufferSize")

            val readBuf = ShortArray(bufferSize / 2)
            var lastTranscribeTime = 0L
            var voiceFrames = 0

            while (isRunning.get()) {
                if (listenerPaused.get()) {
                    // Сервис диалога владеет микрофоном — освобождаем
                    try { recorder.stop() } catch (_: Exception) {}
                    while (listenerPaused.get() && isRunning.get()) {
                        Thread.sleep(100)
                    }
                    if (!isRunning.get()) break
                    try { recorder.startRecording() } catch (e: Exception) {
                        android.util.Log.e("HermesListener", "Re-start recorder failed: ${e.message}")
                        Thread.sleep(500)
                        continue
                    }
                    voiceFrames = 0
                    lastTranscribeTime = System.currentTimeMillis()
                    continue
                }
                val read = recorder.read(readBuf, 0, readBuf.size)
                if (read <= 0) { Thread.sleep(20); continue }

                // Записываем в rolling buffer
                synchronized(ringLock) {
                    for (i in 0 until read) {
                        ringBuffer[ringPos] = readBuf[i]
                        ringPos = (ringPos + 1) % ringSize
                    }
                }

                // Считаем амплитуду
                var sum = 0L
                for (i in 0 until read) sum += Math.abs(readBuf[i].toInt())
                val amplitude = (sum / read).toInt()

                val now = System.currentTimeMillis()
                if (amplitude > WAKE_AMPLITUDE_THRESHOLD) {
                    voiceFrames++
                } else {
                    voiceFrames = maxOf(0, voiceFrames - 1)
                }

                // Голос обнаружен и кулдаун прошёл — проверяем wake-word.
                // Требуем НЕСКОЛЬКО подряд голосовых фреймов (устойчивую речь),
                // иначе короткий шум/щелчок не должен слать аудио в облачный STT.
                if (voiceFrames >= WAKE_MIN_VOICE_FRAMES &&
                    !isTranscribing.get() &&
                    now - lastTranscribeTime > COOLDOWN_MS
                ) {
                    lastTranscribeTime = now
                    voiceFrames = 0

                    if (isTranscribing.compareAndSet(false, true)) {
                        // Берём snapshot после короткой паузы, чтобы в буфер
                        // успело записаться окончание слова "Тройка". Если
                        // юзер всё ещё говорит — ждём дольше (до 1.2 с).
                        thread(name = "HermesTranscribe") {
                            try {
                                waitForSpeechEnd(maxWaitMs = 1200, silenceMs = 400)
                                if (!isRunning.get()) return@thread
                                val snapshot = takeSnapshot()
                                checkWakeWord(snapshot)
                            } finally {
                                isTranscribing.set(false)
                            }
                        }
                    }
                }
            }
        } catch (e: SecurityException) {
            android.util.Log.e("HermesListener", "No mic permission: ${e.message}")
        } catch (e: Exception) {
            android.util.Log.e("HermesListener", "Listener error: ${e.message}")
            e.printStackTrace()
        } finally {
            try { recorder?.stop() } catch (_: Exception) {}
            recorder?.release()
        }
    }

    /**
     * Ждём пока речь в rolling buffer не закончится (silenceMs тишины подряд)
     * или истечёт maxWaitMs. Это позволяет захватывать полное "Тройка"
     * не зная заранее как долго юзер будет говорить.
     */
    private fun waitForSpeechEnd(maxWaitMs: Long, silenceMs: Long) {
        val start = System.currentTimeMillis()
        var lastVoiceTime = start
        val checkWindow = SAMPLE_RATE / 10  // 100 мс выборка
        while (System.currentTimeMillis() - start < maxWaitMs) {
            Thread.sleep(80)
            val recent = takeSnapshotMs(120)
            var sum = 0L
            for (s in recent) sum += Math.abs(s.toInt())
            val amp = if (recent.isNotEmpty()) (sum / recent.size).toInt() else 0
            if (amp > WAKE_AMPLITUDE_THRESHOLD) {
                lastVoiceTime = System.currentTimeMillis()
            } else if (System.currentTimeMillis() - lastVoiceTime > silenceMs) {
                return
            }
        }
    }

    /** Скопировать последние BUFFER_SECONDS секунд из rolling buffer */
    private fun takeSnapshot(): ShortArray {
        synchronized(ringLock) {
            val out = ShortArray(ringSize)
            // ringBuffer[ringPos] — самый старый сэмпл
            for (i in 0 until ringSize) {
                out[i] = ringBuffer[(ringPos + i) % ringSize]
            }
            return out
        }
    }

    private fun checkWakeWord(pcm: ShortArray) {
        val out = ByteArrayOutputStream(pcm.size * 2)
        for (s in pcm) {
            val v = s.toInt()
            out.write(v and 0xff)
            out.write((v shr 8) and 0xff)
        }
        val wav = pcmToWav(out.toByteArray(), SAMPLE_RATE)
        val raw = transcribeSync(wav)?.trim() ?: ""
        val text = russianLowercase(raw)

        if (raw.isNotEmpty() && !isWhisperHallucination(text)) {
            android.util.Log.d("HermesListener", "heard='$raw' norm='$text'")
            sendDebugToFlutter(raw)
            val matched = WAKE_WORDS.firstOrNull { text.contains(it) }
            // АТОМАРНО: compareAndSet вместо get()+set() — иначе между проверкой
            // и установкой manual-путь (triggerDialog) мог тоже стартовать диалог,
            // и запускались ДВА runDialog → два приветствия / наложение голосов.
            if (matched != null && isInDialog.compareAndSet(false, true)) {
                android.util.Log.i("HermesListener", "WAKE_WORD matched=$matched")
                thread(name = "HermesDialog") { runDialog() }
            }
        }
    }

    /**
     * Ручной lowercase по кодам символов — устройство-независимо.
     * Кириллица: А..Я = 0x0410..0x042F, а..я = 0x0430..0x044F (разница 32).
     * Ё (0x0401) → ё (0x0451).
     * Латиница: A..Z = 0x41..0x5A, a..z = 0x61..0x7A.
     */
    private fun russianLowercase(s: String): String {
        val sb = StringBuilder(s.length)
        for (c in s) {
            val code = c.code
            val mapped = when (code) {
                in 0x0410..0x042F -> (code + 32).toChar()  // А..Я → а..я
                0x0401 -> 0x0451.toChar()                   // Ё → ё
                in 0x41..0x5A -> (code + 32).toChar()       // A..Z → a..z
                else -> c
            }
            sb.append(mapped)
        }
        return sb.toString()
    }

    /**
     * Whisper часто галлюцинирует на тишине и шуме — фильтруем известные ложные
     * срабатывания. Источник: тренировочные данные Whisper включают много
     * YouTube-видео, поэтому на пустом аудио он выдаёт куски титров.
     */
    private fun isWhisperHallucination(text: String): Boolean {
        val raw = russianLowercase(text).trim().trim('.', '!', '?', ',', ' ', '\n', '\r')

        // Слишком короткие фрагменты — почти всегда галлюцинации одиночных слов
        if (raw.length < 3) return true

        // Точные совпадения
        val exact = setOf(
            "спасибо", "спасибо за внимание", "спасибо за просмотр", "спасибо большое",
            "продолжение следует", "субтитры", "субтитры подогнал",
            "субтитры сделал", "субтитры сделал dimatorzok",
            "субтитры создавал dimatorzok", "редактор субтитров а.семкин",
            "до встречи", "до новых встреч", "до скорой встречи",
            "ну", "так", "и", "да", "вот", "ага", "угу", "ох", "эх", "хм",
            "thanks", "thank you", "you", "bye", "okay", "ok",
            ".", "..", "...", "[музыка]", "(музыка)", "[аплодисменты]", "(аплодисменты)",
            "продолжение следует...",
            "продолжение в следующей серии",
            "подписывайтесь на канал", "ставьте лайки", "ставьте лайк",
            "не забывайте подписываться",
            "корректор", "корректор а.кулакова",
            "озвучивал", "автор перевода",
            "до свидания", "пока всем",
            "всем пока", "всем спасибо",
        )
        if (raw in exact) return true

        // Подстрочные шаблоны — слово "субтитры", "DimaTorzok", разные YouTube-формулы
        val patterns = listOf(
            "продолжение следует",
            "субтитры создавал",
            "субтитры сделал",
            "субтитры подогнал",
            "редактор субтитров",
            "корректор",
            "спасибо за просмотр",
            "спасибо за внимание",
            "dimatorzok", "семкин", "кулакова",
            "подписывайтесь на канал",
            "ставьте лайк",
            "поставьте лайк",
            "не забудьте подписаться",
        )
        return patterns.any { raw.contains(it) }
    }

    /**
     * Полный диалог в continuous-режиме:
     *   wake-word → "Слушаю" → запись → ответ → ОПЯТЬ запись (без wake-word) → ответ → ...
     *   Выход если: 7 сек тишины ИЛИ юзер сказал "хватит/стоп/спасибо пока"
     * История сообщений сохраняется между итерациями для follow-up вопросов.
     */
    private fun runDialog() {
        listenerPaused.set(true)
        Thread.sleep(400)

        val history = mutableListOf<JSONObject>()
        var firstTurn = true

        try {
            HermesOverlay.get(this).show("✨ Слушаю...")
            // Мгновенный звуковой сигнал — юзер сразу слышит что wake-word поймался,
            // даже до того как Edge TTS успеет синтезировать "Слушаю"
            SoundFeedback.heard()

            // Короткое "Слушаю" только в начале диалога
            val ttsHi = Object()
            // Случайная короткая фраза приветствия — Jarvis-стиль, без перебора с именем
            val greeting = listOf(
                "Слушаю.",
                "Да?",
                "Здесь.",
                "К услугам.",
            ).random()
            speak(greeting) { synchronized(ttsHi) { ttsHi.notify() } }
            synchronized(ttsHi) { try { ttsHi.wait(2500) } catch (_: Exception) {} }
            // Дольше пауза — динамик/AGC должны успокоиться, иначе первые слова
            // юзера съедаются эхо-подавлением мика после TTS.
            Thread.sleep(700)

            while (isRunning.get()) {
                // Запись вопроса
                HermesOverlay.get(this).updateStatus(
                    if (firstTurn) "🎙 Говори..." else "🎙 Продолжай..."
                )
                val maxMs = if (firstTurn) 9000L else 8000L
                val questionWav = recordUtterance(maxMs)
                if (questionWav == null) {
                    // Тишина — выходим из диалога
                    if (!firstTurn) {
                        HermesOverlay.get(this).updateStatus("До связи")
                        Thread.sleep(800)
                    } else {
                        HermesOverlay.get(this).updateStatus("Не услышал")
                        Thread.sleep(1200)
                    }
                    break
                }

                HermesOverlay.get(this).updateStatus("⏳ Распознаю...")
                val rawQuestion = transcribeSync(questionWav)?.trim() ?: ""
                val question = russianLowercase(rawQuestion)
                if (rawQuestion.isEmpty() || isWhisperHallucination(question)) {
                    if (!firstTurn) {
                        // Молчание во время follow-up — завершаем
                        break
                    }
                    HermesOverlay.get(this).updateStatus("Не разобрал")
                    Thread.sleep(1200)
                    break
                }

                // Команды выхода из диалога
                val exitPhrases = listOf(
                    "хватит", "стоп", "пока", "спасибо пока", "до свидания",
                    "выход", "закончили", "всё", "все спасибо",
                    "закройся", "помолчи", "уйди", "помолчишь",
                    "молчи", "тише", "сообщи когда", "скажешь когда",
                    "позовешь", "позовёшь", "разбуди когда", "жду",
                    "не слушай", "отключись",
                )
                if (exitPhrases.any { question.contains(it) } && question.length < 40) {
                    HermesOverlay.get(this).updateStatus("До связи!")
                    speakBlocking("Хорошо", timeoutMs = 5000)
                    break
                }

                // Команда переключения голоса
                if (question.contains("смени голос") ||
                    question.contains("другой голос") ||
                    question.contains("следующий голос") ||
                    question.contains("переключи голос")
                ) {
                    val newName = switchToNextVoice()
                    HermesOverlay.get(this).updateStatus("Голос: $newName")
                    speakBlocking(
                        "Это новый голос. Если нравится — продолжаем. Если нет, скажи смени голос.",
                        timeoutMs = 15000,
                    )
                    continue
                }

                HermesOverlay.get(this).updateStatus("Ты: $rawQuestion")
                Thread.sleep(300)

                // Локальный матчер команд телефона — пробуем выполнить ДО вызова LLM
                val localResult = PhoneCommands.tryExecute(this, question, rawQuestion)
                if (localResult != null) {
                    HermesOverlay.get(this).updateStatus(localResult)
                    speakBlocking(localResult, timeoutMs = 20000)
                    // Добавляем в историю чтобы LLM знал о выполненной команде
                    history.add(JSONObject().apply {
                        put("role", "user"); put("content", rawQuestion)
                    })
                    history.add(JSONObject().apply {
                        put("role", "assistant"); put("content", localResult)
                    })
                    sendChatToFlutter("user", rawQuestion)
                    sendChatToFlutter("assistant", localResult)
                    firstTurn = false
                    continue
                }

                // Hermes — с историей сообщений для контекста
                HermesOverlay.get(this).updateStatus("🤔 Думаю...")
                SoundFeedback.thinking()
                history.add(JSONObject().apply {
                    put("role", "user")
                    // Дату кладём В НАЧАЛО вопроса (user-сообщение), а НЕ в system prompt:
                    // слабая модель (deepseek) игнорирует дату из system, но слушается
                    // прямого ввода юзера. Проверено: system→«14 июня» (галлюцинация
                    // из обучения), user-префикс→верная дата. Префикс короткий и
                    // незаметный в TTS т.к. это вход, а не ответ.
                    put("content", currentDatePrefix() + rawQuestion)
                })
                sendChatToFlutter("user", rawQuestion)
                val answer = chatWithHermesHistory(history)
                if (answer.isEmpty()) {
                    HermesOverlay.get(this).updateStatus("Тройка не ответил")
                    Thread.sleep(1500)
                    break
                }
                history.add(JSONObject().apply {
                    put("role", "assistant")
                    put("content", answer)
                })
                sendChatToFlutter("assistant", answer)

                HermesOverlay.get(this).updateStatus(answer.take(120))
                val ttsDone = Object()
                val bargeMon = startBargeInMonitor(ttsDone)
                speak(answer) { synchronized(ttsDone) { ttsDone.notify() } }
                // Длинные ответы (особенно после инструментов) могут озвучиваться до 2 минут
                synchronized(ttsDone) { try { ttsDone.wait(120000) } catch (_: Exception) {} }
                val bargedIn = bargeMon?.wasTriggered() == true
                bargeMon?.stop()
                if (!bargedIn) Thread.sleep(300)

                // Async-задача: Тройка озвучила "Принял, делаю в фоне" → выходим из continuous.
                // Когда задача завершится, push-уведомление через notify_voice разбудит Мишу
                // отдельной озвучкой — слушать всё это время не нужно.
                val answerLow = answer.lowercase()
                val asyncSignals = listOf(
                    "в фоне", "в фоновом режиме",
                    "скажу когда", "сообщу когда", "позову когда",
                    "когда готово", "когда будет готов",
                    "когда закончу", "приступаю",
                )
                if (asyncSignals.any { answerLow.contains(it) }) {
                    android.util.Log.i("HermesListener",
                        "Async-task detected in reply, exiting continuous mode")
                    break
                }

                firstTurn = false
                // Ограничиваем длину истории чтобы не раздувать контекст
                if (history.size > 12) {
                    history.subList(0, history.size - 12).clear()
                }
            }

            Thread.sleep(300)
            HermesOverlay.get(this).hide()
        } catch (e: Exception) {
            android.util.Log.e("HermesListener", "Dialog error: ${e.message}")
            HermesOverlay.get(this).hide()
        } finally {
            isInDialog.set(false)
            listenerPaused.set(false)
        }
    }

    /** Записать вопрос своим AudioRecord (listener loop в это время паузится) */
    private fun recordUtterance(maxMs: Long): ByteArray? {
        val bufSize = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        ).coerceAtLeast(4096)

        var rec: AudioRecord? = null
        return try {
            rec = AudioRecord(
                MediaRecorder.AudioSource.MIC,
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufSize * 2
            )
            if (rec.state != AudioRecord.STATE_INITIALIZED) {
                android.util.Log.e("HermesListener", "Dialog recorder init failed")
                return null
            }
            rec.startRecording()

            val pcm = ByteArrayOutputStream()
            val frameBuf = ShortArray(bufSize / 2)
            val startTime = System.currentTimeMillis()
            var lastVoiceTime = startTime
            // Считаем фреймы РЕЧИ (амплитуда > порога) и среднюю амплитуду всех фреймов.
            // Whisper галлюцинирует на коротких/тихих фрагментах ("Субтитры сделал DimaTorzok",
            // "Спасибо за просмотр") — если речи реально не было, лучше вообще не отправлять.
            var voiceFrameCount = 0
            var totalFrames = 0
            var ampSum = 0L

            while (System.currentTimeMillis() - startTime < maxMs) {
                val read = rec.read(frameBuf, 0, frameBuf.size)
                if (read <= 0) { Thread.sleep(20); continue }
                for (i in 0 until read) {
                    pcm.write(frameBuf[i].toInt() and 0xff)
                    pcm.write((frameBuf[i].toInt() shr 8) and 0xff)
                }
                var sum = 0L
                for (i in 0 until read) sum += Math.abs(frameBuf[i].toInt())
                val amp = (sum / read).toInt()
                totalFrames++
                ampSum += amp
                if (amp > AMPLITUDE_THRESHOLD) {
                    lastVoiceTime = System.currentTimeMillis()
                    voiceFrameCount++
                } else if (voiceFrameCount > 0 && System.currentTimeMillis() - lastVoiceTime > 1500) {
                    break
                }
            }

            // Мягкие проверки на реальную речь:
            //   1) не меньше 3 фреймов выше порога (≈100 мс речи) — было 8, но реальные
            //      короткие вопросы ("Который час?") режутся
            //   2) ИЛИ средняя амплитуда по всей записи > 150 (раньше требовалось И-И)
            //   3) запись не пустая (>2 КБ — иначе вообще ничего не было)
            val avgAmp = if (totalFrames > 0) (ampSum / totalFrames).toInt() else 0
            val hasRealSpeech =
                pcm.size() > 2048 &&
                (voiceFrameCount >= 3 || avgAmp > 150)
            if (!hasRealSpeech) {
                android.util.Log.d(
                    "HermesListener",
                    "recordUtterance: dropped (voiceFrames=$voiceFrameCount avgAmp=$avgAmp bytes=${pcm.size()})"
                )
                null
            } else {
                pcmToWav(pcm.toByteArray(), SAMPLE_RATE)
            }
        } catch (e: Exception) {
            android.util.Log.e("HermesListener", "recordUtterance err: ${e.message}")
            null
        } finally {
            try { rec?.stop() } catch (_: Exception) {}
            rec?.release()
        }
    }

    /** Взять последние N миллисекунд из rolling buffer */
    private fun takeSnapshotMs(ms: Int): ShortArray {
        val samples = (SAMPLE_RATE * ms / 1000).coerceAtMost(ringSize)
        synchronized(ringLock) {
            val out = ShortArray(samples)
            val start = (ringPos - samples + ringSize) % ringSize
            for (i in 0 until samples) {
                out[i] = ringBuffer[(start + i) % ringSize]
            }
            return out
        }
    }

    /** Короткий префикс с датой для ВХОДЯЩЕГО user-сообщения. Слабая модель
     *  игнорирует дату из system prompt, но не из прямого ввода юзера. */
    private fun currentDatePrefix(): String {
        val cal = java.util.Calendar.getInstance()
        val months = arrayOf("января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря")
        val weekdays = arrayOf("воскресенье", "понедельник", "вторник", "среда",
            "четверг", "пятница", "суббота")
        val day = cal.get(java.util.Calendar.DAY_OF_MONTH)
        val month = months[cal.get(java.util.Calendar.MONTH)]
        val year = cal.get(java.util.Calendar.YEAR)
        val wd = weekdays[cal.get(java.util.Calendar.DAY_OF_WEEK) - 1]
        val hh = cal.get(java.util.Calendar.HOUR_OF_DAY)
        val mm = cal.get(java.util.Calendar.MINUTE)
        return "[сейчас $day $month $year, $wd, " +
            String.format("%02d:%02d", hh, mm) + "] "
    }

    /** Запрос к Hermes /v1/chat/completions с историей сообщений (для continuous-режима) */
    private fun chatWithHermesHistory(history: List<JSONObject>): String {
        val prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val serverUrl = prefs.getString(PREF_URL, null) ?: return ""
        val apiKey = prefs.getString(PREF_KEY, "") ?: ""
        val url = "$serverUrl/v1/chat/completions"

        return try {
            val body = JSONObject().apply {
                put("model", "troika-agent")
                put("messages", JSONArray().apply {
                    put(JSONObject().apply {
                        put("role", "system")
                        put("content",
                            "Ты Тройка — личный голосовой ассистент Миши. " +
                            "Тебя зовут Тройка, ты отзываешься на 'тройка'.\n\n" +
                            "АВТО-ПОДБОР ИНСТРУМЕНТОВ:\n" +
                            "Если задача нетривиальна (что-то сложнее 'который час' или 'погода в Москве'), " +
                            "ПЕРВЫМ ДЕЛОМ вызови skill_view('voice-task-routing') — это таблица " +
                            "соответствия 'услышал → какой tool вызвать' для голосовых сценариев. " +
                            "В ней правила выбора tool'ов для презентаций, календаря, файлов, заметок, " +
                            "погоды, переводов, web-поиска, делегирования. После загрузки skill " +
                            "немедленно делай нужный tool-вызов, не комментируй процесс. " +
                            "Если есть skill подходящий под тематику (apple-notes, songwriting, " +
                            "powerpoint и т.д.) — тоже загружай его через skill_view. " +
                            "Скиллы — это знание о том КАК делать, tools — это РУКИ. Сначала ум, потом руки.\n\n" +
                            "СТИЛЬ ОБЩЕНИЯ — критически важно, читай внимательно:\n" +
                            "Ты НЕ ИИ-ассистент. Ты — живой умный человек, который помогает другу. " +
                            "Говори как настоящий человек: естественно, кратко, по делу. " +
                            "ЗАПРЕЩЕНО говорить любые из этих фраз и формулировок:\n" +
                            "— 'я ИИ', 'я модель', 'я не могу как ИИ', 'как искусственный интеллект'\n" +
                            "— 'я готов помочь', 'чем могу быть полезен', 'буду рад помочь'\n" +
                            "— 'я успешно выполнил', 'действие выполнено успешно', 'задача решена'\n" +
                            "— 'надеюсь это поможет', 'если нужно ещё что-то — обращайся'\n" +
                            "— 'давайте/давай разберём', 'предлагаю', 'хочу отметить'\n" +
                            "— 'извини, но', 'к сожалению', 'извиняюсь' (без реальной причины)\n" +
                            "— 'отлично!', 'прекрасно!', 'замечательно!', 'круто!' в начале\n" +
                            "— 'как помощник', 'в моих возможностях', 'позвольте мне'\n" +
                            "— перечисления вида '1) ... 2) ... 3) ...' и markdown списки\n" +
                            "— 'хорошо', 'да', 'конечно' в начале (сразу к делу!)\n" +
                            "— чрезмерная вежливость, излишние пояснения, дисклеймеры\n\n" +
                            "КАК НУЖНО говорить:\n" +
                            "— Короткими предложениями, как в разговоре с другом.\n" +
                            "— Если сделал — просто скажи что получилось: 'Готово, открыл'. 'Сохранил'. 'Не нашёл'. \n" +
                            "— Иногда лёгкая ирония или юмор — но не натужно.\n" +
                            "— Если не знаешь — скажи 'не знаю' или 'надо проверить', не выкручивайся.\n" +
                            "— Имя 'Миша' используй РЕДКО — раз в десять-двадцать реплик, не чаще.\n" +
                            "— Никаких эмодзи, markdown, разметки — это озвучивается ГОЛОСОМ.\n\n" +
                            "ПАМЯТЬ: используй memory tool проактивно — сохраняй важные факты " +
                            "(предпочтения, имена близких, события, проекты Миши). " +
                            "В начале каждой сессии помни что было раньше. " +
                            "Никогда не говори 'я запомнил это' — просто незаметно сохраняй.\n\n" +
                            "ИНСТРУМЕНТЫ: у тебя есть много tools — для телефона (открыть приложение, " +
                            "позвонить, будильник, файлы, скриншот, фонарик, батарея), для документов " +
                            "(PDF, PPTX, DOCX, XLSX, инфографика, красивые презентации с темами и картинками), " +
                            "для повседневности (погода, Wikipedia, переводчик, курсы валют, крипта, " +
                            "новости, YouTube поиск, QR-коды, калькулятор, конвертер единиц, время по " +
                            "городам, генерация изображений через Pollinations). " +
                            "Когда Миша просит что-то — сразу делай, не объясняй процесс.\n\n" +
                            "ПРАВИЛА ВЫБОРА ИНСТРУМЕНТОВ (КРИТИЧЕСКИ ВАЖНО):\n" +
                            "— Презентация / слайды / 'презинтация' / slide deck — ВСЕГДА phone_create_beautiful_pptx, " +
                            "НИКОГДА phone_create_pptx (он даёт уродливые белые слайды). Подбирай theme под тему: " +
                            "экология/природа→forest_green, бизнес/корпоратив→corporate_navy, технологии→modern_blue, " +
                            "искусство/дизайн→vibrant_pink, минимализм→minimalist_mono, океан/вода→ocean_teal, " +
                            "закат/тепло→warm_sunset, наука/космос→elegant_purple.\n" +
                            "— Документ / отчёт / PDF — phone_create_beautiful_pdf, не phone_create_pdf.\n" +
                            "— Календарь / встреча / событие / 'поставь / запиши на завтра / напомни' — " +
                            "android_calendar_create_event с ISO-8601 датой. Длительность опускай — " +
                            "будет дефолт 1 час. Reminder_minutes=15 ставь по умолчанию если Миша не " +
                            "сказал иначе. 'Что на завтра / что запланировано' — android_calendar_list_events.\n" +
                            "— Сложная многошаговая задача / исследование / 'разберись подробно' / 'собери информацию' — " +
                            "используй delegate_task: заведи sub-agent с конкретной целью и получи короткий итог. " +
                            "Не пытайся всё делать в одном цикле, если задача требует 5+ шагов.\n" +
                            "— Несколько мнений / 'подумай по-разному' / сложный анализ — mixture_of_agents " +
                            "(несколько моделей параллельно дают ответ, потом синтез).\n" +
                            "— MCP-tools (mcp_filesystem_*, mcp_git_*, mcp_time_*, mcp_fetch_*, mcp_sequential_thinking_*) — " +
                            "доступ к файлам PC, git-репам, точному времени/таймзонам, HTTP fetch и пошаговому " +
                            "рассуждению. Используй их когда нужно работать с компьютером Миши, а не с телефоном.\n" +
                            "— Не пиши 'сейчас сделаю презентацию' — просто вызови tool и потом скажи 'готово, в Downloads'.\n\n" +
                            "ДАТА/ВРЕМЯ: текущие дата и время идут в начале сообщения Миши в квадратных скобках " +
                            "[сейчас ...] — бери их ОТТУДА, никогда не называй дату из памяти/обучения."
                        )
                    })
                    for (msg in history) put(msg)
                })
                put("stream", false)
            }

            val conn = (URL(url).openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                doOutput = true
                connectTimeout = 8000
                // Большой timeout — Hermes может ходить в браузер/искать/работать с файлами
                readTimeout = 180000
                setRequestProperty("Authorization", "Bearer $apiKey")
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
                // Стабильный session key и id чтобы Hermes сохранял память и историю
                // между разными разговорами с этим устройством
                setRequestProperty("X-Hermes-Session-Key", "phone-misha")
                setRequestProperty("X-Hermes-Session-Id", "phone-misha-main")
                // Контекст устройства для режима «где я» — Wi-Fi BSSID,
                // bluetooth, тип сети. Сервер маппит в дом/работа/машина.
                try {
                    val ctxHeader = DeviceContext.asHeaderValue(applicationContext)
                    if (ctxHeader.isNotEmpty()) {
                        setRequestProperty("X-Hermes-Device-Context", ctxHeader)
                    }
                } catch (_: Exception) {}
            }
            conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }

            if (conn.responseCode == 200) {
                val resp = conn.inputStream.bufferedReader(Charsets.UTF_8).readText()
                val json = JSONObject(resp)
                val choices = json.optJSONArray("choices") ?: return ""
                if (choices.length() == 0) return ""
                val msg = choices.getJSONObject(0).optJSONObject("message")
                msg?.optString("content", "") ?: ""
            } else {
                val err = conn.errorStream?.bufferedReader()?.readText() ?: ""
                android.util.Log.e("HermesListener", "Chat ${conn.responseCode}: $err")
                ""
            }
        } catch (e: Exception) {
            android.util.Log.e("HermesListener", "Chat err: ${e.message}")
            ""
        }
    }

    private fun pcmToWav(pcm: ByteArray, sampleRate: Int): ByteArray {
        val out = ByteArrayOutputStream()
        val dos = DataOutputStream(out)
        val totalAudioLen = pcm.size
        val totalDataLen = totalAudioLen + 36
        val channels = 1
        val byteRate = sampleRate * 2 * channels

        dos.writeBytes("RIFF")
        dos.write(intToLE(totalDataLen))
        dos.writeBytes("WAVE")
        dos.writeBytes("fmt ")
        dos.write(intToLE(16))
        dos.write(shortToLE(1))
        dos.write(shortToLE(channels))
        dos.write(intToLE(sampleRate))
        dos.write(intToLE(byteRate))
        dos.write(shortToLE(channels * 2))
        dos.write(shortToLE(16))
        dos.writeBytes("data")
        dos.write(intToLE(totalAudioLen))
        dos.write(pcm)
        dos.flush()
        return out.toByteArray()
    }

    private fun intToLE(v: Int): ByteArray = byteArrayOf(
        (v and 0xff).toByte(),
        ((v shr 8) and 0xff).toByte(),
        ((v shr 16) and 0xff).toByte(),
        ((v shr 24) and 0xff).toByte()
    )

    private fun shortToLE(v: Int): ByteArray = byteArrayOf(
        (v and 0xff).toByte(),
        ((v shr 8) and 0xff).toByte()
    )

    private fun transcribeSync(wav: ByteArray): String? {
        val prefs: SharedPreferences = getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val serverUrl = prefs.getString(PREF_URL, null) ?: return null
        val apiKey = prefs.getString(PREF_KEY, "") ?: ""
        val sttUrl = serverUrl.replace(Regex(":\\d+$"), ":8643") +
            "/v1/audio/transcriptions"

        return try {
            val boundary = "----HermesBoundary${System.currentTimeMillis()}"
            val conn = (URL(sttUrl).openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                doOutput = true
                connectTimeout = 5000
                readTimeout = 15000
                setRequestProperty("Authorization", "Bearer $apiKey")
                setRequestProperty(
                    "Content-Type",
                    "multipart/form-data; boundary=$boundary"
                )
            }

            DataOutputStream(conn.outputStream).use { out ->
                out.writeBytes("--$boundary\r\n")
                out.writeBytes("Content-Disposition: form-data; name=\"language\"\r\n\r\n")
                out.writeBytes("ru\r\n")
                out.writeBytes("--$boundary\r\n")
                out.writeBytes("Content-Disposition: form-data; name=\"file\"; filename=\"voice.wav\"\r\n")
                out.writeBytes("Content-Type: audio/wav\r\n\r\n")
                out.write(wav)
                out.writeBytes("\r\n--$boundary--\r\n")
                out.flush()
            }

            if (conn.responseCode == 200) {
                val resp = conn.inputStream.bufferedReader().readText()
                // Используем JSONObject вместо ручного regex — он сам декодирует \uXXXX
                try {
                    JSONObject(resp).optString("text", "")
                } catch (e: Exception) {
                    android.util.Log.e("HermesListener", "STT json parse err: ${e.message}")
                    null
                }
            } else {
                android.util.Log.e(
                    "HermesListener",
                    "STT ${conn.responseCode}: ${conn.errorStream?.bufferedReader()?.readText()}"
                )
                null
            }
        } catch (e: Exception) {
            android.util.Log.e("HermesListener", "STT err: ${e.message}")
            null
        }
    }

    private fun sendDebugToFlutter(text: String) {
        val engine = FlutterEngineCache.getInstance().get("main_engine") ?: return
        val channel = MethodChannel(
            engine.dartExecutor.binaryMessenger, FLUTTER_CHANNEL
        )
        android.os.Handler(mainLooper).post {
            channel.invokeMethod("debug_heard", text)
        }
    }

    /// Прокинуть реплику голосового диалога в Flutter-чат, чтобы голос и текст
    /// складывались в одну общую ленту (одна сессия phone-misha-main).
    private fun sendChatToFlutter(role: String, content: String) {
        val engine = FlutterEngineCache.getInstance().get("main_engine") ?: return
        val channel = MethodChannel(
            engine.dartExecutor.binaryMessenger, FLUTTER_CHANNEL
        )
        val payload = HashMap<String, Any>()
        payload["role"] = role
        payload["content"] = content
        android.os.Handler(mainLooper).post {
            channel.invokeMethod("voice_message", payload)
        }
    }

    private fun notifyFlutter(event: String) {
        val engine = FlutterEngineCache.getInstance().get("main_engine")
        if (engine != null) {
            val channel = MethodChannel(
                engine.dartExecutor.binaryMessenger, FLUTTER_CHANNEL
            )
            android.os.Handler(mainLooper).post {
                channel.invokeMethod(event, null)
            }
        }

        // Всегда поднимаем UI — даже если engine ещё не создан или приложение свернуто
        val launchIntent = Intent(this, MainActivity::class.java).apply {
            addFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK or
                    Intent.FLAG_ACTIVITY_REORDER_TO_FRONT or
                    Intent.FLAG_ACTIVITY_SINGLE_TOP
            )
            putExtra("wake_word_detected", true)
        }
        try {
            startActivity(launchIntent)
        } catch (e: Exception) {
            android.util.Log.e("HermesListener", "Activity start failed: ${e.message}")
        }
    }

    override fun onDestroy() {
        isRunning.set(false)
        listenerThread?.interrupt()
        wakeLock?.let { if (it.isHeld) it.release() }
        try {
            tts?.stop()
            tts?.shutdown()
        } catch (_: Exception) {}
        try { phoneBridge?.stop() } catch (_: Exception) {}
        phoneBridge = null
        try { edgeTts?.stop() } catch (_: Exception) {}
        edgeTts = null
        HermesOverlay.get(this).hide()
        super.onDestroy()
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        // Перезапустить сервис если пользователь свайпнул приложение
        val restartIntent = Intent(applicationContext, HermesListenerService::class.java)
            .apply { action = ACTION_START }
        val pi = PendingIntent.getService(
            applicationContext, 1, restartIntent,
            PendingIntent.FLAG_ONE_SHOT or PendingIntent.FLAG_IMMUTABLE
        )
        val am = getSystemService(Context.ALARM_SERVICE) as AlarmManager
        am.set(
            AlarmManager.ELAPSED_REALTIME,
            android.os.SystemClock.elapsedRealtime() + 1000,
            pi
        )
        super.onTaskRemoved(rootIntent)
    }

    private fun buildNotification(): Notification {
        val stopIntent = Intent(this, HermesListenerService::class.java).apply {
            action = ACTION_STOP
        }
        val stopPi = PendingIntent.getService(
            this, 0, stopIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val openIntent = Intent(this, MainActivity::class.java)
        val openPi = PendingIntent.getActivity(
            this, 0, openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Тройка слушает")
            .setContentText("Скажи «Тройка» чтобы активировать")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentIntent(openPi)
            .addAction(android.R.drawable.ic_delete, "Остановить", stopPi)
            .setOngoing(true)
            .setSilent(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Тройка Voice Listener",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Фоновое прослушивание wake-word"
                setShowBadge(false)
                setSound(null, null)
                enableVibration(false)
            }
            getSystemService(NotificationManager::class.java)
                ?.createNotificationChannel(channel)
        }
    }
}
