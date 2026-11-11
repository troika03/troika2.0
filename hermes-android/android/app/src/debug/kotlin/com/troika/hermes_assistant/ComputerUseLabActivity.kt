package com.troika.hermes_assistant

import android.app.Activity
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.view.View
import android.view.WindowManager
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import java.util.UUID
import java.util.concurrent.Executors

/** Disposable Android editor available only in debug builds. */
class ComputerUseLabActivity : Activity() {
    private val worker = Executors.newSingleThreadExecutor()
    private lateinit var status: TextView
    private lateinit var allow: Button
    private lateinit var stop: Button
    private var session: AndroidComputerUseSession? = null
    private var finished = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        title = "Проба управления Android"
        val padding = (20 * resources.displayMetrics.density).toInt()
        val body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(padding, padding, padding, padding)
        }
        body.addView(TextView(this).apply {
            text = "Тройка введёт пробную строку в это окно и проверит результат."
            textSize = 18f
        })
        allow = Button(this).apply {
            text = "Разрешить и запустить"
            setOnClickListener { start() }
        }
        stop = Button(this).apply {
            text = "Остановить"
            isEnabled = false
            setOnClickListener { revoke() }
        }
        status = TextView(this).apply { text = "Ожидаю разрешения." }
        val editor = object : TextView(this) {
            override fun onInitializeAccessibilityNodeInfo(info: AccessibilityNodeInfo) {
                super.onInitializeAccessibilityNodeInfo(info)
                info.className = EditText::class.java.name
                info.isEditable = true
                info.addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_SET_TEXT)
            }

            override fun performAccessibilityAction(action: Int, arguments: Bundle?): Boolean {
                if (action != AccessibilityNodeInfo.ACTION_SET_TEXT) {
                    return super.performAccessibilityAction(action, arguments)
                }
                val input = arguments?.getCharSequence(
                    AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                )?.toString() ?: return false
                if (!hasWindowFocus() || !isShown) return false
                return session?.applyWrite(input) {
                    if (text.isNotEmpty()) return@applyWrite false
                    text = input
                    true
                } ?: false
            }
        }.apply {
            id = R.id.troika_computer_lab_editor
            isSaveEnabled = false
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_YES
            minHeight = padding * 3
            textSize = 18f
        }
        body.addView(allow)
        body.addView(stop)
        body.addView(status)
        body.addView(TextView(this).apply { text = "Тестовый редактор" })
        body.addView(editor)
        setContentView(body)
    }

    private fun start() {
        if (session != null || !hasWindowFocus()) return
        val service = HermesAccessibilityService.instance
        if (service == null) {
            status.text = "Включите службу специальных возможностей Тройки на тестовом устройстве."
            return
        }
        val target = AccessibilityLabEditor(service, packageName, resources.getResourceName(R.id.troika_computer_lab_editor))
        val grant = AndroidComputerUseSession(SystemClock::elapsedRealtime, target)
        if (!grant.allow()) return
        session = grant
        allow.isEnabled = false
        stop.isEnabled = true
        status.text = "Проверяю тестовый редактор."
        worker.execute {
            val observed = grant.inspect(UUID.randomUUID())
            val observation = observed.observation
            val result = if (observation?.canWrite == true) {
                grant.write(UUID.randomUUID(), observation.id, "Пробная запись Тройки.")
            } else {
                observed
            }
            grant.stop()
            runOnUiThread {
                if (finished || isDestroyed) return@runOnUiThread
                finished = true
                stop.isEnabled = false
                status.text = if (result.status == AndroidComputerUseSession.Status.VERIFIED) {
                    "Пробная строка введена и проверена."
                } else {
                    "Ввод не подтверждён."
                }
            }
        }
    }

    private fun revoke() {
        if (session == null || finished) return
        session?.stop()
        finished = true
        stop.isEnabled = false
        status.text = "Остановлено."
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (!hasFocus) revoke()
    }

    override fun onPause() {
        revoke()
        super.onPause()
    }

    override fun onDestroy() {
        revoke()
        worker.shutdownNow()
        super.onDestroy()
    }
}

private class AccessibilityLabEditor(
    private val service: HermesAccessibilityService,
    private val packageName: String,
    private val resourceName: String,
) : AndroidComputerUseSession.Editor {
    override fun inspect(): AndroidComputerUseSession.EditorState? {
        val target = findEditor() ?: return null
        return AndroidComputerUseSession.EditorState(target.windowId, target.text.isNullOrEmpty())
    }

    override fun write(windowId: Int, text: String): Boolean {
        val target = findEditor() ?: return false
        if (target.windowId != windowId || !target.text.isNullOrEmpty()) return false
        val arguments = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        return target.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, arguments)
    }

    override fun verify(windowId: Int, text: String): Boolean {
        val target = findEditor() ?: return false
        return target.windowId == windowId && text.contentEquals(target.text)
    }

    private fun findEditor(): AccessibilityNodeInfo? {
        if (HermesAccessibilityService.instance !== service) return null
        val root = service.rootInActiveWindow ?: return null
        if (root.packageName?.toString() != packageName) return null
        val target = root.findAccessibilityNodeInfosByViewId(resourceName).singleOrNull() ?: return null
        if (!target.refresh()) return null
        return target.takeIf {
            it.packageName?.toString() == packageName && it.viewIdResourceName == resourceName &&
                it.windowId == root.windowId && it.isVisibleToUser && it.isEditable && !it.isPassword &&
                (Build.VERSION.SDK_INT < 34 || !it.isAccessibilityDataSensitive) &&
                AccessibilityNodeInfo.AccessibilityAction.ACTION_SET_TEXT in it.actionList
        }
    }
}
