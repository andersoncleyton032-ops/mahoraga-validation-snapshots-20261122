package com.mahoraga.shizukuprobe;

import com.mahoraga.shizukuprobe.IProbeCallback;

interface IUserService {
    int getProtocolVersion() = 1;
    void runIdentityProbe(String requestId, IProbeCallback callback) = 2;
    void cancelIdentityProbe(String requestId) = 3;
    void destroy() = 16777114;
}