package com.mahoraga.capabilitylab;

import org.junit.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

public final class CapabilityStateTest {
    @Test
    public void absentFeatureIsUnsupportedEvenWhenPermissionIsGranted() {
        assertEquals(
                CapabilityState.Status.UNSUPPORTED,
                CapabilityState.permission(false, true)
        );
    }

    @Test
    public void presentFeatureWithoutPermissionRequiresPermission() {
        assertEquals(
                CapabilityState.Status.REQUIRES_PERMISSION,
                CapabilityState.permission(true, false)
        );
    }

    @Test
    public void presentFeatureWithPermissionIsAvailable() {
        assertEquals(
                CapabilityState.Status.AVAILABLE,
                CapabilityState.permission(true, true)
        );
    }

    @Test
    public void absentOptionalPackageIsNotMisclassifiedAsUnsupported() {
        assertEquals(
                CapabilityState.Status.TEMPORARILY_UNAVAILABLE,
                CapabilityState.optionalPackage(false)
        );
    }

    @Test
    public void reportDefensivelyCopiesNestedProbeEvidence() {
        List<Object> sensors = new ArrayList<>();
        sensors.add("accelerometer");
        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("sensors", sensors);
        Map<String, Object> capability = capabilityEntry(evidence);
        Map<String, Object> capabilities = new LinkedHashMap<>();
        capabilities.put("sensor_inventory", capability);
        Map<String, Object> device = new LinkedHashMap<>();
        device.put("model", "test-device");

        CapabilityReport report = new CapabilityReport(device, capabilities);
        sensors.add("mutated-after-construction");
        capability.put("detail", "mutated-after-construction");
        device.put("model", "mutated-after-construction");

        Map<?, ?> reportDevice = (Map<?, ?>) report.toMap().get("device");
        Map<?, ?> reportCapabilities = (Map<?, ?>) report.toMap().get("capabilities");
        Map<?, ?> reportSensor = (Map<?, ?>) reportCapabilities.get("sensor_inventory");
        Map<?, ?> reportEvidence = (Map<?, ?>) reportSensor.get("evidence");
        List<?> reportSensors = (List<?>) reportEvidence.get("sensors");

        assertEquals("test-device", reportDevice.get("model"));
        assertEquals("Inventário concluído.", reportSensor.get("detail"));
        assertEquals(1, reportSensors.size());
        assertEquals("accelerometer", reportSensors.get(0));
    }

    @Test
    public void reportNestedEvidenceIsImmutableAndOutputMutationIsIsolated() {
        Map<String, Object> evidence = new LinkedHashMap<>();
        evidence.put("count", 2);
        Map<String, Object> capabilities = new LinkedHashMap<>();
        capabilities.put("sensor_inventory", capabilityEntry(evidence));
        CapabilityReport report = new CapabilityReport(new LinkedHashMap<>(), capabilities);

        Map<String, Object> first = report.toMap();
        first.put("unexpected", "output-only");
        ((Map<String, Object>) first.get("device")).put("model", "output-only");
        Map<?, ?> capabilityMap = (Map<?, ?>) first.get("capabilities");
        Map<?, ?> sensor = (Map<?, ?>) capabilityMap.get("sensor_inventory");
        Map<?, ?> nestedEvidence = (Map<?, ?>) sensor.get("evidence");

        assertEquals("output-only", ((Map<?, ?>) first.get("device")).get("model"));
        assertFalse(report.toMap().containsKey("unexpected"));
        assertEquals(2, nestedEvidence.get("count"));
        try {
            ((Map<String, Object>) nestedEvidence).put("count", 3);
            throw new AssertionError("Nested report evidence must be immutable.");
        } catch (UnsupportedOperationException expected) {
            assertNotNull(expected);
        }
    }

    @Test
    public void reportTimestampIsStableAcrossSerializations() {
        Map<String, Object> capabilities = new LinkedHashMap<>();
        capabilities.put("jobscheduler", capabilityEntry(null));
        CapabilityReport report = new CapabilityReport(new LinkedHashMap<>(), capabilities);

        String first = (String) report.toMap().get("generated_at");
        String second = (String) report.toMap().get("generated_at");

        assertNotNull(first);
        assertEquals(first, second);
        assertTrue(first.endsWith("Z"));
        assertTrue(report.toJson().contains(CapabilityReport.SCHEMA));
    }

    @Test
    public void reportRejectsUnknownCapabilityStatusAndMissingDetail() {
        Map<String, Object> unknownStatus = new LinkedHashMap<>();
        unknownStatus.put("status", "MAYBE");
        unknownStatus.put("detail", "invalid");
        Map<String, Object> invalidCapabilities = new LinkedHashMap<>();
        invalidCapabilities.put("camera", unknownStatus);
        expectInvalidReport(invalidCapabilities);

        Map<String, Object> missingDetail = new LinkedHashMap<>();
        missingDetail.put("status", CapabilityState.Status.AVAILABLE.name());
        invalidCapabilities.put("camera", missingDetail);
        expectInvalidReport(invalidCapabilities);
    }

    @Test
    public void reportRejectsNonFiniteAndNonJsonEvidence() {
        Map<String, Object> nonFinite = new LinkedHashMap<>();
        nonFinite.put("value", Double.NaN);
        Map<String, Object> capabilities = new LinkedHashMap<>();
        capabilities.put("sensor_inventory", capabilityEntry(nonFinite));
        expectInvalidReport(capabilities);

        Map<String, Object> unsupported = new LinkedHashMap<>();
        unsupported.put("value", new Object());
        capabilities.put("sensor_inventory", capabilityEntry(unsupported));
        expectInvalidReport(capabilities);
    }


    @Test
    public void reportRejectsCyclicEvidence() {
        Map<String, Object> cyclic = new LinkedHashMap<>();
        cyclic.put("self", cyclic);
        Map<String, Object> capabilities = new LinkedHashMap<>();
        capabilities.put("sensor_inventory", capabilityEntry(cyclic));

        expectInvalidReport(capabilities);
    }

    @Test
    public void reportRejectsExcessivelyNestedEvidence() {
        Map<String, Object> nested = new LinkedHashMap<>();
        for (int index = 0; index < 40; index++) {
            Map<String, Object> parent = new LinkedHashMap<>();
            parent.put("nested", nested);
            nested = parent;
        }
        Map<String, Object> capabilities = new LinkedHashMap<>();
        capabilities.put("sensor_inventory", capabilityEntry(nested));

        expectInvalidReport(capabilities);
    }

    private static Map<String, Object> capabilityEntry(Map<String, Object> evidence) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("status", CapabilityState.Status.AVAILABLE.name());
        entry.put("detail", "Inventário concluído.");
        if (evidence != null) entry.put("evidence", evidence);
        return entry;
    }

    private static void expectInvalidReport(Map<String, Object> capabilities) {
        try {
            new CapabilityReport(new LinkedHashMap<>(), capabilities);
            throw new AssertionError("Invalid report was accepted.");
        } catch (IllegalArgumentException expected) {
            assertNotNull(expected);
        }
    }
}
