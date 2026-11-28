package com.mahoraga.capabilitylab;

import java.lang.reflect.Field;

import org.junit.Test;

import static org.junit.Assert.assertNotEquals;

public final class MainActivityReportFieldTest {
    private static void assertNoLatestReportField(Class<?> type) {
        for (Field field : type.getDeclaredFields()) {
            assertNotEquals("Activity must not cache the report in a separate field",
                    "latestReport", field.getName());
        }
    }

    @Test
    public void activityDoesNotCacheItsOwnLatestReport() {
        assertNoLatestReportField(MainActivity.class);
    }

    @Test(expected = AssertionError.class)
    public void detectsAFieldRegardlessOfItsType() {
        assertNoLatestReportField(ActivityWithArrayField.class);
    }

    @Test
    public void ignoresLocalVariables() {
        assertNoLatestReportField(ActivityWithLocalVariable.class);
    }

    private static final class ActivityWithArrayField {
        private String[] latestReport;
    }

    private static final class ActivityWithLocalVariable {
        void observe() {
            String latestReport = "";
        }
    }
}
