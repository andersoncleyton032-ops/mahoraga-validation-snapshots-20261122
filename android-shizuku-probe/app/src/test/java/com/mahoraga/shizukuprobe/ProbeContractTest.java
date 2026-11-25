package com.mahoraga.shizukuprobe;

import static org.junit.Assert.*;

import org.junit.Test;

public final class ProbeContractTest {
    @Test
    public void acceptsCanonicalUuidRequestId() {
        assertTrue(ProbeContract.isValidRequestId("550e8400-e29b-41d4-a716-446655440000"));
    }

    @Test
    public void rejectsNullAndWrongLengthRequestIds() {
        assertFalse(ProbeContract.isValidRequestId(null));
        assertFalse(ProbeContract.isValidRequestId("550e8400"));
        assertFalse(ProbeContract.isValidRequestId("550e8400-e29b-41d4-a716-4466554400000"));
    }

    @Test
    public void rejectsNonHexadecimalCharacters() {
        assertFalse(ProbeContract.isValidRequestId("550e8400-e29b-41d4-a716-44665544ZZZZ"));
    }

    @Test
    public void rejectsMisplacedSeparators() {
        assertFalse(ProbeContract.isValidRequestId("550e8400e29b-41d4-a716-446655440000"));
    }

    @Test
    public void protocolAndServiceVersionsAreExplicit() {
        assertEquals(1, ProbeContract.PROTOCOL_VERSION);
        assertEquals(1, ProbeContract.USER_SERVICE_VERSION);
    }

    @Test
    public void operationBudgetsArePositiveAndBounded() {
        assertTrue(ProbeContract.BIND_TIMEOUT_MS > 0);
        assertTrue(ProbeContract.BIND_TIMEOUT_MS <= 15_000);
        assertTrue(ProbeContract.OPERATION_TIMEOUT_MS > 0);
        assertTrue(ProbeContract.OPERATION_TIMEOUT_MS <= 10_000);
    }
}