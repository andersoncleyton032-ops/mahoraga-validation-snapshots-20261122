package com.mahoraga.runtime

import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.net.Uri
import android.os.Binder
import android.os.Build
import android.os.Bundle
import android.util.Base64
import org.json.JSONObject
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException

/**
 * Narrow local IPC surface for the Termux core.
 * Only the installed Termux UID with an allowlisted release signer is accepted.
 *
 * Methods:
 *  status
 *  load       arg: "cpu" (GPU remains disabled pending device validation)
 *  infer      arg: {"request_id":"...","prompt":"..."} -> accepted request ID
 *  result     arg: request ID -> pending/completed/failed/cancelled
 *  cancel     arg: request ID -> cancellation_requested/already_completed/unknown_request
 *  unload
 */
class ModelRuntimeProvider : ContentProvider() {
    companion object {
        const val PROMPT_PROTOCOL_VERSION = 1
        const val PROMPT_PROTOCOL = ModelPromptEnvelope.FORMAT
    }

    override fun onCreate(): Boolean = true

    override fun call(method: String, arg: String?, extras: Bundle?): Bundle {
        val appContext = context ?: return response("failed", error = "provider_context_unavailable")
        if (!isTermuxCaller(appContext)) {
            throw SecurityException("Only Termux may call the Mahoraga model provider.")
        }
        val owner = (appContext.applicationContext as MahoragaApplication).modelEngineOwner

        return try {
            when (method) {
                "status" -> owner.status().apply {
                    putInt("prompt_protocol_version", PROMPT_PROTOCOL_VERSION)
                    putString("prompt_protocol", PROMPT_PROTOCOL)
                    putString("backend_policy", "cpu_only_until_device_validation")
                    val preferences = appContext.getSharedPreferences(
                        ModelFileManager.PREFERENCES, Context.MODE_PRIVATE
                    )
                    putString("model_sha256", preferences.getString(ModelFileManager.KEY_MODEL_SHA256, null))
                    putLong("model_size_bytes", preferences.getLong(ModelFileManager.KEY_MODEL_SIZE, 0L))
                }
                "load" -> {
                    val preferences = appContext.getSharedPreferences(
                        ModelFileManager.PREFERENCES, Context.MODE_PRIVATE
                    )
                    val modelPath = preferences.getString(ModelFileManager.KEY_MODEL_PATH, null)
                        ?: return response("failed", error = "model_not_imported")
                    val backend = arg?.lowercase()?.takeIf { it.isNotBlank() } ?: "cpu"
                    if (!ModelRuntimeAdmissionPolicy.isBackendAllowed(backend)) {
                        return response("failed", error = "backend_not_authorized")
                    }
                    val expectedSha256 = preferences.getString(
                        ModelFileManager.KEY_MODEL_SHA256, null
                    ) ?: return response("failed", error = "model_sha256_missing")
                    val future = owner.load(modelPath, backend, expectedSha256)
                    val state = try {
                        future.get(180, TimeUnit.SECONDS)
                    } catch (_: TimeoutException) {
                        "load_pending"
                    }
                    response(state)
                }
                "infer" -> {
                    val payload = JSONObject(arg ?: "{}")
                    val requestId = payload.optString("request_id")
                    val prompt = payload.optString("prompt")
                    val taskClass = payload.optString("task_class", "interactive")
                    val duration = (payload.opt("max_duration_seconds") as? Number)?.toDouble()
                    val durationPolicyApplied = payload.optBoolean("duration_policy_applied", false)
                    val extraRam = (payload.opt("estimated_additional_ram_mb") as? Number)?.toLong()
                    val thinkingBudget = (payload.opt("thinking_token_budget") as? Number)?.toInt()
                    val outputBudget = (payload.opt("max_output_tokens") as? Number)?.toInt()
                    val allowBackground = payload.optBoolean("allow_background", false)
                    val topK = optionalInt(payload, "top_k")
                    val topP = optionalDouble(payload, "top_p")
                    val temperature = optionalDouble(payload, "temperature")
                    val state = owner.submitInference(
                        requestId, prompt, taskClass, duration, durationPolicyApplied,
                        extraRam, thinkingBudget, outputBudget, allowBackground,
                        topK, topP, temperature
                    )
                    response(state, requestId = requestId)
                }
                "cancel" -> {
                    val requestId = arg?.takeIf { it.isNotBlank() }
                        ?: return response("failed", error = "request_id_required")
                    owner.cancelInference(requestId)
                }
                "ack" -> {
                    val requestId = arg?.takeIf { it.isNotBlank() }
                        ?: return response("failed", error = "request_id_required")
                    owner.acknowledgeInference(requestId)
                }
                "result" -> {
                    val requestId = arg?.takeIf { it.isNotBlank() }
                        ?: return response("failed", error = "request_id_required")
                    val result = owner.pollInference(requestId)
                    val text = result.getString("text")
                    if (text != null) {
                        result.remove("text")
                        val encoded = Base64.encodeToString(
                            text.toByteArray(Charsets.UTF_8), Base64.NO_WRAP
                        ).ifEmpty { "-" }
                        result.putString("text_b64", encoded)
                    }
                    result
                }
                "unload" -> {
                    owner.unload().get(60, TimeUnit.SECONDS)
                    response("unloaded")
                }
                else -> response("failed", error = "method_not_supported")
            }
        } catch (_: TimeoutException) {
            response("pending", error = "operation_still_running")
        } catch (failure: Exception) {
            val cause = failure.cause ?: failure
            if (cause is VirtualMachineError || cause is ThreadDeath) throw cause
            response("failed", error = cause.javaClass.simpleName)
        } catch (failure: LinkageError) {
            response("failed", error = failure.javaClass.simpleName)
        }
    }

