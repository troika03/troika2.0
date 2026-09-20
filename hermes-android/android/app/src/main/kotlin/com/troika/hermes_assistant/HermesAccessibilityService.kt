package com.troika.hermes_assistant

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.DisplayMetrics
import android.util.Log
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONArray
import org.json.JSONObject

/**
 * Сервис специальных возможностей — даёт Hermes доступ к UI любого приложения.
 * Пользователь включает его в Настройках → Спец. возможности → Hermes.
 *
 * Возможности:
 *  - читать содержимое экрана (текст, content-description, координаты)
 *  - нажимать на элемент по тексту/описанию/координатам
 *  - вводить текст в активное поле
 *  - свайпы и кнопки back/home
 */
class HermesAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "HermesA11y"
        @Volatile var instance: HermesAccessibilityService? = null
            private set
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        Log.i(TAG, "Accessibility service connected")
    }

    override fun onDestroy() {
        if (instance === this) instance = null
        Log.i(TAG, "Accessibility service destroyed")
        super.onDestroy()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // Мы потребляем события только по запросу (через rootInActiveWindow), не реактивно
    }

    override fun onInterrupt() {}

    // -----------------------------------------------------------------
    // Публичные методы для PhoneCommandExecutor
    // -----------------------------------------------------------------

    fun tapOn(params: JSONObject): JSONObject {
        val text = params.optString("text")
        val desc = params.optString("desc")
        val x = if (params.has("x") && !params.isNull("x")) params.optInt("x") else -1
        val y = if (params.has("y") && !params.isNull("y")) params.optInt("y") else -1

        if (x >= 0 && y >= 0) {
            return if (clickAt(x.toFloat(), y.toFloat())) ok("tap at ($x,$y)")
            else err("gesture_failed at ($x,$y)")
        }

        val root = rootInActiveWindow ?: return err("no_active_window")
        val node = findClickableByText(root, text) ?: findClickableByDesc(root, desc)
            ?: return err("element_not_found")
        return if (clickNode(node)) ok("tapped: ${nodeLabel(node)}")
        else err("click_failed: ${nodeLabel(node)}")
    }

    fun typeText(text: String): JSONObject {
        if (text.isEmpty()) return err("empty_text")
        val root = rootInActiveWindow ?: return err("no_active_window")
        val focused = findFocused(root) ?: return err("no_focused_input")
        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        val performed = focused.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
        return if (performed) ok("typed: $text") else err("set_text_failed")
    }

    fun swipe(direction: String): JSONObject {
        val (w, h) = screenSize()
        val cx = w / 2f
        val cy = h / 2f
        val (sx, sy, ex, ey) = when (direction.lowercase()) {
            "up" -> Quad(cx, h * 0.7f, cx, h * 0.3f)
            "down" -> Quad(cx, h * 0.3f, cx, h * 0.7f)
            "left" -> Quad(w * 0.7f, cy, w * 0.3f, cy)
            "right" -> Quad(w * 0.3f, cy, w * 0.7f, cy)
            else -> return err("bad direction: $direction")
        }
        val path = Path().apply {
            moveTo(sx, sy)
            lineTo(ex, ey)
        }
        val stroke = GestureDescription.StrokeDescription(path, 0, 250)
        val gesture = GestureDescription.Builder().addStroke(stroke).build()
        val dispatched = dispatchGesture(gesture, null, null)
        return if (dispatched) ok("swipe $direction") else err("dispatch_failed")
    }

    fun pressBack(): JSONObject {
        return if (performGlobalAction(GLOBAL_ACTION_BACK)) ok("back") else err("back_failed")
    }

    fun pressHome(): JSONObject {
        return if (performGlobalAction(GLOBAL_ACTION_HOME)) ok("home") else err("home_failed")
    }

    fun pressRecents(): JSONObject {
        return if (performGlobalAction(GLOBAL_ACTION_RECENTS)) ok("recents") else err("recents_failed")
    }

    fun openNotifications(): JSONObject {
        return if (performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS)) {
            ok("notifications")
        } else {
            err("notifications_failed")
        }
    }

    /**
     * Сделать скриншот текущего экрана через AccessibilityService API (Android 11+).
     * Возвращает base64-PNG в поле "image".
     */
    fun takeScreenshot(): JSONObject {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            return err("requires Android 11+ for accessibility screenshot")
        }
        val latch = java.util.concurrent.CountDownLatch(1)
        val resultRef = arrayOfNulls<JSONObject>(1)
        try {
            takeScreenshot(
                android.view.Display.DEFAULT_DISPLAY,
                mainExecutor,
                object : android.accessibilityservice.AccessibilityService.TakeScreenshotCallback {
                    override fun onSuccess(screenshot: android.accessibilityservice.AccessibilityService.ScreenshotResult) {
                        try {
                            val buffer = screenshot.hardwareBuffer
                            val bitmap = android.graphics.Bitmap.wrapHardwareBuffer(
                                buffer, screenshot.colorSpace
                            )
                            if (bitmap == null) {
                                resultRef[0] = err("wrap_hardware_buffer_returned_null")
                                latch.countDown()
                                return
                            }
                            // Конвертируем в software bitmap для кодирования
                            val software = bitmap.copy(android.graphics.Bitmap.Config.ARGB_8888, false)
                            buffer.close()
                            val baos = java.io.ByteArrayOutputStream()
                            software.compress(android.graphics.Bitmap.CompressFormat.PNG, 90, baos)
                            val data = baos.toByteArray()
                            software.recycle()
                            resultRef[0] = JSONObject().apply {
                                put("ok", true)
                                put("encoding", "base64")
                                put("format", "png")
                                put("size", data.size)
                                put("image", android.util.Base64.encodeToString(data, android.util.Base64.NO_WRAP))
                            }
                        } catch (e: Exception) {
                            resultRef[0] = err("screenshot_encode_failed: ${e.message}")
                        } finally {
                            latch.countDown()
                        }
                    }
                    override fun onFailure(errorCode: Int) {
                        resultRef[0] = err("screenshot_failed: code=$errorCode")
                        latch.countDown()
                    }
                }
            )
            latch.await(10, java.util.concurrent.TimeUnit.SECONDS)
            return resultRef[0] ?: err("screenshot_timeout")
        } catch (e: Exception) {
            return err("screenshot_error: ${e.message}")
        }
    }

    fun readScreen(): JSONObject {
        val root = rootInActiveWindow ?: return err("no_active_window")
        val elements = JSONArray()
        traverse(root, elements, depth = 0)
        val pkg = root.packageName?.toString() ?: ""
        return JSONObject().apply {
            put("ok", true)
            put("package", pkg)
            put("elements", elements)
        }
    }

    /** Package only, used locally to block sensitive screens before capture. */
    fun activePackageName(): String? = rootInActiveWindow?.packageName?.toString()

    /** Fail-closed local check; collected text is never returned or logged. */
    fun hasSensitiveContentOnScreen(): Boolean {
        val root = rootInActiveWindow ?: return true
        val text = StringBuilder()
        fun collect(node: AccessibilityNodeInfo?, depth: Int): Boolean {
            if (node == null || depth > 40) return false
            if (node.isPassword) return true
            if (text.length < 16_000) {
                node.text?.let { text.append(' ').append(it) }
                node.contentDescription?.let { text.append(' ').append(it) }
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    node.hintText?.let { text.append(' ').append(it) }
                }
            }
            for (index in 0 until node.childCount) {
                if (collect(node.getChild(index), depth + 1)) return true
            }
            return false
        }
        if (collect(root, 0)) return true
        val visible = text.toString().lowercase()
        val sensitiveLabels = listOf(
            "verification code", "one-time code", "one time code", "otp",
            "код подтверждения", "одноразовый код", "cvc", "cvv",
            "recovery phrase", "seed phrase", "private key",
            "фраза восстановления", "секретный ключ",
        )
        if (sensitiveLabels.any(visible::contains)) return true
        val digits = visible.replace(Regex("[\\s-]"), "")
        return Regex("(?<!\\d)\\d{13,19}(?!\\d)").containsMatchIn(digits)
    }

    // -----------------------------------------------------------------
    // Internals
    // -----------------------------------------------------------------

    private fun clickAt(x: Float, y: Float): Boolean {
        val path = Path().apply { moveTo(x, y) }
        val stroke = GestureDescription.StrokeDescription(path, 0, 50)
        val gesture = GestureDescription.Builder().addStroke(stroke).build()
        return dispatchGesture(gesture, null, null)
    }

    private fun clickNode(node: AccessibilityNodeInfo): Boolean {
        // Поднимаемся до clickable-предка
        var n: AccessibilityNodeInfo? = node
        while (n != null && !n.isClickable) {
            n = n.parent
        }
        val target = n ?: node
        return target.performAction(AccessibilityNodeInfo.ACTION_CLICK)
    }

    private fun findClickableByText(node: AccessibilityNodeInfo?, text: String): AccessibilityNodeInfo? {
        if (node == null || text.isBlank()) return null
        val q = text.lowercase()
        if (matchesText(node, q)) return node
        for (i in 0 until node.childCount) {
            val found = findClickableByText(node.getChild(i), text)
            if (found != null) return found
        }
        return null
    }

    private fun findClickableByDesc(node: AccessibilityNodeInfo?, desc: String): AccessibilityNodeInfo? {
        if (node == null || desc.isBlank()) return null
        val q = desc.lowercase()
        val nd = node.contentDescription?.toString()?.lowercase() ?: ""
        if (nd.contains(q)) return node
        for (i in 0 until node.childCount) {
            val found = findClickableByDesc(node.getChild(i), desc)
            if (found != null) return found
        }
        return null
    }

    private fun findFocused(node: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        if (node == null) return null
        if (node.isFocused && node.isEditable) return node
        if (node.isAccessibilityFocused && node.isEditable) return node
        // Через системный API
        val f = findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
        if (f != null && f.isEditable) return f
        for (i in 0 until node.childCount) {
            val r = findFocused(node.getChild(i))
            if (r != null) return r
        }
        return null
    }

    private fun matchesText(node: AccessibilityNodeInfo, q: String): Boolean {
        val t = node.text?.toString()?.lowercase() ?: ""
        if (t == q || t.contains(q)) return true
        val d = node.contentDescription?.toString()?.lowercase() ?: ""
        if (d == q || d.contains(q)) return true
        return false
    }

    private fun nodeLabel(node: AccessibilityNodeInfo): String {
        return node.text?.toString()
            ?: node.contentDescription?.toString()
            ?: node.viewIdResourceName
            ?: "<unnamed>"
    }

    private fun traverse(node: AccessibilityNodeInfo?, out: JSONArray, depth: Int) {
        if (node == null || depth > 30 || out.length() > 200) return
        val text = node.text?.toString() ?: ""
        val desc = node.contentDescription?.toString() ?: ""
        if (text.isNotEmpty() || desc.isNotEmpty() || node.isClickable) {
            val rect = Rect()
            node.getBoundsInScreen(rect)
            val item = JSONObject().apply {
                if (text.isNotEmpty()) put("text", text)
                if (desc.isNotEmpty()) put("desc", desc)
                if (node.isClickable) put("clickable", true)
                if (node.isEditable) put("editable", true)
                put("bounds", JSONObject().apply {
                    put("x", rect.centerX())
                    put("y", rect.centerY())
                    put("w", rect.width())
                    put("h", rect.height())
                })
            }
            out.put(item)
        }
        for (i in 0 until node.childCount) {
            traverse(node.getChild(i), out, depth + 1)
        }
    }

    private fun screenSize(): Pair<Int, Int> {
        val wm = getSystemService(WINDOW_SERVICE) as WindowManager
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            val bounds = wm.currentWindowMetrics.bounds
            Pair(bounds.width(), bounds.height())
        } else {
            val dm = DisplayMetrics()
            @Suppress("DEPRECATION")
            wm.defaultDisplay.getRealMetrics(dm)
            Pair(dm.widthPixels, dm.heightPixels)
        }
    }

    private fun ok(message: String) = JSONObject().apply {
        put("ok", true); put("message", message)
    }

    private fun err(msg: String) = JSONObject().apply {
        put("ok", false); put("error", msg)
    }

    private data class Quad(val a: Float, val b: Float, val c: Float, val d: Float)
}
