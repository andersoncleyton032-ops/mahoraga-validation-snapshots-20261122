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
import java.util.concurrent.SynchronousQueue;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

import rikka.shizuku.Shizuku;

public final class MainActivity extends Activity {
    private static final String SHIZUKU_PACKAGE = "moe.shizuku.privileged.api";
    private static final int PERMISSION_REQUEST_CODE = 4202;

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private static final SerialCommandQueue lifecycleExecutor =
            new SerialCommandQueue("mahoraga-ipc-lifecycle");
    private static final ExecutorService handshakeExecutor = new ThreadPoolExecutor(
            0, 2, 30L, TimeUnit.SECONDS, new SynchronousQueue<>(),
            daemonFactory("mahoraga-ipc-handshake"), new ThreadPoolExecutor.AbortPolicy()
    );
    private static final ServiceLifecycle lifecycle = new ServiceLifecycle();

    private TextView statusView;
    private Button permissionButton;
    private Button bindButton;
    private Button runButton;
    private Button cancelButton;
    private Button stopButton;

    private ShizukuProbeState shizukuState = ShizukuProbeState.binderUnavailable(false);
    private String serviceState = "STOPPED";
    private String lastResult = "No operation executed";
    private volatile ConnectionContext currentContext;

    private final Shizuku.OnBinderReceivedListener binderReceivedListener =
            this::refreshFromBinder;
    private final Shizuku.OnBinderDeadListener binderDeadListener =
            this::onShizukuBinderDead;
    private final Shizuku.OnRequestPermissionResultListener permissionResultListener =
            this::onPermissionResult;

    private Shizuku.UserServiceArgs createUserServiceArgs(long generation) {
        return new Shizuku.UserServiceArgs(
                new ComponentName(getPackageName(), UserService.class.getName())
        )
                .daemon(false)
                .processNameSuffix(ProbeContract.userServiceProcessSuffix(generation))
                .tag(ProbeContract.userServiceTag(generation))
                .version(ProbeContract.USER_SERVICE_VERSION)
                .debuggable(false);
    }

    private static ThreadFactory daemonFactory(String name) {
        return runnable -> {
            Thread thread = new Thread(runnable, name);
            thread.setDaemon(true);
            return thread;
        };
    }

    private final class ConnectionContext {
        final ServiceLifecycle.Session token;
        final Shizuku.UserServiceArgs userServiceArgs;
        final OneShotGate handshakeFinished = new OneShotGate();
        final ServiceConnection connection;
        volatile boolean bindRequested;
        IUserService service;
        IBinder binder;
        ServiceLifecycle.Operation operation;
        Runnable bindTimeout;
        Runnable handshakeTimeout;
        Runnable operationTimeout;
        IBinder.DeathRecipient deathRecipient;

        ConnectionContext(ServiceLifecycle.Session token) {
            this.token = token;
            this.userServiceArgs = createUserServiceArgs(token.generation);
            this.connection = new ServiceConnection() {
                @Override
                public void onServiceConnected(ComponentName name, IBinder connectedBinder) {
                    mainHandler.post(() -> handleUserServiceConnected(
                            ConnectionContext.this, connectedBinder
                    ));
                }

                @Override
                public void onServiceDisconnected(ComponentName name) {
                    mainHandler.post(() -> stopUserService(
                            ConnectionContext.this, "USER_SERVICE_DISCONNECTED"
                    ));
                }
            };
        }
    }

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
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
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
        stopButton.setOnClickListener(view -> {
            ConnectionContext context = currentContext;
            if (context != null) stopUserService(context, "STOPPED_BY_USER");
        });
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
        ConnectionContext context = currentContext;
        if (context != null) stopUserService(context, "ACTIVITY_STOPPED");
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        Shizuku.removeRequestPermissionResultListener(permissionResultListener);
        ConnectionContext context = currentContext;
        if (context != null) stopUserService(context, "ACTIVITY_DESTROYED");
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
        ConnectionContext context = currentContext;
        if (context != null) stopUserService(context, "SHIZUKU_BINDER_DIED");
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
        if (!shizukuState.isShellReady()) {
            serviceState = "BLOCKED: requires Binder + permission + UID 2000";
            renderState();
            return;
        }
        ServiceLifecycle.Session token = lifecycle.begin();
        if (token == null) {
            serviceState = "BLOCKED: UserService lifecycle already active";
            renderState();
            return;
        }

        ConnectionContext context = new ConnectionContext(token);
        currentContext = context;
        context.bindRequested = true;
        serviceState = "BINDING #" + token.generation;
        context.bindTimeout = () -> {
            if (lifecycle.isCurrent(token) && token.state() == ServiceLifecycle.State.BINDING) {
                stopUserService(context, "BIND_TIMEOUT");
            }
        };
        mainHandler.postDelayed(context.bindTimeout, ProbeContract.BIND_TIMEOUT_MS);
        renderState();

