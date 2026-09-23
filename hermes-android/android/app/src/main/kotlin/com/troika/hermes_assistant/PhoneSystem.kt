package com.troika.hermes_assistant

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.hardware.camera2.CameraManager
import android.media.AudioManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.BatteryManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.util.Base64
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File

/**
 * Системные операции телефона: буфер обмена, фонарик, батарея, сеть, и т.д.
 */
object PhoneSystem {
    private const val TAG = "PhoneSystem"

    // ---- Clipboard ---------------------------------------------------------

    fun clipboardGet(ctx: Context): JSONObject {
        val cm = ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        // Чтение clipboard требует чтобы наше app было input method или foreground app
        // на современном Android. Делаем на main thread (требование API).
        return runOnMain {
            try {
                val clip = cm.primaryClip
                if (clip == null || clip.itemCount == 0) {
                    JSONObject().apply { put("ok", true); put("text", "") }
                } else {
                    val sb = StringBuilder()
                    for (i in 0 until clip.itemCount) {
                        clip.getItemAt(i).coerceToText(ctx)?.let { sb.append(it) }
                    }
                    JSONObject().apply {
                        put("ok", true)
                        put("text", sb.toString())
                    }
                }
            } catch (e: SecurityException) {
                JSONObject().apply {
                    put("ok", false)
                    put("error", "clipboard_blocked: Android requires app to be foreground or input-method to read clipboard. Use clipboard_set instead, or bring Troika UI to front first.")
                }
            }
        }
    }

    fun clipboardSet(ctx: Context, text: String): JSONObject {
        val cm = ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        return runOnMain {
            try {
                cm.setPrimaryClip(ClipData.newPlainText("Troika", text))
                JSONObject().apply { put("ok", true); put("length", text.length) }
            } catch (e: Exception) {
                JSONObject().apply { put("ok", false); put("error", e.message ?: "clipboard_set_failed") }
            }
        }
    }

    // ---- Torch -------------------------------------------------------------

    private var torchOn = false

    fun torch(ctx: Context, on: Boolean): JSONObject {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            return JSONObject().apply { put("ok", false); put("error", "requires Android 6+") }
        }
        return try {
            val cm = ctx.getSystemService(Context.CAMERA_SERVICE) as CameraManager
            val cameraId = cm.cameraIdList.firstOrNull { id ->
                cm.getCameraCharacteristics(id)
                    .get(android.hardware.camera2.CameraCharacteristics.FLASH_INFO_AVAILABLE) == true
            } ?: return JSONObject().apply { put("ok", false); put("error", "no_flash") }
            cm.setTorchMode(cameraId, on)
            torchOn = on
            JSONObject().apply { put("ok", true); put("on", on) }
        } catch (e: Exception) {
            JSONObject().apply { put("ok", false); put("error", e.message ?: "torch_failed") }
        }
    }

    fun torchToggle(ctx: Context): JSONObject = torch(ctx, !torchOn)

    // ---- Battery -----------------------------------------------------------

    fun battery(ctx: Context): JSONObject {
        val bm = ctx.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
        val level = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        val status = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_STATUS)
        val plugged = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            try { bm.computeChargeTimeRemaining() } catch (_: Exception) { -1L }
        } else -1L

        val statusName = when (status) {
            BatteryManager.BATTERY_STATUS_CHARGING -> "charging"
            BatteryManager.BATTERY_STATUS_DISCHARGING -> "discharging"
            BatteryManager.BATTERY_STATUS_FULL -> "full"
            BatteryManager.BATTERY_STATUS_NOT_CHARGING -> "not_charging"
            else -> "unknown"
        }
        return JSONObject().apply {
            put("ok", true)
            put("level_percent", level)
            put("status", statusName)
            if (plugged > 0) put("time_to_full_ms", plugged)
        }
    }

    // ---- Network -----------------------------------------------------------

    fun network(ctx: Context): JSONObject {
        val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val active = cm.activeNetwork
        if (active == null) {
            return JSONObject().apply { put("ok", true); put("connected", false) }
        }
        val caps = cm.getNetworkCapabilities(active)
        val transport = when {
            caps == null -> "unknown"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_BLUETOOTH) -> "bluetooth"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN) -> "vpn"
            else -> "other"
        }
        val result = JSONObject().apply {
            put("ok", true)
            put("connected", true)
            put("transport", transport)
            put("has_internet", caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) ?: false)
            put("validated", caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) ?: false)
        }
        if (transport == "wifi") {
            try {
                val wm = ctx.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
                val info = wm.connectionInfo
                if (info != null) {
                    result.put("wifi_ssid", info.ssid?.trim('"'))
                    result.put("wifi_rssi_dbm", info.rssi)
                    result.put("wifi_speed_mbps", info.linkSpeed)
                }
            } catch (_: Exception) {}
        }
        return result
    }

    // ---- Camera (фото) -----------------------------------------------------
    // Получить фото с фронт/тыл камеры — открываем системную камеру в режиме capture.
    // Сохраняем новые снимки в Pictures/Troika и возвращаем путь.

    fun cameraTakePhoto(ctx: Context, frontFacing: Boolean = false): JSONObject {
        // Через intent ACTION_IMAGE_CAPTURE — пользователь нажимает кнопку спуска.
        // Без UI-интервенции сделать снимок нельзя без CAMERA permission и сложного кода.
        return try {
            val dir = File(android.os.Environment.getExternalStoragePublicDirectory(
                android.os.Environment.DIRECTORY_PICTURES), "Troika")
            dir.mkdirs()
            val file = File(dir, "photo_${System.currentTimeMillis()}.jpg")
            val uri = androidx.core.content.FileProvider.getUriForFile(
                ctx, "${ctx.packageName}.fileprovider", file
            )

            val intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE).apply {
                putExtra(MediaStore.EXTRA_OUTPUT, uri)
                if (frontFacing) {
                    putExtra("android.intent.extras.CAMERA_FACING", 1)
                    putExtra("android.intent.extras.LENS_FACING_FRONT", 1)
                    putExtra("android.intent.extra.USE_FRONT_CAMERA", true)
                }
                addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            ctx.startActivity(intent)
            JSONObject().apply {
                put("ok", true)
                put("message", "Camera opened — user must tap shutter")
                put("expected_path", file.absolutePath)
            }
        } catch (e: Exception) {
            JSONObject().apply { put("ok", false); put("error", e.message ?: "camera_failed") }
        }
    }

    // ---- Helpers -----------------------------------------------------------

    /** Выполнить блок на main thread синхронно. */
    private fun <T> runOnMain(block: () -> T): T {
        if (Looper.myLooper() == Looper.getMainLooper()) return block()
        val handler = Handler(Looper.getMainLooper())
        val result = arrayOfNulls<Any>(1)
        val latch = java.util.concurrent.CountDownLatch(1)
        handler.post {
            try {
                @Suppress("UNCHECKED_CAST")
                result[0] = block()
            } catch (e: Exception) {
                Log.e(TAG, "runOnMain block error: ${e.message}")
            } finally {
                latch.countDown()
            }
        }
        latch.await(5, java.util.concurrent.TimeUnit.SECONDS)
        @Suppress("UNCHECKED_CAST")
        return result[0] as T
    }
}
