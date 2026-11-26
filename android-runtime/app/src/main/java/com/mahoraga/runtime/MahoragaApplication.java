package com.mahoraga.runtime;

import android.app.Application;
import android.content.ComponentCallbacks2;
import android.util.Log;

import androidx.annotation.NonNull;
import androidx.work.Configuration;

import java.util.concurrent.Executors;

public final class MahoragaApplication extends Application
        implements Configuration.Provider, ComponentCallbacks2 {

    private volatile ModelEngineOwner modelEngineOwner;

    public synchronized ModelEngineOwner getModelEngineOwner() {
        if (modelEngineOwner == null) {
            modelEngineOwner = new ModelEngineOwner(getApplicationContext());
        }
        return modelEngineOwner;
    }

    @NonNull
    @Override
    public Configuration getWorkManagerConfiguration() {
        return new Configuration.Builder()
                .setMinimumLoggingLevel(Log.INFO)
                .setExecutor(Executors.newSingleThreadExecutor())
                .build();
    }

    @Override
    public void onTrimMemory(int level) {
        super.onTrimMemory(level);
        if (level >= ComponentCallbacks2.TRIM_MEMORY_RUNNING_LOW) {
            ModelEngineOwner owner = modelEngineOwner;
            if (owner != null) owner.unloadForMemoryPressure();
        }
    }

    @Override
    public void onLowMemory() {
        super.onLowMemory();
        ModelEngineOwner owner = modelEngineOwner;
        if (owner != null) owner.unloadForMemoryPressure();
    }

    @Override
    public void onConfigurationChanged(android.content.res.Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
    }
}
