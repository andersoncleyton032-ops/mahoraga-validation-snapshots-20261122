package com.mahoraga.runtime

internal object ModelRuntimeAdmissionPolicy {
    fun isBackendAllowed(backendName: String): Boolean =
        backendName.trim().equals("cpu", ignoreCase = true)

    fun isLoadAllowed(
        backgroundScheduleEnabled: Boolean,
        screenInteractive: Boolean,
        charging: Boolean
    ): Boolean {
        if (screenInteractive) return true
        return backgroundScheduleEnabled && charging
    }

    fun isInferenceAllowed(
        allowBackground: Boolean,
        taskClass: String,
        backgroundScheduleEnabled: Boolean,
        screenInteractive: Boolean,
        charging: Boolean
    ): Boolean {
        if (taskClass == "background") {
            return allowBackground
                && backgroundScheduleEnabled
                && (screenInteractive || charging)
        }
        return !allowBackground && screenInteractive
    }
}
