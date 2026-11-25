package com.mahoraga.shizukuprobe;

interface IProbeCallback {
    void onCompleted(String requestId, int uid, int pid, long elapsedRealtimeMillis);
    void onRejected(String requestId, int reasonCode);
}