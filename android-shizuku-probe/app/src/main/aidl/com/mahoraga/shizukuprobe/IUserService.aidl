package com.mahoraga.shizukuprobe;

interface IUserService {
    int getProtocolVersion();
    void runIdentityProbe(String requestId, IProbeCallback callback);
    void cancelIdentityProbe(String requestId);
    void destroy() = 16777114;
}