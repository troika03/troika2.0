package com.troika.hermes_assistant

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.*
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.view.animation.LinearInterpolator
import android.widget.FrameLayout
import android.widget.TextView
import kotlin.math.PI
import kotlin.math.sin

// Фирменный янтарь Тройки (совпадает с TroikaColors.brand / brandSoft).
private const val BRAND = 0xFFF5A623.toInt()
private const val BRAND_SOFT = 0xFFFFC65C.toInt()

/**
 * Полупрозрачное окошко поверх любого приложения (SYSTEM_ALERT_WINDOW).
 * Внутри — пульсирующая «живая» волна в фирменном янтаре Тройки.
 * Одна марка цвета, без радужных градиентов.
 */
class HermesOverlay private constructor(private val context: Context) {

    private var view: View? = null
    private var statusText: TextView? = null
    private var wave: WaveView? = null
    private val handler = Handler(Looper.getMainLooper())

    companion object {
        @Volatile private var instance: HermesOverlay? = null
        fun get(context: Context): HermesOverlay {
            return instance ?: synchronized(this) {
                instance ?: HermesOverlay(context.applicationContext).also { instance = it }
            }
        }
    }

    fun show(initialText: String = "Слушаю…") {
        handler.post {
            if (view != null) {
                statusText?.text = initialText
                return@post
            }
            buildAndShow(initialText)
        }
    }

    fun updateStatus(text: String) {
        handler.post { statusText?.text = text }
    }

    fun hide() {
        handler.post {
            wave?.stop()
            wave = null
            view?.let {
                try {
                    val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
                    wm.removeView(it)
                } catch (_: Exception) {}
            }
            view = null
            statusText = null
        }
    }

    private fun buildAndShow(initialText: String) {
        val d = context.resources.displayMetrics.density
        val sheetH = (130 * d).toInt()

        val root = FrameLayout(context).apply { setBackgroundColor(Color.TRANSPARENT) }

        // Полупрозрачная подложка с закруглённым верхом
        val sheet = FrameLayout(context).apply {
            background = GradientDrawable().apply {
                colors = intArrayOf(0xE61A1712.toInt(), 0xF20C0B0A.toInt()) // тёплый тёмный, ~90% непрозр.
                orientation = GradientDrawable.Orientation.TOP_BOTTOM
                cornerRadii = floatArrayOf(
                    26f * d, 26f * d, 26f * d, 26f * d, 0f, 0f, 0f, 0f
                )
            }
        }
        val sheetLp = FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT, sheetH
        )
        root.addView(sheet, sheetLp)

        // Тонкая фирменная линия-кромка сверху
        val edge = View(context).apply {
            background = GradientDrawable(
                GradientDrawable.Orientation.LEFT_RIGHT,
                intArrayOf(0x00F5A623, BRAND, BRAND_SOFT, BRAND, 0x00F5A623)
            )
        }
        sheet.addView(edge, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT, (2 * d).toInt()
        ))

        // Пульсирующая волна
        val w = WaveView(context).apply { start() }
        wave = w
        sheet.addView(w, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            (72 * d).toInt(),
            Gravity.CENTER_VERTICAL
        ))

        // Текст статуса
        val tv = TextView(context).apply {
            text = initialText
            setTextColor(0xFFF3F0EA.toInt())
            textSize = 16f
            gravity = Gravity.CENTER
            setShadowLayer(8f, 0f, 0f, 0x66000000)
        }
        sheet.addView(tv, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.WRAP_CONTENT,
            FrameLayout.LayoutParams.WRAP_CONTENT,
            Gravity.CENTER_HORIZONTAL or Gravity.BOTTOM
        ).apply { bottomMargin = (16 * d).toInt() })
        statusText = tv

        val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        } else {
            @Suppress("DEPRECATION")
            WindowManager.LayoutParams.TYPE_PHONE
        }
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT
        ).apply { gravity = Gravity.BOTTOM }

        try {
            wm.addView(root, lp)
            view = root
        } catch (e: Exception) {
            android.util.Log.e("HermesOverlay", "addView failed: ${e.message}")
        }
    }

    /** Несколько наложенных синусоид в янтаре — мягко текут и пульсируют. */
    private class WaveView(context: Context) : View(context) {
        private var phase = 0f
        private var t = 0f
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeCap = Paint.Cap.ROUND
        }
        private var animator: ValueAnimator? = null

        init {
            // setShadowLayer (glow) не работает с аппаратным ускорением — нужен software-слой.
            setLayerType(LAYER_TYPE_SOFTWARE, null)
        }

        fun start() {
            animator?.cancel()
            animator = ValueAnimator.ofFloat(0f, 1f).apply {
                duration = 1600
                repeatCount = ValueAnimator.INFINITE
                interpolator = LinearInterpolator()
                addUpdateListener {
                    phase = (it.animatedValue as Float) * 2f * PI.toFloat()
                    t += 0.016f
                    invalidate()
                }
                start()
            }
        }

        fun stop() {
            animator?.cancel()
            animator = null
        }

        override fun onDetachedFromWindow() {
            stop()
            super.onDetachedFromWindow()
        }

        override fun onDraw(canvas: Canvas) {
            val w = width.toFloat()
            val h = height.toFloat()
            val mid = h / 2f
            // Дыхание: общая амплитуда мягко пульсирует
            val breath = 0.6f + 0.4f * sin(t * 1.6f)
            val d = resources.displayMetrics.density

            // три слоя: плотный яркий + два размытых эха
            drawWave(canvas, w, mid, baseAmp = 16f * d * breath, freq = 1.6f,
                phaseOff = 0f, stroke = 3.5f * d, color = BRAND_SOFT, alpha = 235, glow = 14f * d)
            drawWave(canvas, w, mid, baseAmp = 22f * d * breath, freq = 1.1f,
                phaseOff = 1.2f, stroke = 2.2f * d, color = BRAND, alpha = 150, glow = 10f * d)
            drawWave(canvas, w, mid, baseAmp = 10f * d * breath, freq = 2.4f,
                phaseOff = 2.5f, stroke = 1.6f * d, color = BRAND_SOFT, alpha = 90, glow = 6f * d)
        }

        private fun drawWave(
            canvas: Canvas, w: Float, mid: Float,
            baseAmp: Float, freq: Float, phaseOff: Float,
            stroke: Float, color: Int, alpha: Int, glow: Float
        ) {
            val path = Path()
            val steps = 64
            for (i in 0..steps) {
                val x = w * i / steps
                val k = i.toFloat() / steps
                // огибающая: к краям волна затухает к центральной линии
                val env = sin(PI * k).toFloat()
                val y = mid + sin(k * freq * 2f * PI.toFloat() + phase + phaseOff) * baseAmp * env
                if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
            }
            paint.color = color
            paint.alpha = alpha
            paint.strokeWidth = stroke
            paint.setShadowLayer(glow, 0f, 0f, color)
            canvas.drawPath(path, paint)
        }
    }
}
