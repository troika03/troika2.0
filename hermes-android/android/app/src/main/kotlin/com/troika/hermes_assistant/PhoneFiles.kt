package com.troika.hermes_assistant

import android.content.Context
import android.os.Build
import android.os.Environment
import android.util.Base64
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException

/**
 * Файловые операции на телефоне для LLM-инструментов.
 *
 * Безопасность:
 *   - Все пути канонизируются (resolveSafe) и должны лежать внутри одного из
 *     [allowedRoots] (Downloads/Documents/Pictures/Music/Movies/DCIM + app cache).
 *   - Без MANAGE_EXTERNAL_STORAGE юзер видит ТОЛЬКО эти папки.
 *   - С MANAGE_EXTERNAL_STORAGE (Settings → "Все файлы") доступ расширяется
 *     на /storage/emulated/0 целиком, но защита от ".." всё равно работает —
 *     путь должен начинаться с /storage/emulated/0.
 *
 * Размеры:
 *   - read() ограничен 5MB (текст) или 20MB (для бинарных, возвращается base64
 *     если запрошено encoding=base64).
 *   - write() принимает либо текст, либо base64.
 */
object PhoneFiles {
    private const val TAG = "PhoneFiles"

    private const val MAX_READ_BYTES = 20 * 1024 * 1024  // 20MB
    private const val MAX_TEXT_BYTES = 5 * 1024 * 1024   // 5MB
    private const val MAX_LIST_ENTRIES = 500

