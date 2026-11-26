package com.mahoraga.shizukuprobe;

import android.app.Application;

import rikka.shizuku.ShizukuProvider;

public final class ProbeApplication extends Application {
    static {
        // This probe accepts only Shizuku ADB/shell UID 2000, never Sui/root UID 0.
        ShizukuProvider.disableAutomaticSuiInitialization();
    }
}