    private fun optionalNumber(payload: JSONObject, key: String): Number? {
        val value = payload.opt(key)
        if (value == null || value === JSONObject.NULL) return null
        return value as? Number ?: throw IllegalArgumentException("${key}_invalid")
    }

    private fun optionalInt(payload: JSONObject, key: String): Int? {
        val number = optionalNumber(payload, key) ?: return null
        val value = number.toDouble()
        require(value.isFinite() && value % 1.0 == 0.0 &&
            value >= Int.MIN_VALUE.toDouble() && value <= Int.MAX_VALUE.toDouble()
        ) { "${key}_invalid" }
        return value.toInt()
    }

    private fun optionalDouble(payload: JSONObject, key: String): Double? {
        val number = optionalNumber(payload, key) ?: return null
        return number.toDouble().also {
            require(it.isFinite()) { "${key}_invalid" }
        }
    }

    private fun isTermuxCaller(appContext: Context): Boolean {
        return try {
            val packageManager = appContext.packageManager
            val callingUid = Binder.getCallingUid()
            val packages = packageManager.getPackagesForUid(callingUid)
            val installedTermux = packageManager.getApplicationInfo(
                TermuxCallerPolicy.TERMUX_PACKAGE, 0
            )
            val signer = TermuxSignerPolicy.verifyInstalled(
                packageManager,
                TermuxCallerPolicy.TERMUX_PACKAGE,
                Build.VERSION.SDK_INT
            )
            TermuxCallerPolicy.isTrusted(
                callingUid = callingUid,
                packagesForUid = packages,
                installedTermuxUid = installedTermux.uid,
                signerTrusted = signer.trusted
            )
        } catch (_: Exception) {
            false
        }
    }

    private fun response(
        state: String,
        requestId: String? = null,
        error: String? = null,
    ) = Bundle().apply {
        putString("status", state)
        requestId?.let { putString("request_id", it) }
        error?.let { putString("error", it) }
    }

    override fun query(
        uri: Uri, projection: Array<out String>?, selection: String?,
        selectionArgs: Array<out String>?, sortOrder: String?
    ): Cursor? = null

    override fun getType(uri: Uri): String? = null
    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0
    override fun update(
        uri: Uri, values: ContentValues?, selection: String?,
        selectionArgs: Array<out String>?
    ): Int = 0
}
