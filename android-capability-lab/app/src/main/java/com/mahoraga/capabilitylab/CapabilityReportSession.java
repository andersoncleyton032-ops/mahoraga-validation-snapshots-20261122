package com.mahoraga.capabilitylab;

/**
 * Holds only the most recent successful read-only capability observation.
 *
 * Starting a new observation invalidates the previous report immediately so a
 * failed refresh can never be mistaken for current device state.
 */
public final class CapabilityReportSession {
    private String latestReport = "";

    public void beginCollection() {
        latestReport = "";
    }

    public void complete(String report) {
        if (report == null || report.trim().isEmpty()) {
            throw new IllegalArgumentException("Capability report must not be empty.");
        }
        latestReport = report;
    }

    public void fail() {
        latestReport = "";
    }

    public String latestReport() {
        return latestReport;
    }

    public boolean hasReport() {
        return !latestReport.isEmpty();
    }
}
