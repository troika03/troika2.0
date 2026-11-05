package com.troika.hermes_assistant

import android.app.Activity
import android.os.Handler
import android.os.Looper
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong

/** Explicit enrollment and local speaker filtering for the Flutter settings UI. */
internal class OwnerVoiceBridge(private val activity: Activity, engine: FlutterEngine,
                               private val isResumed: () -> Boolean) : AutoCloseable {
    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor()
    private val generation = AtomicLong()
    private var busy = false
    val isBusy: Boolean get() = busy
    private var resume: (() -> Unit)? = null
    private val channel = MethodChannel(engine.dartExecutor.binaryMessenger, "com.troika.hermes/owner_voice")

    init {
        channel.setMethodCallHandler { call, result ->
            when (call.method) {
                "status" -> result.success(OwnerVoiceStore.status(activity))
                "cancel" -> { cancel(); result.success(null) }
                "delete" -> {
                    cancel()
                    synchronized(SecureTokenStore) {
                        val binding = OwnerVoiceStore.binding(NativeAccountSession.eventSnapshot(activity))
                        OwnerVoiceStore.delete(activity, binding)
                    }
                    HermesListenerService.ownerVoiceChanged()
                    result.success(OwnerVoiceStore.status(activity))
                }
                "setEnabled" -> {
                    try {
                        val enabled = call.argument<Boolean>("enabled") ?: false
                        synchronized(SecureTokenStore) {
                            val identity = NativeAccountSession.eventSnapshot(activity)
                            if (enabled && (!identity.signedIn || identity.owner.isBlank())) {
                                result.error("voice_sign_in_required", "Сначала войди в аккаунт Тройки", null)
                                return@setMethodCallHandler
                            }
                            val binding = OwnerVoiceStore.binding(identity)
                            val profile = OwnerVoiceStore.load(activity, binding)
                            if (enabled && profile.samples.size != OwnerVoicePolicy.REQUIRED_SAMPLES) {
                                result.error("voice_not_enrolled", "Сначала зарегистрируй три образца голоса", null)
                            } else {
                                cancel()
                                OwnerVoiceStore.save(activity, profile.copy(enabled = enabled), binding)
                                HermesListenerService.ownerVoiceChanged()
                                result.success(OwnerVoiceStore.status(activity))
                            }
                        }
                    } catch (_: Exception) { result.error("voice_profile_failed", "Не удалось сохранить настройку голоса", null) }
                }
                "enroll" -> capture(result, enrollment = true)
                "recognize" -> capture(result, enrollment = false)
                else -> result.notImplemented()
            }
        }
    }

    private fun capture(result: MethodChannel.Result, enrollment: Boolean) {
        if (!isResumed()) {
            result.error("voice_not_visible", "Открой экран регистрации голоса", null)
            return
        }
        if (busy || MainActivity.foregroundVoiceBusy() ||
            HermesListenerService.projectReportBlocker() in setOf("dialog", "manual_dialog", "foreground_speech")) {
            result.error("voice_busy", "Сначала заверши голосовой разговор", null)
            return
        }
        val identity = NativeAccountSession.eventSnapshot(activity)
        if (enrollment && (!identity.signedIn || identity.owner.isBlank())) {
            result.error("voice_sign_in_required", "Сначала войди в аккаунт Тройки", null)
            return
        }
        val binding = OwnerVoiceStore.binding(identity)
        val profile = OwnerVoiceStore.load(activity, binding)
        val profileRevision = OwnerVoiceStore.revision
        if (profile.enabled && profile.samples.size != OwnerVoicePolicy.REQUIRED_SAMPLES) {
            result.error("voice_profile_invalid", "Профиль голоса повреждён. Удали его и зарегистрируй голос заново", null)
            return
        }
        if (enrollment && profile.samples.size >= OwnerVoicePolicy.REQUIRED_SAMPLES) {
            result.error("voice_enrolled", "Голос уже зарегистрирован. Удали профиль для новой регистрации", null)
            return
        }
        busy = true
        val ticket = generation.incrementAndGet()
        fun current() = isResumed() && generation.get() == ticket && OwnerVoiceStore.revision == profileRevision &&
            NativeAccountSession.currentEvent(activity, identity)
        val start = {
            worker.execute {
                var failure: String? = null
                var text: String? = null
                try {
                    if (current()) {
                        val captured = OwnerVoiceCapture(activity).capture(enrollment, ::current)
                        if (current() && enrollment) {
                            if (captured == null || captured.frames < OwnerVoicePolicy.MIN_FRAMES) {
                                failure = "Скажи одну фразу не короче четырёх секунд"
                            } else if (!OwnerVoicePolicy.acceptsSample(profile.samples, captured.vector, captured.frames)) {
                                failure = "Голос отличается от предыдущих образцов. Повтори в тихом месте"
                            } else {
                                synchronized(SecureTokenStore) {
                                    if (current()) OwnerVoiceStore.save(activity, OwnerVoiceStore.Profile(profile.samples + listOf(captured.vector)), binding)
                                }
                            }
                        } else if (current()) text = OwnerVoiceCapture.verifiedText(activity, captured, binding)
                    }
                } catch (error: SecurityException) { failure = "Разреши доступ к микрофону" }
                catch (_: Exception) { failure = "Не удалось проверить голос. Повтори фразу не короче четырёх секунд" }
                main.post {
                    busy = false
                    resume?.invoke(); resume = null
                    when {
                        generation.get() != ticket || !NativeAccountSession.currentEvent(activity, identity) -> result.error("voice_cancelled", "Запись отменена", null)
                        failure != null -> result.error("voice_sample_rejected", failure, null)
                        enrollment -> result.success(OwnerVoiceStore.status(activity))
                        else -> result.success(if (OwnerVoiceStore.revision == profileRevision) text else null)
                    }
                }
            }
        }
        resume = HermesListenerService.pauseForForegroundSpeech {
            if (current()) start() else {
                busy = false
                resume?.invoke(); resume = null
                result.error("voice_cancelled", "Запись отменена", null)
            }
        }
        if (resume == null) start()
    }

    fun cancel() {
        generation.incrementAndGet()
        if (busy) OwnerVoiceCapture.cancelActive()
        // The capture worker releases the microphone before resuming wake.
    }

    override fun close() { cancel(); channel.setMethodCallHandler(null); worker.shutdown() }
}