        lifecycleExecutor.execute(() -> {
            try {
                if (token.isClosed()) return;
                if (!Shizuku.pingBinder()
                        || Shizuku.checkSelfPermission() != PackageManager.PERMISSION_GRANTED
                        || Shizuku.getUid() != 2000) {
                    throw new SecurityException("Shizuku shell UID 2000 is not ready");
                }
                if (token.isClosed()) return;
                Shizuku.bindUserService(context.userServiceArgs, context.connection);
            } catch (RuntimeException failure) {
                mainHandler.post(() -> {
                    if (lifecycle.isCurrent(token)) {
                        stopUserService(context,
                                "BIND_FAILED: " + failure.getClass().getSimpleName());
                    }
                });
            }
        });
    }

    private void handleUserServiceConnected(ConnectionContext context, IBinder binder) {
        if (!lifecycle.isCurrent(context.token)) {
            enqueueStaleConnectionRemoval(context);
            return;
        }
        if (binder == null || !binder.pingBinder() || isFinishing()
                || !lifecycle.markConnected(context.token)) {
            stopUserService(context, "INVALID_SERVICE_BINDER");
            return;
        }
        if (context.bindTimeout != null) {
            mainHandler.removeCallbacks(context.bindTimeout);
            context.bindTimeout = null;
        }

        context.deathRecipient = () -> mainHandler.post(() ->
                stopUserService(context, "USER_SERVICE_BINDER_DIED"));
        try {
            binder.linkToDeath(context.deathRecipient, 0);
        } catch (RemoteException dead) {
            stopUserService(context, "USER_SERVICE_DIED_DURING_BIND");
            return;
        }

        context.binder = binder;
        context.service = IUserService.Stub.asInterface(binder);
        lifecycle.markVerifying(context.token);
        serviceState = "CONNECTED; VERIFYING_PROTOCOL #" + context.token.generation;
        renderState();

        context.handshakeTimeout = () -> {
            if (context.handshakeFinished.tryFinish()
                    && lifecycle.isCurrent(context.token)) {
                stopUserService(context, "PROTOCOL_HANDSHAKE_TIMEOUT");
            }
        };
        mainHandler.postDelayed(context.handshakeTimeout, ProbeContract.HANDSHAKE_TIMEOUT_MS);

        try {
            handshakeExecutor.execute(() -> {
                try {
                    int version = context.service.getProtocolVersion();
                    mainHandler.post(() -> handleHandshakeResult(context, version, null));
                } catch (RemoteException | RuntimeException failure) {
                    mainHandler.post(() -> handleHandshakeResult(context, -1, failure));
                }
            });
        } catch (RuntimeException rejected) {
            handleHandshakeResult(context, -1, rejected);
        }
    }

    private void handleHandshakeResult(
            ConnectionContext context, int version, Exception failure
    ) {
        if (!context.handshakeFinished.tryFinish()) return;
        if (context.handshakeTimeout != null) {
            mainHandler.removeCallbacks(context.handshakeTimeout);
            context.handshakeTimeout = null;
        }
        if (!lifecycle.isCurrent(context.token)) return;
        if (failure != null || version < 0) {
            stopUserService(context, "PROTOCOL_CHECK_FAILED: "
                    + failure.getClass().getSimpleName());
            return;
        }
        if (version != ProbeContract.PROTOCOL_VERSION) {
            stopUserService(context, "PROTOCOL_MISMATCH: " + version);
            return;
        }
        if (!lifecycle.markReady(context.token)) return;
        serviceState = "CONNECTED; PROTOCOL " + version;
        renderState();
    }

    private void runIdentityProbe() {
        ConnectionContext context = currentContext;
        if (context == null || !lifecycle.isCurrent(context.token)
                || context.token.state() != ServiceLifecycle.State.READY
                || context.service == null || context.operation != null) return;

        ServiceLifecycle.Operation operation = new ServiceLifecycle.Operation(
                context.token.generation, UUID.randomUUID().toString()
        );
        context.operation = operation;
        serviceState = "OPERATION_PENDING";
        context.operationTimeout = () ->
                cancelOperation(context, operation, "OPERATION_TIMEOUT");
        mainHandler.postDelayed(context.operationTimeout, ProbeContract.OPERATION_TIMEOUT_MS);
        renderState();

        IProbeCallback callback = new IProbeCallback.Stub() {
            @Override
            public void onCompleted(
                    String requestId, int uid, int pid, long elapsedRealtimeMillis
            ) {
                mainHandler.post(() -> handleProbeCompleted(
                        context, operation, requestId, uid, pid, elapsedRealtimeMillis
                ));
            }

            @Override
            public void onRejected(String requestId, int reasonCode) {
                mainHandler.post(() -> handleProbeRejected(
                        context, operation, requestId, reasonCode
                ));
            }
        };

        lifecycleExecutor.execute(() -> {
            if (!lifecycle.isCurrent(context.token) || !operation.isPending()) return;
            try {
                context.service.runIdentityProbe(operation.requestId, callback);
            } catch (RemoteException | RuntimeException failure) {
                mainHandler.post(() -> {
                    if (!lifecycle.isCurrent(context.token)
                            || context.operation != operation || !operation.fail()) return;
                    clearOperationTimeout(context);
                    context.operation = null;
                    serviceState = "OPERATION_FAILED: "
                            + failure.getClass().getSimpleName();
                    renderState();
                });
            }
        });
    }

    private void handleProbeCompleted(
            ConnectionContext context, ServiceLifecycle.Operation operation,
            String requestId, int uid, int pid, long elapsedRealtimeMillis
    ) {
        if (!isCurrentOperation(context, operation, requestId) || !operation.complete()) return;
        clearOperationTimeout(context);
        context.operation = null;
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

    private void handleProbeRejected(
            ConnectionContext context, ServiceLifecycle.Operation operation,
            String requestId, int reasonCode
    ) {
        if (!isCurrentOperation(context, operation, requestId) || !operation.complete()) return;
        clearOperationTimeout(context);
        context.operation = null;
        serviceState = "OPERATION_REJECTED: " + reasonCode;
        renderState();
    }

    private boolean isCurrentOperation(
            ConnectionContext context, ServiceLifecycle.Operation operation, String requestId
    ) {
        return lifecycle.isCurrent(context.token)
                && context.operation == operation
                && operation.generation == context.token.generation
                && operation.requestId.equals(requestId);
    }

    private void cancelIdentityProbe() {
        ConnectionContext context = currentContext;
        if (context != null && context.operation != null) {
            cancelOperation(context, context.operation, "CANCEL_REQUESTED");
        }
    }

    private void cancelOperation(
            ConnectionContext context, ServiceLifecycle.Operation operation, String terminalState
    ) {
        if (!lifecycle.isCurrent(context.token)
                || context.operation != operation || !operation.cancel()) return;
        clearOperationTimeout(context);
        context.operation = null;
        serviceState = terminalState;
        lifecycleExecutor.execute(() -> {
            if (context.service == null || !Shizuku.pingBinder()) return;
            try {
                context.service.cancelIdentityProbe(operation.requestId);
            } catch (RemoteException | RuntimeException ignored) {
                // The local terminal gate already suppresses late callbacks.
            }
        });
        renderState();
    }

    private void clearOperationTimeout(ConnectionContext context) {
        if (context.operationTimeout != null) {
            mainHandler.removeCallbacks(context.operationTimeout);
            context.operationTimeout = null;
        }
    }

    private void enqueueStaleConnectionRemoval(ConnectionContext context) {
        if (!context.bindRequested) return;
        lifecycleExecutor.execute(() -> {
            if (!Shizuku.pingBinder()) return;
            try {
                removeUserServiceGeneration(context);
            } catch (RuntimeException ignored) {
                // Binder may have died; the old generation is already invalidated.
            }
        });
    }

    private void removeUserServiceGeneration(ConnectionContext context) {
        // remove=false unregisters this generation's callback and evicts the client-side
        // ShizukuServiceConnections cache entry. remove=true then destroys only this tag.
        try {
            Shizuku.unbindUserService(context.userServiceArgs, context.connection, false);
        } catch (RuntimeException ignored) {
            // Continue: remove=true is still required to stop the generation.
        }
        try {
            Shizuku.unbindUserService(context.userServiceArgs, context.connection, true);
        } catch (RuntimeException ignored) {
            // Binder death or prior removal can make final removal unavailable.
        }
    }

    private void stopUserService(ConnectionContext context, String reason) {
        if (!lifecycle.invalidate(context.token)) return;
        if (currentContext == context) currentContext = null;

        if (context.bindTimeout != null) {
            mainHandler.removeCallbacks(context.bindTimeout);
            context.bindTimeout = null;
        }
        if (context.handshakeTimeout != null) {
            mainHandler.removeCallbacks(context.handshakeTimeout);
            context.handshakeTimeout = null;
        }

        clearOperationTimeout(context);
        ServiceLifecycle.Operation operation = context.operation;
        context.operation = null;
        if (operation != null) operation.cancel();

        if (context.binder != null && context.deathRecipient != null
                && context.binder.isBinderAlive()) {
            context.binder.unlinkToDeath(context.deathRecipient, 0);
        }

        if (context.bindRequested) {
            lifecycleExecutor.execute(() -> {
                if (operation != null && context.service != null && Shizuku.pingBinder()) {
                    try {
                        context.service.cancelIdentityProbe(operation.requestId);
                    } catch (RemoteException | RuntimeException ignored) {
                        // Continue with scoped unbind.
                    }
                }
                if (!Shizuku.pingBinder()) return;
                removeUserServiceGeneration(context);
            });
        }

        serviceState = reason;
        renderState();
    }

    private void renderState() {
        if (statusView == null) return;
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

        ConnectionContext context = currentContext;
        boolean active = context != null && lifecycle.isCurrent(context.token);
        boolean pending = active && context.operation != null
                && context.operation.isPending();
        permissionButton.setEnabled(shizukuState.canRequestPermission());
        bindButton.setEnabled(shizukuState.isShellReady() && !active);
        runButton.setEnabled(active
                && context.token.state() == ServiceLifecycle.State.READY
                && context.operation == null);
        cancelButton.setEnabled(pending);
        stopButton.setEnabled(active);
    }
}
