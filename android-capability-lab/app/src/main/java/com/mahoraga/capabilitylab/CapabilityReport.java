package com.mahoraga.capabilitylab;

import org.json.JSONObject;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

public final class CapabilityReport {
    public static final String SCHEMA = "mahoraga.android_capability_report.v1";

    private final Map<String, Object> device;
    private final Map<String, Object> capabilities;

    public CapabilityReport(Map<String, Object> device, Map<String, Object> capabilities) {
        this.device = new LinkedHashMap<>(device);
        this.capabilities = new LinkedHashMap<>(capabilities);
    }

    public Map<String, Object> toMap() {
        Map<String, Object> report = new LinkedHashMap<>();
        report.put("schema", SCHEMA);
        report.put("generated_at", Instant.now().toString());
        report.put("device", new LinkedHashMap<>(device));
        report.put("capabilities", new LinkedHashMap<>(capabilities));
        report.put("network_upload_performed", false);
        report.put("capture_started", false);
        report.put("permissions_requested", false);
        return report;
    }

    public String toJson() {
        try {
            return new JSONObject(toMap()).toString(2);
        } catch (org.json.JSONException error) {
            throw new IllegalStateException("Capability report could not be serialized.", error);
        }
    }
}
