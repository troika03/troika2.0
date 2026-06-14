package com.troika.hermes_assistant

import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.os.Build
import android.provider.Settings
import org.json.JSONArray
import org.json.JSONObject

/**
 * Лёгкий сборщик контекста устройства для подсказки серверу про "где я".
 * Минимум разрешений: то что доступно без FINE_LOCATION или BLUETOOTH_CONNECT runtime grant.
 *
 * Поля JSON:
 *   bssid          — MAC точки доступа Wi-Fi (доступно только если уже выдан FINE_LOCATION)
 *   ssid           — имя сети (тоже под FINE_LOCATION на Android 10+)
 *   network_type   — wifi / cellular / ethernet / none
 *   bluetooth      — массив имён связанных bonded устройств (если разрешён доступ)
 *   device_name    — Build.MODEL для дебага
 */
object DeviceContext {

    fun build(ctx: Context): JSONObject {
        val out = JSONObject()
        try {
            out.put("device_name", Build.MODEL ?: "")
            out.put("network_type", networkType(ctx))

            // Wi-Fi BSSID/SSID — без FINE_LOCATION оба придут "<unknown ssid>" / "02:00..." на новых
            // Android; пишем как есть, сервер сам решит подходит ли как fingerprint.
            try {
                val wm = ctx.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
                val info = wm?.connectionInfo
                val bssid = info?.bssid
                if (!bssid.isNullOrBlank() && bssid != "02:00:00:00:00:00") {
                    out.put("bssid", bssid)
                }
                val ssid = info?.ssid?.trim('"')
                if (!ssid.isNullOrBlank() && ssid != "<unknown ssid>") {
                    out.put("ssid", ssid)
                }
            } catch (_: SecurityException) {
                // нет разрешения — игнор, маппинг будет по bluetooth + network_type
            } catch (_: Exception) {}

            // Bluetooth: bonded devices (paired). Не требует FINE_LOCATION,
            // но на Android 12+ требует BLUETOOTH_CONNECT. Если permission
            // нет — getBondedDevices бросает SecurityException, ловим и идём дальше.
            val bt = JSONArray()
            try {
                val adapter: BluetoothAdapter? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                    val bm = ctx.applicationContext.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
                    bm?.adapter
                } else {
                    @Suppress("DEPRECATION")
                    BluetoothAdapter.getDefaultAdapter()
                }
                val bonded = adapter?.bondedDevices
                if (bonded != null) {
                    for (d in bonded) {
                        val n = try { d.name } catch (_: SecurityException) { null }
                        if (!n.isNullOrBlank()) bt.put(n)
                    }
                }
            } catch (_: SecurityException) {
            } catch (_: Exception) {}
            out.put("bluetooth", bt)
        } catch (_: Exception) {}
        return out
    }

    private fun networkType(ctx: Context): String {
        return try {
            val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
                ?: return "unknown"
            val net = cm.activeNetwork ?: return "none"
            val caps = cm.getNetworkCapabilities(net) ?: return "none"
            when {
                caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
                caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
                caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
                else -> "other"
            }
        } catch (_: Exception) { "unknown" }
    }

    /** Безопасный header value — JSON в одну строку, обрезка до 4 КБ. */
    fun asHeaderValue(ctx: Context): String {
        val s = build(ctx).toString()
        return if (s.length > 3500) s.substring(0, 3500) else s
    }
}
