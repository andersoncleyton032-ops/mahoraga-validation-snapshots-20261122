package com.mahoraga.runtime;

import android.app.Application;
import android.util.Log;

import androidx.annotation.NonNull;
import androidx.work.Configuration;

import java.util.concurrent.Executors;

public final class MahoragaApplication extends Application
        implements Configuration.Provider {

    @NonNull
    @Override
    public Configuration getWorkManagerConfiguration() {
        return new Configuration.Builder()
                .setMinimumLoggingLevel(Log.INFO)
                .setExecutor(Executors.newSingleThreadExecutor())
                .setMaxSchedulerLimit(1)
                .build();
    }
}
