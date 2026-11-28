package com.mahoraga.capabilitylab;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public final class CapabilityReportSessionTest {
    @Test
    public void sessionStartsWithoutAReport() {
        CapabilityReportSession session = new CapabilityReportSession();

        assertFalse(session.hasReport());
        assertEquals("", session.latestReport());
    }

    @Test
    public void successfulCollectionPublishesTheCurrentReport() {
        CapabilityReportSession session = new CapabilityReportSession();
        session.beginCollection();
        session.complete("{\"schema\":\"capability-report-v1\"}");

        assertTrue(session.hasReport());
        assertEquals("{\"schema\":\"capability-report-v1\"}", session.latestReport());
    }

    @Test
    public void startingANewCollectionInvalidatesThePreviousReport() {
        CapabilityReportSession session = new CapabilityReportSession();
        session.complete("{\"observation\":1}");

        session.beginCollection();

        assertFalse(session.hasReport());
        assertEquals("", session.latestReport());
    }

    @Test
    public void failedRefreshCannotExposeThePreviousSuccessfulReport() {
        CapabilityReportSession session = new CapabilityReportSession();
        session.complete("{\"observation\":1}");
        session.beginCollection();

        session.fail();

        assertFalse(session.hasReport());
        assertEquals("", session.latestReport());
    }

    @Test
    public void emptyReportsAreRejected() {
        CapabilityReportSession session = new CapabilityReportSession();

        try {
            session.complete("  ");
            throw new AssertionError("Empty report must not be published.");
        } catch (IllegalArgumentException expected) {
            assertTrue(expected.getMessage().contains("must not be empty"));
        }
    }
}
