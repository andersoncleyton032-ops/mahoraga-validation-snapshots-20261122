package com.mahoraga.capabilitylab;

import org.json.JSONObject;

import java.math.BigDecimal;
import java.math.BigInteger;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Immutable, validated snapshot of the read-only Android capability inventory.
 *
 * Nested input maps/lists are defensively copied so later probe mutations cannot
 * rewrite evidence after collection. The generated timestamp is fixed at creation.
 */
public final class CapabilityReport {
    public static final String SCHEMA = "mahoraga.android_capability_report.v1";

    private static final int MAX_JSON_DEPTH = 32;
    private static final int MAX_JSON_NODES = 50000;

    private final Map<String, Object> device;
    private final Map<String, Object> capabilities;
    private final String generatedAt;

    public CapabilityReport(Map<String, Object> device, Map<String, Object> capabilities) {
        IdentityHashMap<Object, Boolean> active = new IdentityHashMap<>();
        int[] budget = {0};
        this.device = immutableObject(device, "device", active, budget);
        this.capabilities = immutableObject(capabilities, "capabilities", active, budget);
        validateCapabilities(this.capabilities);
        this.generatedAt = Instant.now().toString();
    }

    public Map<String, Object> toMap() {
        Map<String, Object> report = new LinkedHashMap<>();
        report.put("schema", SCHEMA);
        report.put("generated_at", generatedAt);
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

    private static void validateCapabilities(Map<String, Object> capabilities) {
        for (Map.Entry<String, Object> item : capabilities.entrySet()) {
            if (!(item.getValue() instanceof Map)) {
                throw new IllegalArgumentException(
                        "Capability '" + item.getKey() + "' must be a JSON object.");
            }
            Map<?, ?> entry = (Map<?, ?>) item.getValue();
            Object status = entry.get("status");
            Object detail = entry.get("detail");
            if (!(status instanceof String)) {
                throw new IllegalArgumentException(
                        "Capability '" + item.getKey() + "' requires a string status.");
            }
            try {
                CapabilityState.Status.valueOf((String) status);
            } catch (IllegalArgumentException error) {
                throw new IllegalArgumentException(
                        "Capability '" + item.getKey() + "' has an unknown status.", error);
            }
            if (!(detail instanceof String) || ((String) detail).trim().isEmpty()) {
                throw new IllegalArgumentException(
                        "Capability '" + item.getKey() + "' requires a non-empty detail.");
            }
        }
    }

    private static Map<String, Object> immutableObject(
            Map<String, Object> source,
            String path,
            IdentityHashMap<Object, Boolean> active,
            int[] budget) {
        if (source == null) {
            throw new IllegalArgumentException(path + " must not be null.");
        }
        Map<String, Object> result = new LinkedHashMap<>();
        for (Map.Entry<?, ?> item : ((Map<?, ?>) source).entrySet()) {
            if (!(item.getKey() instanceof String)
                    || ((String) item.getKey()).trim().isEmpty()) {
                throw new IllegalArgumentException(path + " contains a non-string/empty key.");
            }
            String key = (String) item.getKey();
            result.put(key, immutableJsonValue(
                    item.getValue(), path + "." + key, 0, active, budget));
        }
        return Collections.unmodifiableMap(result);
    }

    private static Object immutableJsonValue(
            Object value,
            String path,
            int depth,
            IdentityHashMap<Object, Boolean> active,
            int[] budget) {
        budget[0]++;
        if (depth > MAX_JSON_DEPTH || budget[0] > MAX_JSON_NODES) {
            throw new IllegalArgumentException(path + " exceeds the report complexity budget.");
        }
        if (value == null || value instanceof String || value instanceof Boolean) {
            return value;
        }
        if (value instanceof Byte || value instanceof Short
                || value instanceof Integer || value instanceof Long
                || value instanceof BigInteger || value instanceof BigDecimal) {
            return value;
        }
        if (value instanceof Double) {
            if (!Double.isFinite((Double) value)) {
                throw new IllegalArgumentException(path + " must be finite.");
            }
            return value;
        }
        if (value instanceof Float) {
            if (!Float.isFinite((Float) value)) {
                throw new IllegalArgumentException(path + " must be finite.");
            }
            return value;
        }
        if (value instanceof Map) {
            if (active.put(value, Boolean.TRUE) != null) {
                throw new IllegalArgumentException(path + " contains a cyclic JSON object.");
            }
            try {
                Map<?, ?> source = (Map<?, ?>) value;
                Map<String, Object> result = new LinkedHashMap<>();
                for (Map.Entry<?, ?> item : source.entrySet()) {
                    if (!(item.getKey() instanceof String)
                            || ((String) item.getKey()).trim().isEmpty()) {
                        throw new IllegalArgumentException(
                                path + " contains a non-string/empty key.");
                    }
                    String key = (String) item.getKey();
                    result.put(key, immutableJsonValue(
                            item.getValue(), path + "." + key, depth + 1, active, budget));
                }
                return Collections.unmodifiableMap(result);
            } finally {
                active.remove(value);
            }
        }
        if (value instanceof List) {
            if (active.put(value, Boolean.TRUE) != null) {
                throw new IllegalArgumentException(path + " contains a cyclic JSON array.");
            }
            try {
                List<?> source = (List<?>) value;
                List<Object> result = new ArrayList<>(source.size());
                for (int index = 0; index < source.size(); index++) {
                    result.add(immutableJsonValue(
                            source.get(index), path + "[" + index + "]",
                            depth + 1, active, budget));
                }
                return Collections.unmodifiableList(result);
            } finally {
                active.remove(value);
            }
        }
        throw new IllegalArgumentException(
                path + " contains a value that is not JSON-compatible: "
                        + value.getClass().getName());
    }
}
