package com.troika.hermes_assistant

import android.app.*
import android.content.*
import android.content.pm.ServiceInfo
import android.media.AudioManager
import android.os.*
import android.util.Log
import androidx.core.app.NotificationCompat
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.InputStream
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/** Device-only handoff worker. It never records the microphone or executes project code. */
class DevelopmentService : Service() {
    companion object {
        private const val CHANNEL = "troika_development"
        private const val NOTIFICATION = 1045
        @Volatile private var current: DevelopmentService? = null
        @Volatile var foregroundUntil = 0L
        @Volatile var running = false
        fun interruptReport() { current?.let { it.reportInterrupted=true; it.voice?.stop() } }
        fun uiLease() { foregroundUntil = SystemClock.elapsedRealtime()+20000; interruptReport() }
        fun hash(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    }
    @Volatile private var alive = true
    @Volatile private var voice: EdgeTtsPlayer? = null
    @Volatile private var reportInterrupted = false
    private var lastDiagnostic = ""
    private var requestStage = "idle"
    private var responseStatus = 0
    /** Fixed state codes only: never log requests, titles, source, tokens or audio. */
    private fun diagnostic(state: String) {
        if (state != lastDiagnostic) {
            Log.i("TroikaDevelopment", state)
            lastDiagnostic = state
        }
    }
    private val preferences by lazy { getSharedPreferences("FlutterSharedPreferences", MODE_PRIVATE) }
    private val settings by lazy { getSharedPreferences("troika_development_worker", MODE_PRIVATE) }
    private val main = Handler(Looper.getMainLooper())
    override fun onBind(intent: Intent?) = null
    override fun onCreate() {
        super.onCreate(); current = this; running = true
        diagnostic("worker_started")
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL, "Проекты Тройки", NotificationManager.IMPORTANCE_LOW))
        notifyState("Проекты работают в фоне")
        thread(name="TroikaProjectObserver", isDaemon=true) {
            while (alive) {
                try {
                    if (SystemClock.elapsedRealtime() >= foregroundUntil) poll()
                    else diagnostic("worker_waiting_foreground")
                }
                catch (error: Exception) {
                    val line = error.stackTrace.firstOrNull { it.className == DevelopmentService::class.java.name }?.lineNumber ?: 0
                    diagnostic("worker_error:$requestStage:$responseStatus:${error.javaClass.simpleName}:line=$line")
                    main.post { if (alive) notifyState("Нужно внимание. Откройте Тройку для продолжения.") }
                }
                repeat(40) { if (alive) Thread.sleep(250) }
            }
        }
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == "disable") {
            val owner = settings.getString("owner", "").orEmpty()
            preferences.edit().putBoolean("flutter.project_background:$owner", false).apply()
            settings.edit().putBoolean("enabled", false).apply(); stopSelf()
        }
        if (intent?.action == "quiet") interruptReport()
        return START_NOT_STICKY
    }
    override fun onDestroy() {
        alive=false; voice?.stop(); voice=null; running=false; current=null
        super.onDestroy()
    }
    override fun onTimeout(startId: Int, fgsType: Int) { stopSelf() }
    private fun bounded(stream: InputStream, limit: Int): ByteArray = stream.use {
        val output=ByteArrayOutputStream(); val buffer=ByteArray(16384)
        while (true) { val count=it.read(buffer); if (count<0) break; check(output.size()+count<=limit); output.write(buffer,0,count) }
        output.toByteArray()
    }
    private fun notifyState(text: String) {
        val open = PendingIntent.getActivity(this, 1045, Intent(this, MainActivity::class.java), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        fun action(name: String, id: Int) = PendingIntent.getService(this, id, Intent(this, DevelopmentService::class.java).setAction(name), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notice = NotificationCompat.Builder(this, CHANNEL).setSmallIcon(android.R.drawable.stat_notify_sync)
            .setContentTitle("Тройка · Разработка").setContentText(text).setContentIntent(open).setOngoing(true)
            .addAction(0, "Прервать отчёт", action("quiet", 1046))
            .addAction(0, "Выключить фон", action("disable", 1047)).build()
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIFICATION, notice, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        else startForeground(NOTIFICATION, notice)
    }
    private fun owner() = preferences.getString("flutter.troika_account_email", "").orEmpty()
    private fun accountMatches(identity: String) = alive && identity.isNotBlank() && identity == owner() && settings.getString("owner", "") == identity && settings.getBoolean("enabled", false)
    private fun request(identity: String, path: String, body: JSONObject? = null, personal: Boolean = false, max: Int = 3*1024*1024): ByteArray {
        requestStage = when {
            path.endsWith("/checkpoint/received") -> "checkpoint_ack"
            path.endsWith("/checkpoint") -> "checkpoint"
            path.endsWith("/resume") -> "resume"
            path.startsWith("/v1/device-files/") -> "artifact"
            else -> "projects"
        }
        responseStatus = 0
        check(accountMatches(identity))
        val server = settings.getString("server", "").orEmpty()
        check(server == "https://api.zhulebino-teahouse.ru")
        val account = requireNotNull(NativeAccountSession.snapshot(this, server))
        check(account.owner.equals(identity, ignoreCase = true))
        val token = accessToken(identity, server)
        check(token.startsWith("trk_live_") && accountMatches(identity) && NativeAccountSession.current(this, account))
        val connection = URL(server+path).openConnection() as HttpURLConnection
        try {
            connection.instanceFollowRedirects=false; connection.connectTimeout=8000; connection.readTimeout=30000
            connection.setRequestProperty("Authorization", "Bearer $token")
            if (personal) OwnProviderSession.headers(this, server+"/v1/chat/completions", token).forEach { (key,value) -> connection.setRequestProperty(key,value) }
            check(accountMatches(identity) && NativeAccountSession.current(this, account))
            if (body != null) {
                connection.requestMethod="POST"; connection.doOutput=true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            responseStatus = connection.responseCode
            check(responseStatus in 200..299)
            val data=bounded(connection.inputStream,max)
            check(data.size <= max && accountMatches(identity) && NativeAccountSession.current(this, account)); return data
        } finally { connection.disconnect() }
    }
    private fun accessToken(identity: String, server: String): String {
        val account = requireNotNull(NativeAccountSession.snapshot(this, server))
        check(accountMatches(identity) && account.owner.equals(identity, ignoreCase = true))
        val token = NativeAccountSession.accessToken(this, account)
        check(token.startsWith("trk_live_") && NativeAccountSession.current(this, account) && accountMatches(identity))
        return token
    }
    private fun atomic(path: File, bytes: ByteArray) {
        path.parentFile!!.mkdirs(); val partial=File(path.path+".part")
        partial.outputStream().use { it.write(bytes); it.fd.sync() }
        val previous=File(path.path+".previous"); previous.delete()
        if (path.exists()) check(path.renameTo(previous))
        check(partial.renameTo(path))
    }
    private fun checkpointFile(identity: String, id: String): File {
        check(Regex("run_[a-f0-9]{32}").matches(id))
        return File(noBackupFilesDir,"development/${hash(identity.lowercase().toByteArray())}/$id.json")
    }
    private fun read(path: File): JSONObject? = try { if (path.length() in 1..2600000) JSONObject(path.readText()) else null } catch (_: Exception) { null }
    private fun poll() {
        val identity=settings.getString("owner", "").orEmpty()
        if (!accountMatches(identity)) { stopSelf(); return }
        val data=JSONObject(String(request(identity,"/v1/development/projects"),Charsets.UTF_8))
        if (!data.optBoolean("enabled")) { stopSelf(); return }
        val projects=data.optJSONArray("projects") ?: JSONArray()
        var pending=false
        for (index in 0 until projects.length()) {
            if (!accountMatches(identity) || SystemClock.elapsedRealtime()<foregroundUntil) return
            val project=projects.getJSONObject(index); val id=project.optString("project_id",project.optString("run_id"))
            val path=checkpointFile(identity,id); var local=read(path) ?: read(File(path.path+".previous"))
            val revision=project.optInt("checkpoint_revision")
            if (revision > (local?.optInt("revision") ?: 0)) {
                val value=JSONObject(String(request(identity,"/v1/development/projects/$id/checkpoint"),Charsets.UTF_8))
                val bytes=android.util.Base64.decode(value.getString("payload"),android.util.Base64.DEFAULT)
                check(hash(bytes)==value.getString("digest"))
                val checkpoint=JSONObject(String(bytes,Charsets.UTF_8)); check(checkpoint.getInt("version")==1)
                value.put("checkpoint",checkpoint).put("project_id",id).put("title",project.optString("title",local?.optString("title") ?: "Проект"))
                value.remove("payload")
                for (field in listOf("pending_instruction","pending_budget")) if (local?.has(field)==true) value.put(field,local.get(field))
                check(accountMatches(identity)); atomic(path,value.toString().toByteArray(Charsets.UTF_8)); local=value
                request(identity,"/v1/development/projects/$id/checkpoint/received",JSONObject().put("revision",revision).put("digest",value.getString("digest")))
            }
            val state=project.optString("status")
            if (local!=null && local.optInt("revision")==revision && project.optInt("checkpoint_confirmed")<revision) {
                request(identity,"/v1/development/projects/$id/checkpoint/received",JSONObject().put("revision",revision).put("digest",local.getString("digest")))
            }
            if (local!=null && (state=="interrupted" || state=="paused" && local.has("pending_instruction"))) {
                pending=true
                val instruction=local.optString("pending_instruction")
                val key="resume-"+hash("$id:$revision:$instruction:${local.optInt("pending_budget")}".toByteArray())
                request(identity,"/v1/development/projects/$id/resume",JSONObject().put("checkpoint",local.getJSONObject("checkpoint"))
                    .put("revision",local.getInt("revision")).put("title",local.optString("title"))
                    .put("instruction",instruction).put("reuse_budget",!local.has("pending_instruction"))
                    .put("budget_tokens",local.optInt("pending_budget",100000)).put("idempotency_key",key),personal=true)
                local.remove("pending_instruction"); local.remove("pending_budget"); atomic(path,local.toString().toByteArray(Charsets.UTF_8))
            }
            if (state !in setOf("completed","failed","cancelled","paused","waiting_budget","interrupted")) pending=true
            if (state=="completed" && project.optJSONObject("artifact")!=null) receive(identity,project.getJSONObject("artifact"))
            val reports=project.optJSONArray("reports") ?: JSONArray()
            if (reports.length()>0) {
                // Background wakeup announces the latest meaningful state, without replaying a backlog.
                val report=reports.getJSONObject(reports.length()-1)
                val key=project.optString("run_id")+":"+report.optString("id")
                val seen=settings.getStringSet("seen:$identity",emptySet()).orEmpty()
                if (key !in seen && preferences.getBoolean("flutter.project_voice:$identity",true)) {
                    pending=true
                    if (speak(identity,local?.optString("title") ?: project.optString("title"),report.optString("text"),hash(key.toByteArray()).take(16))) {
                        settings.edit().putStringSet("seen:$identity",(seen+key).toList().takeLast(400).toSet()).apply()
                    }
                } else {
                    diagnostic(if (key in seen) "report_already_seen" else "report_voice_disabled")
                }
            }
        }
        if (!pending) stopSelf()
    }
    private fun receive(identity: String, artifact: JSONObject) {
        val id=artifact.getString("id"); val kind=artifact.getString("kind")
        check(Regex("[a-zA-Z0-9_-]{8,100}").matches(id) && kind in setOf("zip","pptx","docx","pdf"))
        val configured=File(settings.getString("files_root", "").orEmpty()).canonicalFile
        val privateRoot=File(applicationInfo.dataDir).canonicalFile
        check(configured.path.startsWith(privateRoot.path+File.separator) && configured.name==hash(identity.lowercase().toByteArray()))
        val target=File(configured,"$id.$kind"); val meta=File(target.path+".metadata.json")
        if (target.exists() && meta.exists() && hash(target.readBytes())==artifact.optString("sha256")) {
            try { request(identity,"/v1/device-files/$id/received",JSONObject()) } catch (_: Exception) { /* Verified local bytes remain available after a lost ACK. */ }
            return
        }
        val size=artifact.getInt("size"); check(size in 1..(50*1024*1024))
        val bytes=request(identity,"/v1/device-files/$id",max=size)
        check(bytes.size==size && hash(bytes)==artifact.getString("sha256"))
        check(accountMatches(identity)); atomic(target,bytes)
        atomic(meta,JSONObject(artifact.toString()).put("local_path",target.path).toString().toByteArray(Charsets.UTF_8))
        try { request(identity,"/v1/device-files/$id/received",JSONObject()) } catch (_: Exception) { /* The durable local copy comes before ACK. */ }
    }
    private fun speak(identity: String, title: String, text: String, reference: String): Boolean {
        if (text.isBlank() || !accountMatches(identity)) return false
        if (SystemClock.elapsedRealtime()<foregroundUntil) { diagnostic("report_waiting_foreground"); return false }
        val blocker = HermesListenerService.projectReportBlocker()
        if (blocker != null) { diagnostic("report_waiting_$blocker"); return false }
        val audio=getSystemService(AUDIO_SERVICE) as AudioManager
        val focus=AudioManager.OnAudioFocusChangeListener { if (it<0) interruptReport() }
        @Suppress("DEPRECATION") val granted=audio.requestAudioFocus(focus,AudioManager.STREAM_MUSIC,AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
        if (granted!=AudioManager.AUDIOFOCUS_REQUEST_GRANTED) { diagnostic("report_waiting_audio_focus"); return false }
        val finished=CountDownLatch(1); var success=false
        try {
            val server=settings.getString("server", "").orEmpty(); val token=accessToken(identity,server)
            check(accountMatches(identity) && SystemClock.elapsedRealtime()>=foregroundUntil)
            val account = requireNotNull(NativeAccountSession.snapshot(this, server))
            check(account.owner.equals(identity, ignoreCase = true))
            val player=EdgeTtsPlayer(this,server,token,preferences.getString("flutter.hermes_edge_voice","ru-RU-SvetlanaNeural")!!,
                expectedIdentity = account)
            reportInterrupted=false; voice=player
            diagnostic("report_synthesizing:$reference")
            main.post {
                if (accountMatches(identity) && SystemClock.elapsedRealtime()>=foregroundUntil && HermesListenerService.projectReportMaySpeak()) {
                    if (HermesListenerService.serviceActive) startService(Intent(this,HermesListenerService::class.java).setAction(HermesListenerService.ACTION_PAUSE_WAKE_FOR_FOREGROUND_SPEECH))
                    player.speakWithResult("$title. $text") { completed -> success=completed; finished.countDown() }
                } else finished.countDown()
            }
            val deadline=SystemClock.elapsedRealtime()+45000
            while (!finished.await(250,TimeUnit.MILLISECONDS) && SystemClock.elapsedRealtime()<deadline) {
                if (!accountMatches(identity) || !preferences.getBoolean("flutter.project_voice:$identity",true)
                    || SystemClock.elapsedRealtime()<foregroundUntil) { interruptReport(); break }
            }
            val completed = success && !reportInterrupted && accountMatches(identity) && SystemClock.elapsedRealtime()>=foregroundUntil
            diagnostic(if (completed) "report_playback_complete:$reference" else "report_playback_incomplete:$reference")
            return completed
        } finally {
            voice?.stop(); voice=null
            if (HermesListenerService.serviceActive) startService(Intent(this,HermesListenerService::class.java).setAction(HermesListenerService.ACTION_RESUME_WAKE_AFTER_FOREGROUND_SPEECH))
            @Suppress("DEPRECATION") audio.abandonAudioFocus(focus)
        }
    }
}
