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
        assertTrue(ProbeContract.HANDSHAKE_TIMEOUT_MS > 0);
        assertTrue(ProbeContract.HANDSHAKE_TIMEOUT_MS <= 10_000);
    }
    @Test
    public void userServiceTagAndProcessNameAreUniquePerGeneration() {
        assertEquals(ProbeContract.userServiceTag(7), ProbeContract.userServiceTag(7));
        assertNotEquals(ProbeContract.userServiceTag(7), ProbeContract.userServiceTag(8));
        assertNotEquals(
                ProbeContract.userServiceProcessSuffix(7),
                ProbeContract.userServiceProcessSuffix(8)
        );
    }

    @Test
    public void userServiceIdentityRejectsNonPositiveGeneration() {
        try {
            ProbeContract.userServiceTag(0);
            fail("zero generation must be rejected");
        } catch (IllegalArgumentException expected) {
            assertTrue(expected.getMessage().contains("positive"));
        }
        try {
            ProbeContract.userServiceProcessSuffix(-1);
            fail("negative generation must be rejected");
        } catch (IllegalArgumentException expected) {
            assertTrue(expected.getMessage().contains("positive"));
        }
    }

}
