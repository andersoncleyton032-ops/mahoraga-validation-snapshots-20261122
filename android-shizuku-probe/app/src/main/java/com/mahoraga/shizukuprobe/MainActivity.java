package com.mahoraga.shizukuprobe;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ComponentName;
import android.content.ServiceConnection;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.RemoteException;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import rikka.shizuku.Shizuku;

public final class MainActivity extends Activity {
    private static final String SHIZUKU_PACKAGE = "moe.shizuku.privileged.api";
    private static final int PERMISSION_REQUEST_CODE = 4202;

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService ipcExecutor = Executors.newSingleThreadExecutor();
    private final ExecutorService cleanupExecutor = Executors.newSingleThreadExecutor();
    private volatile long serviceGeneration = 0;

    private TextView statusView;
    private Button permissionButton;
    private Button bindButton;
    private Button runButton;
    private Button cancelButton;
    private Button stopButton;

    private ShizukuProbeState shizukuState = ShizukuProbeState.binderUnavailable(false);
    private String serviceState = "STOPPED";
    private String lastResult = "No operation executed";
    private boolean binding;
    private boolean serviceBound;
    private boolean protocolReady;
    private IUserService userService;
    private IBinder userServiceBinder;
    private String pendingRequestId;
    private Runnable bindTimeout;
    private Runnable operationTimeout;

    private final Shizuku.UserServiceArgs userServiceArgs =
            new Shizuku.UserServiceArgs(
                    new ComponentName("com.mahoraga.shizukuprobe", UserService.class.getName())
            )
                    .daemon(false)
                    .processNameSuffix("mahoraga_probe")
                    .tag("mahoraga.shizuku.probe.alpha2")
                    .version(ProbeContract.USER_SERVICE_VERSION)
                    .debuggable(false);

    private final Shizuku.OnBinderReceivedListener binderReceivedListener =
            this::refreshFromBinder;
    private final Shizuku.OnBinderDeadListener binderDeadListener =
            this::onShizukuBinderDead;
    private final Shizuku.OnRequestPermissionResultListener permissionResultListener =
            this::onPermissionResult;

    private final IBinder.DeathRecipient userServiceDeathRecipient =
            () -> mainHandler.post(() -> stopUserService("USER_SERVICE_BINDER_DIED"));

    private final IProbeCallback probeCallback = new IProbeCallback.Stub() {
        @Override
        public void onCompleted(
                String requestId, int uid, int pid, long elapsedRealtimeMillis
        ) {
            mainHandler.post(() -> handleProbeCompleted(
                    requestId, uid, pid, elapsedRealtimeMillis
            ));
        }

        @Override
        public void onRejected(String requestId, int reasonCode) {
            mainHandler.post(() -> handleProbeRejected(requestId, reasonCode));
        }
    };

