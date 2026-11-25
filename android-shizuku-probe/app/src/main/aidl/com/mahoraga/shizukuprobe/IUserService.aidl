package com.mahoraga.shizukuprobe;

import com.mahoraga.shizukuprobe.IProbeCallback;

interface IUserService {
    int getProtocolVersion();
    void runIdentityProbe(String requestId, IProbeCallback callback);
    void cancelIdentityProbe(String requestId);
    void destroy() = 16777114;
}