    /** Базовые корни (всегда доступны без специальных разрешений если есть READ/WRITE_EXTERNAL_STORAGE). */
    private fun publicRoots(): List<File> {
        // Environment.getExternalStoragePublicDirectory deprecated, но работает на всех версиях
        @Suppress("DEPRECATION")
        return listOf(
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOCUMENTS),
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES),
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MUSIC),
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MOVIES),
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DCIM),
        ).filterNotNull()
    }

    /** Имеет ли приложение полный доступ ко всем файлам. */
    fun hasAllFilesAccess(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Environment.isExternalStorageManager()
        } else true  // на старых Android — READ/WRITE_EXTERNAL_STORAGE достаточно
    }

    /** Корни доступные сейчас, с учётом разрешений. */
    private fun currentRoots(ctx: Context): List<File> {
        val list = mutableListOf<File>()
        // Если есть MANAGE_EXTERNAL_STORAGE — основной корень это /storage/emulated/0
        if (hasAllFilesAccess()) {
            Environment.getExternalStorageDirectory()?.let { list.add(it) }
        } else {
            list.addAll(publicRoots())
        }
        // Всегда даём доступ к private cache (для скачивания TTS / temp файлов)
        ctx.cacheDir?.let { list.add(it) }
        ctx.filesDir?.let { list.add(it) }
        return list.distinctBy { try { it.canonicalPath } catch (_: Exception) { it.absolutePath } }
    }

    /**
     * Резолвит входной путь относительно корней. Возвращает File если путь безопасен,
     * иначе null (вне разрешённых корней).
     *
     * Принимает:
     *   - абсолютные пути (/storage/emulated/0/Download/x.txt) → проверяем что внутри корня
     *   - относительные ("Downloads/x.txt") → ищем в каком из корней он лежит
     *   - префикс ~ или $HOME → /storage/emulated/0
     */
    private fun resolveSafe(ctx: Context, path: String): File? {
        if (path.isBlank()) return null
        val roots = currentRoots(ctx)

        // Нормализация
        var p = path.trim()
        if (p.startsWith("~") || p.startsWith("\$HOME")) {
            p = p.removePrefix("~").removePrefix("\$HOME").trimStart('/')
            val ext = Environment.getExternalStorageDirectory()
            if (ext != null) p = File(ext, p).absolutePath
        }

        val candidate = if (p.startsWith("/")) {
            File(p)
        } else {
            // Относительный путь — пробуем найти в каком из корней он есть/имеет смысл создаться
            val firstSegment = p.substringBefore("/").lowercase()
            val matchedRoot = roots.firstOrNull {
                it.name.lowercase() == firstSegment ||
                    it.name.lowercase().startsWith(firstSegment) ||
                    firstSegment in listOf("downloads", "download") && it.name == Environment.DIRECTORY_DOWNLOADS.lowercase()
            }
            if (matchedRoot != null) {
                File(matchedRoot.parentFile ?: matchedRoot, p)
            } else {
                // По умолчанию — Downloads
                @Suppress("DEPRECATION")
                File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), p)
            }
        }

        // Канонизация для защиты от ../
        val canonical = try { candidate.canonicalFile } catch (_: IOException) { candidate.absoluteFile }
        for (root in roots) {
            val rootCanon = try { root.canonicalFile } catch (_: IOException) { root.absoluteFile }
            if (canonical.absolutePath == rootCanon.absolutePath ||
                canonical.absolutePath.startsWith(rootCanon.absolutePath + File.separator)) {
                return canonical
            }
        }
        Log.w(TAG, "resolveSafe rejected: $path → ${canonical.absolutePath}")
        return null
    }

    // ------------------------------------------------------------------
    // Public API — вызывается из PhoneCommandExecutor
    // ------------------------------------------------------------------

    fun listFiles(ctx: Context, path: String, recursive: Boolean = false, pattern: String? = null): JSONObject {
        val dir = if (path.isBlank() || path == ".") {
            // Корень — показываем все доступные корни
            return JSONObject().apply {
                put("ok", true)
                put("path", "<roots>")
                put("entries", JSONArray().apply {
                    for (r in currentRoots(ctx)) {
                        put(JSONObject().apply {
                            put("name", r.name)
                            put("path", r.absolutePath)
                            put("is_dir", true)
                        })
                    }
                })
            }
        } else {
            resolveSafe(ctx, path) ?: return err("path_not_allowed: $path")
        }

        if (!dir.exists()) return err("not_found: ${dir.absolutePath}")
        if (!dir.isDirectory) {
            return JSONObject().apply {
                put("ok", true)
                put("path", dir.absolutePath)
                put("entries", JSONArray().apply { put(fileEntry(dir)) })
            }
        }

        val regex = pattern?.let {
            try { Regex(it, RegexOption.IGNORE_CASE) } catch (_: Exception) { null }
        }
        val entries = JSONArray()
        if (recursive) {
            dir.walkTopDown().take(MAX_LIST_ENTRIES + 1).forEach { f ->
                if (f == dir) return@forEach
                if (regex != null && !regex.containsMatchIn(f.name)) return@forEach
                if (entries.length() >= MAX_LIST_ENTRIES) return@forEach
                entries.put(fileEntry(f))
            }
        } else {
            val files = dir.listFiles() ?: emptyArray()
            for (f in files.sortedWith(compareBy({ !it.isDirectory }, { it.name.lowercase() }))) {
                if (regex != null && !regex.containsMatchIn(f.name)) continue
                if (entries.length() >= MAX_LIST_ENTRIES) break
                entries.put(fileEntry(f))
            }
        }
        return JSONObject().apply {
            put("ok", true)
            put("path", dir.absolutePath)
            put("count", entries.length())
            put("truncated", entries.length() >= MAX_LIST_ENTRIES)
            put("entries", entries)
        }
    }

    fun readFile(ctx: Context, path: String, encoding: String = "auto", maxBytes: Int = MAX_TEXT_BYTES): JSONObject {
        val f = resolveSafe(ctx, path) ?: return err("path_not_allowed: $path")
        if (!f.exists()) return err("not_found: ${f.absolutePath}")
        if (!f.isFile) return err("not_a_file: ${f.absolutePath}")

        val size = f.length()
        val limit = if (encoding == "base64") MAX_READ_BYTES else maxBytes.coerceAtMost(MAX_TEXT_BYTES)
        if (size > limit) return err("file_too_large: ${size}b > ${limit}b. Use encoding=base64 for binary files up to 20MB, or chunk reading.")

        val bytes = f.readBytes()
        return when (encoding) {
            "base64" -> JSONObject().apply {
                put("ok", true)
                put("path", f.absolutePath)
                put("size", size)
                put("encoding", "base64")
                put("content", Base64.encodeToString(bytes, Base64.NO_WRAP))
            }
            "text", "auto" -> {
                val text = try { String(bytes, Charsets.UTF_8) } catch (_: Exception) { null }
                if (text == null || (encoding == "auto" && !looksLikeText(bytes))) {
                    JSONObject().apply {
                        put("ok", true)
                        put("path", f.absolutePath)
                        put("size", size)
                        put("encoding", "base64")
                        put("content", Base64.encodeToString(bytes, Base64.NO_WRAP))
                        put("note", "binary content auto-encoded to base64")
                    }
                } else {
                    JSONObject().apply {
                        put("ok", true)
                        put("path", f.absolutePath)
                        put("size", size)
                        put("encoding", "text")
                        put("content", text)
                    }
                }
            }
            else -> err("unsupported_encoding: $encoding (use text/base64/auto)")
        }
    }

    fun writeFile(
        ctx: Context,
        path: String,
        content: String,
        encoding: String = "text",
        append: Boolean = false,
    ): JSONObject {
        val f = resolveSafe(ctx, path) ?: return err("path_not_allowed: $path")
        try {
            f.parentFile?.mkdirs()
            val bytes = when (encoding) {
                "base64" -> Base64.decode(content, Base64.DEFAULT)
                "text" -> content.toByteArray(Charsets.UTF_8)
                else -> return err("unsupported_encoding: $encoding")
            }
            if (append && f.exists()) {
                f.appendBytes(bytes)
            } else {
                f.writeBytes(bytes)
            }
            return JSONObject().apply {
                put("ok", true)
                put("path", f.absolutePath)
                put("size", f.length())
                put("appended", append)
            }
        } catch (e: Exception) {
            return err("write_failed: ${e.message}")
        }
    }

    /**
     * Сохранить картинку/видео в Галерею телефона (MediaStore).
     * content — base64. Тип (фото/видео) определяется по расширению filename.
     * На Android 10+ работает без WRITE_EXTERNAL_STORAGE (scoped storage).
     */
    fun saveToGallery(ctx: Context, filename: String, contentB64: String): JSONObject {
        if (filename.isBlank()) return err("missing filename")
        if (contentB64.isBlank()) return err("missing content")
        return try {
            val bytes = Base64.decode(contentB64, Base64.DEFAULT)
            val lower = filename.lowercase()
            val isVideo = lower.endsWith(".mp4") || lower.endsWith(".mov") ||
                lower.endsWith(".mkv") || lower.endsWith(".webm")
            val mime = when {
                isVideo -> "video/mp4"
                lower.endsWith(".png") -> "image/png"
                lower.endsWith(".webp") -> "image/webp"
                else -> "image/jpeg"
            }
            val collection = if (isVideo)
                android.provider.MediaStore.Video.Media.EXTERNAL_CONTENT_URI
            else
                android.provider.MediaStore.Images.Media.EXTERNAL_CONTENT_URI
            val subDir = if (isVideo)
                Environment.DIRECTORY_MOVIES else Environment.DIRECTORY_PICTURES

            val values = android.content.ContentValues().apply {
                put(android.provider.MediaStore.MediaColumns.DISPLAY_NAME, filename)
                put(android.provider.MediaStore.MediaColumns.MIME_TYPE, mime)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    put(android.provider.MediaStore.MediaColumns.RELATIVE_PATH, "$subDir/Тройка")
                    put(android.provider.MediaStore.MediaColumns.IS_PENDING, 1)
                }
            }
            val resolver = ctx.contentResolver
            val uri = resolver.insert(collection, values)
                ?: return err("mediastore_insert_failed")
            resolver.openOutputStream(uri)?.use { it.write(bytes) }
                ?: return err("open_output_failed")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                values.clear()
                values.put(android.provider.MediaStore.MediaColumns.IS_PENDING, 0)
                resolver.update(uri, values, null, null)
            }
            JSONObject().apply {
                put("ok", true)
                put("message", "Сохранено в Галерею: $filename")
                put("uri", uri.toString())
                put("size", bytes.size)
            }
        } catch (e: Exception) {
            err("save_to_gallery_failed: ${e.message}")
        }
    }

    fun deleteFile(ctx: Context, path: String, recursive: Boolean = false): JSONObject {
        val f = resolveSafe(ctx, path) ?: return err("path_not_allowed: $path")
        if (!f.exists()) return err("not_found: ${f.absolutePath}")
        return try {
            val ok = if (f.isDirectory) {
                if (!recursive) return err("directory_not_empty: pass recursive=true to delete a folder")
                f.deleteRecursively()
            } else {
                f.delete()
            }
            if (ok) JSONObject().apply {
                put("ok", true); put("deleted", f.absolutePath)
            } else err("delete_failed")
        } catch (e: Exception) {
            err("delete_failed: ${e.message}")
        }
    }

    fun moveFile(ctx: Context, src: String, dst: String, overwrite: Boolean = false): JSONObject {
        val s = resolveSafe(ctx, src) ?: return err("src_not_allowed: $src")
        val d = resolveSafe(ctx, dst) ?: return err("dst_not_allowed: $dst")
        if (!s.exists()) return err("src_not_found: ${s.absolutePath}")
        if (d.exists() && !overwrite) return err("dst_exists: ${d.absolutePath}")

        return try {
            d.parentFile?.mkdirs()
            if (s.renameTo(d)) {
                JSONObject().apply { put("ok", true); put("from", s.absolutePath); put("to", d.absolutePath) }
            } else {
                // Fallback: копируем и удаляем (renameTo может не работать между volumes)
                s.copyTo(d, overwrite = overwrite)
                s.deleteRecursively()
                JSONObject().apply { put("ok", true); put("from", s.absolutePath); put("to", d.absolutePath); put("note", "copied+deleted") }
            }
        } catch (e: Exception) {
            err("move_failed: ${e.message}")
        }
    }

    fun fileInfo(ctx: Context, path: String): JSONObject {
        val f = resolveSafe(ctx, path) ?: return err("path_not_allowed: $path")
        if (!f.exists()) return err("not_found: ${f.absolutePath}")
        return JSONObject().apply {
            put("ok", true)
            put("path", f.absolutePath)
            put("name", f.name)
            put("size", if (f.isFile) f.length() else 0)
            put("is_dir", f.isDirectory)
            put("modified_ms", f.lastModified())
            put("readable", f.canRead())
            put("writable", f.canWrite())
            if (f.isDirectory) {
                put("entries", (f.listFiles()?.size ?: 0))
            }
        }
    }

    // ------------------------------------------------------------------
    // helpers
    // ------------------------------------------------------------------

    private fun fileEntry(f: File): JSONObject = JSONObject().apply {
        put("name", f.name)
        put("path", f.absolutePath)
        put("is_dir", f.isDirectory)
        if (f.isFile) put("size", f.length())
        put("modified_ms", f.lastModified())
    }

    /** Эвристика: похоже ли содержимое на текст (мало нулевых байт). */
    private fun looksLikeText(bytes: ByteArray): Boolean {
        if (bytes.isEmpty()) return true
        val sampleSize = minOf(bytes.size, 4096)
        var nulCount = 0
        var nonPrintCount = 0
        for (i in 0 until sampleSize) {
            val b = bytes[i].toInt() and 0xff
            if (b == 0) nulCount++
            else if (b < 0x09 || (b in 0x0e..0x1f && b != 0x1b)) nonPrintCount++
        }
        return nulCount == 0 && nonPrintCount < sampleSize / 50
    }

    private fun err(msg: String) = JSONObject().apply {
        put("ok", false); put("error", msg)
    }
}
