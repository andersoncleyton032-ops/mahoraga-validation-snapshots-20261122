package com.mahoraga.runtime

import android.content.Context
import android.net.Uri
import android.os.Bundle
import android.os.StatFs
import android.provider.OpenableColumns
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.TimeUnit

object ModelFileManager {
    const val PREFERENCES = "mahoraga_local_model"
    const val KEY_MODEL_PATH = "model_path"
    const val KEY_MODEL_SHA256 = "model_sha256"
    const val KEY_MODEL_SIZE = "model_size_bytes"

    @JvmStatic
    fun importModel(context: Context, uri: Uri): Bundle {
        val app = context.applicationContext as? MahoragaApplication
        app?.modelEngineOwner?.unload()?.get(120, TimeUnit.SECONDS)
        val resolver = context.contentResolver
        val metadata = resolver.query(
            uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE),
            null, null, null
        )?.use { cursor ->
            if (!cursor.moveToFirst()) null
            else {
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
                val name = if (nameIndex >= 0) cursor.getString(nameIndex) else null
                val size = if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) cursor.getLong(sizeIndex) else -1L
                Pair(name, size)
            }
        } ?: Pair(null, -1L)

        val originalName = metadata.first?.takeIf { it.isNotBlank() } ?: "model.litertlm"
        require(originalName.endsWith(".litertlm", ignoreCase = true)) {
            "selected_file_is_not_litertlm"
        }
        val safeName = originalName.substringAfterLast('/').substringAfterLast('\\')
            .replace(Regex("[^A-Za-z0-9._-]"), "_")
        require(safeName.isNotBlank() && safeName.endsWith(".litertlm", ignoreCase = true)) {
            "model_filename_invalid"
        }

        val modelDirectory = File(context.filesDir, "models")
        if (!modelDirectory.exists() && !modelDirectory.mkdirs()) {
            throw IOException("model_directory_creation_failed")
        }
        val freeBytes = StatFs(modelDirectory.absolutePath).availableBytes
        val expectedBytes = metadata.second
        val reserveBytes = 64L * 1024L * 1024L
        if (expectedBytes > 0 && freeBytes < expectedBytes + reserveBytes) {
            throw IOException("insufficient_storage_for_model_import")
        }
        if (expectedBytes <= 0 && freeBytes < reserveBytes) {
            throw IOException("insufficient_storage_for_model_import")
        }

        val target = File(modelDirectory, safeName)
        val temporary = File(modelDirectory, ".import-" + UUID.randomUUID() + ".part")
        val backup = File(modelDirectory, ".backup-" + UUID.randomUUID() + ".bak")
        val digest = MessageDigest.getInstance("SHA-256")
        var copied = 0L
        try {
            val input = resolver.openInputStream(uri)
                ?: throw IOException("model_source_unavailable")
            input.use { source ->
                FileOutputStream(temporary).use { output ->
                    val buffer = ByteArray(1024 * 1024)
                    while (true) {
                        val count = source.read(buffer)
                        if (count < 0) break
                        val available = StatFs(modelDirectory.absolutePath).availableBytes
                        if (available < count + reserveBytes) {
                            throw IOException("storage_reserve_reached_during_import")
                        }
                        output.write(buffer, 0, count)
                        digest.update(buffer, 0, count)
                        copied += count
                    }
                    output.fd.sync()
                }
            }
            if (copied <= 0L) throw IOException("model_file_empty")
            if (expectedBytes > 0 && copied != expectedBytes) {
                throw IOException("model_file_size_mismatch")
            }

            if (target.exists() && !target.renameTo(backup)) {
                throw IOException("existing_model_backup_failed")
            }
            if (!temporary.renameTo(target)) {
                if (backup.exists()) backup.renameTo(target)
                throw IOException("model_atomic_publish_failed")
            }
            backup.delete()

            val sha256 = digest.digest().joinToString("") { "%02x".format((it.toInt() and 0xff)) }
            context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE).edit()
                .putString(KEY_MODEL_PATH, target.absolutePath)
                .putString(KEY_MODEL_SHA256, sha256)
                .putLong(KEY_MODEL_SIZE, copied)
                .apply()

            return Bundle().apply {
                putString("status", "imported")
                putString("model_path", target.absolutePath)
                putString("sha256", sha256)
                putLong("size_bytes", copied)
            }
        } catch (failure: Throwable) {
            temporary.delete()
            if (backup.exists() && !target.exists()) backup.renameTo(target)
            throw failure
        }
    }
}