    private final ServiceConnection userServiceConnection = new ServiceConnection() {
        @Override
        public void onServiceConnected(ComponentName name, IBinder binder) {
            mainHandler.post(() -> handleUserServiceConnected(binder));
        }

        @Override
        public void onServiceDisconnected(ComponentName name) {
            mainHandler.post(() -> stopUserService("USER_SERVICE_DISCONNECTED"));
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int padding = (int) (18 * getResources().getDisplayMetrics().density);
        layout.setPadding(padding, padding, padding, padding);

        TextView heading = new TextView(this);
        heading.setText(
                "Mahoraga Shizuku Probe v0.2-alpha2\n\n"
                + "UserService isolado: somente identidade UID/PID e versão do protocolo. "
                + "Sem shell arbitrário, escrita no sistema, rede ou persistência."
        );
        layout.addView(heading, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        Button refreshButton = new Button(this);
        refreshButton.setText("Atualizar estado Shizuku");
        refreshButton.setOnClickListener(view -> refreshFromBinder());
        layout.addView(refreshButton);

        permissionButton = new Button(this);
        permissionButton.setText("Solicitar permissão Shizuku");
        permissionButton.setOnClickListener(view -> requestPermissionFromUserAction());
        layout.addView(permissionButton);

        bindButton = new Button(this);
        bindButton.setText("Iniciar UserService de teste");
        bindButton.setOnClickListener(view -> startUserService());
        layout.addView(bindButton);

        runButton = new Button(this);
        runButton.setText("Executar prova de identidade");
        runButton.setOnClickListener(view -> runIdentityProbe());
        layout.addView(runButton);

        cancelButton = new Button(this);
        cancelButton.setText("Cancelar operação");
        cancelButton.setOnClickListener(view -> cancelIdentityProbe());
        layout.addView(cancelButton);

        stopButton = new Button(this);
        stopButton.setText("Encerrar UserService");
        stopButton.setOnClickListener(view -> stopUserService("STOPPED_BY_USER"));
        layout.addView(stopButton);

        statusView = new TextView(this);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(statusView);
        layout.addView(scroll, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f
        ));

        setContentView(layout);
        Shizuku.addRequestPermissionResultListener(permissionResultListener, mainHandler);
        renderState();
    }

    @Override
    protected void onStart() {
        super.onStart();
        Shizuku.addBinderReceivedListenerSticky(binderReceivedListener, mainHandler);
        Shizuku.addBinderDeadListener(binderDeadListener, mainHandler);
        refreshFromBinder();
    }

    @Override
    protected void onStop() {
        Shizuku.removeBinderReceivedListener(binderReceivedListener);
        Shizuku.removeBinderDeadListener(binderDeadListener);
        stopUserService("ACTIVITY_STOPPED");
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        Shizuku.removeRequestPermissionResultListener(permissionResultListener);
        stopUserService("ACTIVITY_DESTROYED");
        ipcExecutor.shutdown();
        cleanupExecutor.shutdown();
        super.onDestroy();
    }

    private boolean isShizukuInstalled() {
        try {
            getPackageManager().getPackageInfo(SHIZUKU_PACKAGE, 0);
            return true;
        } catch (PackageManager.NameNotFoundException ignored) {
            return false;
        }
    }

    private void refreshFromBinder() {
        boolean installed = isShizukuInstalled();
        try {
            if (!Shizuku.pingBinder()) {
                shizukuState = ShizukuProbeState.binderUnavailable(installed);
            } else if (Shizuku.isPreV11()) {
                shizukuState = ShizukuProbeState.unsupported(installed);
            } else if (Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED) {
                shizukuState = ShizukuProbeState.permissionGranted(installed, Shizuku.getUid());
            } else {
                shizukuState = ShizukuProbeState.permissionDenied(
                        installed, Shizuku.shouldShowRequestPermissionRationale()
                );
            }
        } catch (RuntimeException binderError) {
            shizukuState = ShizukuProbeState.binderUnavailable(installed);
        }
        renderState();
    }

    private void onShizukuBinderDead() {
        shizukuState = ShizukuProbeState.binderUnavailable(isShizukuInstalled());
        stopUserService("SHIZUKU_BINDER_DIED");
        renderState();
    }

    private void onPermissionResult(int requestCode, int grantResult) {
        if (requestCode != PERMISSION_REQUEST_CODE) return;
        if (grantResult == PackageManager.PERMISSION_GRANTED) {
            refreshFromBinder();
        } else {
            boolean rationale = false;
            try {
                rationale = Shizuku.shouldShowRequestPermissionRationale();
            } catch (RuntimeException ignored) {
                // Binder may have died while the permission UI was open.
            }
            shizukuState = ShizukuProbeState.permissionDenied(isShizukuInstalled(), rationale);
            renderState();
        }
    }

    private void requestPermissionFromUserAction() {
        if (!Shizuku.pingBinder()) {
            refreshFromBinder();
            return;
        }
        if (Shizuku.isPreV11()) {
            shizukuState = ShizukuProbeState.unsupported(isShizukuInstalled());
            renderState();
            return;
        }
        try {
            if (Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED) {
                refreshFromBinder();
                return;
            }
            if (Shizuku.shouldShowRequestPermissionRationale()) {
                new AlertDialog.Builder(this)
                        .setTitle("Permissão Shizuku")
                        .setMessage(
                                "O Alpha2 inicia um processo UserService separado e executa "
                                + "somente uma leitura da identidade UID/PID. Nenhum comando "
                                + "arbitrário ou alteração do sistema será executado."
                        )
                        .setNegativeButton("Cancelar", (dialog, which) -> dialog.dismiss())
                        .setPositiveButton("Continuar", (dialog, which) ->
                                Shizuku.requestPermission(PERMISSION_REQUEST_CODE))
                        .show();
            } else {
                Shizuku.requestPermission(PERMISSION_REQUEST_CODE);
            }
        } catch (RuntimeException binderError) {
            shizukuState = ShizukuProbeState.binderUnavailable(isShizukuInstalled());
            renderState();
        }
    }

    private void startUserService() {
        refreshFromBinder();
        if (!shizukuState.isShellReady() || binding || serviceBound) {
            serviceState = "BLOCKED: requires Binder + permission + UID 2000";
            renderState();
            return;
        }

        binding = true;
        protocolReady = false;
        serviceState = "BINDING";
        long attempt = ++serviceGeneration;
        bindTimeout = () -> {
            if (binding && serviceGeneration == attempt) {
                stopUserService("BIND_TIMEOUT");
            }
        };
        mainHandler.postDelayed(bindTimeout, ProbeContract.BIND_TIMEOUT_MS);
        renderState();

        ipcExecutor.execute(() -> {
            try {
                if (serviceGeneration != attempt) return;
                if (!Shizuku.pingBinder()
                        || Shizuku.checkSelfPermission() != PackageManager.PERMISSION_GRANTED
                        || Shizuku.getUid() != 2000) {
                    throw new SecurityException("Shizuku shell UID 2000 is not ready");
                }
                Shizuku.bindUserService(userServiceArgs, userServiceConnection);
            } catch (RuntimeException failure) {
                mainHandler.post(() -> {
                    if (serviceGeneration == attempt) {
                        stopUserService("BIND_FAILED: " + failure.getClass().getSimpleName());
                    }
                });
            }
        });
    }

    private void handleUserServiceConnected(IBinder binder) {
        if (!binding || isFinishing() || binder == null || !binder.pingBinder()) {
            if (!binding && binder != null && Shizuku.pingBinder()) {
                cleanupExecutor.execute(() -> {
                    try {
                        Shizuku.unbindUserService(userServiceArgs, userServiceConnection, true);
                    } catch (RuntimeException ignored) {
                        // Best-effort cleanup for a late connection callback.
                    }
                });
            }
            stopUserService("INVALID_OR_LATE_SERVICE_BINDER");
            return;
        }
        if (bindTimeout != null) {
            mainHandler.removeCallbacks(bindTimeout);
            bindTimeout = null;
        }
        try {
            binder.linkToDeath(userServiceDeathRecipient, 0);
        } catch (RemoteException dead) {
            stopUserService("USER_SERVICE_DIED_DURING_BIND");
            return;
        }

        userServiceBinder = binder;
        userService = IUserService.Stub.asInterface(binder);
        binding = false;
        serviceBound = true;
        serviceState = "CONNECTED; VERIFYING_PROTOCOL";
        renderState();

        IUserService connectedService = userService;
        ipcExecutor.execute(() -> {
            try {
                int version = connectedService.getProtocolVersion();
                mainHandler.post(() -> {
                    if (serviceBound && version == ProbeContract.PROTOCOL_VERSION) {
                        protocolReady = true;
                        serviceState = "CONNECTED; PROTOCOL " + version;
                    } else if (serviceBound) {
                        protocolReady = false;
                        serviceState = "PROTOCOL_MISMATCH: " + version;
                    }
                    renderState();
                });
            } catch (RemoteException | RuntimeException failure) {
                mainHandler.post(() -> stopUserService(
                        "PROTOCOL_CHECK_FAILED: " + failure.getClass().getSimpleName()
                ));
            }
        });
    }

    private void runIdentityProbe() {
        if (!serviceBound || !protocolReady || userService == null || pendingRequestId != null) {
            return;
        }
        String requestId = UUID.randomUUID().toString();
        pendingRequestId = requestId;
        serviceState = "OPERATION_PENDING";
        operationTimeout = () -> {
            if (requestId.equals(pendingRequestId)) {
                cancelIdentityProbe();
                serviceState = "OPERATION_TIMEOUT";
                renderState();
            }
        };
        mainHandler.postDelayed(operationTimeout, ProbeContract.OPERATION_TIMEOUT_MS);
        renderState();

        IUserService service = userService;
        ipcExecutor.execute(() -> {
            try {
                service.runIdentityProbe(requestId, probeCallback);
            } catch (RemoteException | RuntimeException failure) {
                mainHandler.post(() -> {
                    if (requestId.equals(pendingRequestId)) {
                        clearPendingOperation();
                        serviceState = "OPERATION_FAILED: "
                                + failure.getClass().getSimpleName();
                        renderState();
                    }
                });
            }
        });
    }

    private void handleProbeCompleted(
            String requestId, int uid, int pid, long elapsedRealtimeMillis
    ) {
        if (!requestId.equals(pendingRequestId)) return;
        clearPendingOperation();
        if (uid == 2000 && pid > 0) {
            serviceState = "IDENTITY_CONFIRMED";
            lastResult = "UserService UID=" + uid + ", PID=" + pid
                    + ", elapsedRealtimeMs=" + elapsedRealtimeMillis;
        } else {
            serviceState = "IDENTITY_REJECTED";
            lastResult = "Unexpected UserService identity UID=" + uid + ", PID=" + pid;
        }
        renderState();
    }

    private void handleProbeRejected(String requestId, int reasonCode) {
        if (!requestId.equals(pendingRequestId)) return;
        clearPendingOperation();
        serviceState = "OPERATION_REJECTED: " + reasonCode;
        renderState();
    }

    private void cancelIdentityProbe() {
        String requestId = pendingRequestId;
        if (requestId == null) return;
        clearPendingOperation();
        serviceState = "CANCEL_REQUESTED";
        IUserService service = userService;
        if (service != null) {
            cleanupExecutor.execute(() -> {
                try {
                    service.cancelIdentityProbe(requestId);
                } catch (RemoteException | RuntimeException ignored) {
                    // A dead service is handled by the Binder death path.
                }
            });
        }
        renderState();
    }

    private void clearPendingOperation() {
        if (operationTimeout != null) {
            mainHandler.removeCallbacks(operationTimeout);
            operationTimeout = null;
        }
        pendingRequestId = null;
    }

    private void stopUserService(String reason) {
        boolean shouldUnbind = binding || serviceBound;
        binding = false;
        serviceBound = false;
        protocolReady = false;
        serviceGeneration++;
        if (bindTimeout != null) {
            mainHandler.removeCallbacks(bindTimeout);
            bindTimeout = null;
        }
        String requestId = pendingRequestId;
        clearPendingOperation();

        IUserService oldService = userService;
        IBinder oldBinder = userServiceBinder;
        userService = null;
        userServiceBinder = null;
        if (oldBinder != null && oldBinder.isBinderAlive()) {
            oldBinder.unlinkToDeath(userServiceDeathRecipient, 0);
        }

        if (shouldUnbind && Shizuku.pingBinder()) {
            cleanupExecutor.execute(() -> {
                if (oldService != null && requestId != null) {
                    try {
                        oldService.cancelIdentityProbe(requestId);
                    } catch (RemoteException | RuntimeException ignored) {
                        // Continue to explicit service removal.
                    }
                }
                try {
                    Shizuku.unbindUserService(userServiceArgs, userServiceConnection, true);
                } catch (RuntimeException ignored) {
                    // Binder-death and timeout states remain visible in the UI.
                }
            });
        }

        serviceState = reason;
        renderState();
    }

    private void renderState() {
        String uid = shizukuState.getUid() < 0
                ? "UNKNOWN" : Integer.toString(shizukuState.getUid());
        String readiness = shizukuState.isShellReady()
                ? "READY_SHELL_UID_2000"
                : (shizukuState.isRootRejected()
                    ? "REJECTED_ROOT_UID_0"
                    : (shizukuState.isOtherIdentityRejected()
                        ? "REJECTED_UNEXPECTED_UID" : "NOT_READY"));

        statusView.setText(
                "Shizuku instalado: " + shizukuState.isShizukuInstalled()
                + "\nBinder: " + shizukuState.getBinderState().name()
                + "\nPermissão: " + shizukuState.getPermissionState().name()
                + "\nUID Shizuku: " + uid
                + "\nEstado Shizuku: " + readiness
                + "\n\nUserService: " + serviceState
                + "\nResultado: " + lastResult
                + "\n\nA operação permitida lê somente UID/PID do processo remoto."
        );

        permissionButton.setEnabled(shizukuState.canRequestPermission());
        bindButton.setEnabled(shizukuState.isShellReady() && !binding && !serviceBound);
        runButton.setEnabled(serviceBound && protocolReady && pendingRequestId == null);
        cancelButton.setEnabled(pendingRequestId != null);
        stopButton.setEnabled(binding || serviceBound);
    }
}