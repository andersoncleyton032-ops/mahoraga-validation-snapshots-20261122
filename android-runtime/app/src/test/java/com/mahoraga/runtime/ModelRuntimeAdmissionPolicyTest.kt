package com.mahoraga.runtime

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ModelRuntimeAdmissionPolicyTest {
    @Test
    fun allowsCpuBackendOnlyUntilDeviceGpuValidation() {
        assertTrue(ModelRuntimeAdmissionPolicy.isBackendAllowed("cpu"))
        assertTrue(ModelRuntimeAdmissionPolicy.isBackendAllowed(" CPU "))
        assertFalse(ModelRuntimeAdmissionPolicy.isBackendAllowed("gpu"))
        assertFalse(ModelRuntimeAdmissionPolicy.isBackendAllowed("unknown"))
    }

    @Test
    fun interactiveLoadRequiresScreenOnButNotCompanionActivityForeground() {
        assertTrue(
            ModelRuntimeAdmissionPolicy.isLoadAllowed(
                backgroundScheduleEnabled = false,
                screenInteractive = true,
                charging = false
            )
        )
        assertFalse(
            ModelRuntimeAdmissionPolicy.isLoadAllowed(
                backgroundScheduleEnabled = false,
                screenInteractive = false,
                charging = false
            )
        )
    }

    @Test
    fun backgroundLoadRequiresExplicitScheduleAndCharging() {
        assertTrue(
            ModelRuntimeAdmissionPolicy.isLoadAllowed(
                backgroundScheduleEnabled = true,
                screenInteractive = false,
                charging = true
            )
        )
        assertFalse(
            ModelRuntimeAdmissionPolicy.isLoadAllowed(
                backgroundScheduleEnabled = true,
                screenInteractive = false,
                charging = false
            )
        )
        assertFalse(
            ModelRuntimeAdmissionPolicy.isLoadAllowed(
                backgroundScheduleEnabled = false,
                screenInteractive = false,
                charging = true
            )
        )
    }

    @Test
    fun interactiveInferenceRequiresScreenOnAndNoBackgroundClaim() {
        assertTrue(
            ModelRuntimeAdmissionPolicy.isInferenceAllowed(
                allowBackground = false,
                taskClass = "interactive",
                backgroundScheduleEnabled = false,
                screenInteractive = true,
                charging = false
            )
        )
        assertFalse(
            ModelRuntimeAdmissionPolicy.isInferenceAllowed(
                allowBackground = false,
                taskClass = "interactive",
                backgroundScheduleEnabled = false,
                screenInteractive = false,
                charging = true
            )
        )
        assertFalse(
            ModelRuntimeAdmissionPolicy.isInferenceAllowed(
                allowBackground = true,
                taskClass = "interactive",
                backgroundScheduleEnabled = true,
                screenInteractive = true,
                charging = true
            )
        )
    }

    @Test
    fun backgroundInferenceRequiresExplicitOptInScheduleAndScreenOrCharging() {
        assertTrue(
            ModelRuntimeAdmissionPolicy.isInferenceAllowed(
                allowBackground = true,
                taskClass = "background",
                backgroundScheduleEnabled = true,
                screenInteractive = true,
                charging = false
            )
        )
        assertTrue(
            ModelRuntimeAdmissionPolicy.isInferenceAllowed(
                allowBackground = true,
                taskClass = "background",
                backgroundScheduleEnabled = true,
                screenInteractive = false,
                charging = true
            )
        )
        assertFalse(
            ModelRuntimeAdmissionPolicy.isInferenceAllowed(
                allowBackground = true,
                taskClass = "background",
                backgroundScheduleEnabled = true,
                screenInteractive = false,
                charging = false
            )
        )
        assertFalse(
            ModelRuntimeAdmissionPolicy.isInferenceAllowed(
                allowBackground = true,
                taskClass = "background",
                backgroundScheduleEnabled = false,
                screenInteractive = true,
                charging = true
            )
        )
        assertFalse(
            ModelRuntimeAdmissionPolicy.isInferenceAllowed(
                allowBackground = false,
                taskClass = "background",
                backgroundScheduleEnabled = true,
                screenInteractive = true,
                charging = true
            )
        )
    }
}
