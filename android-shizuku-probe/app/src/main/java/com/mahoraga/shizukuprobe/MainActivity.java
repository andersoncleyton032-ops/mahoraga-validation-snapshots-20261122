package com.mahoraga.shizukuprobe;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import rikka.shizuku.Shizuku;

public final class MainActivity extends Activity {
    private static final String SHIZUKU_PACKAGE = "moe.shizuku.privileged.api";
    private static final int REQUEST_CODE = 4202;

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private TextView statusView;
    private Button requestButton;
    private ShizukuProbeState state = ShizukuProbeState.binderUnavailable(false);

    private final Shizuku.OnBinderReceivedListener binderReceivedListener =
            this::refreshFromBinder;
    private final Shizuku.OnBinderDeadListener binderDeadListener =
            this::onBinderDead;
    private final Shizuku.OnRequestPermissionResultListener permissionResultListener =
            this::onPermissionResult;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int padding = (int) (18 * getResources().getDisplayMetrics().density);
        layout.setPadding(padding, padding, padding, padding);

        TextView heading = new TextView(this);
        heading.setText(
                "Mahoraga Shizuku Probe v0.2-alpha1\n\n"
                + "Sonda somente de Binder, permissão e identidade. "
                + "Não executa comandos, não inicia UserService, não altera o sistema "
                + "e não envia dados pela rede. UID aceito: somente shell/ADB 2000."
        );
        layout.addView(heading, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        Button refreshButton = new Button(this);
        refreshButton.setText("Atualizar estado");
        refreshButton.setOnClickListener(view -> refreshFromBinder());
        layout.addView(refreshButton);

        requestButton = new Button(this);
        requestButton.setText("Solicitar permissão Shizuku");
        requestButton.setOnClickListener(view -> requestPermissionFromUserAction());
        layout.addView(requestButton);

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
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        Shizuku.removeRequestPermissionResultListener(permissionResultListener);
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
                state = ShizukuProbeState.binderUnavailable(installed);
            } else if (Shizuku.isPreV11()) {
                state = ShizukuProbeState.unsupported(installed);
            } else if (Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED) {
                state = ShizukuProbeState.permissionGranted(installed, Shizuku.getUid());
            } else {
                state = ShizukuProbeState.permissionDenied(
                        installed, Shizuku.shouldShowRequestPermissionRationale()
                );
            }
        } catch (RuntimeException binderError) {
            state = ShizukuProbeState.binderUnavailable(installed);
        }
        renderState();
    }

    private void onBinderDead() {
        state = ShizukuProbeState.binderUnavailable(isShizukuInstalled());
        renderState();
    }

    private void onPermissionResult(int requestCode, int grantResult) {
        if (requestCode != REQUEST_CODE) {
            return;
        }
        if (!Shizuku.pingBinder()) {
            state = ShizukuProbeState.binderUnavailable(isShizukuInstalled());
        } else if (grantResult == PackageManager.PERMISSION_GRANTED) {
            refreshFromBinder();
            return;
        } else {
            boolean rationale = false;
            try {
                rationale = Shizuku.shouldShowRequestPermissionRationale();
            } catch (RuntimeException ignored) {
                rationale = false;
            }
            state = ShizukuProbeState.permissionDenied(isShizukuInstalled(), rationale);
        }
        renderState();
    }

    private void requestPermissionFromUserAction() {
        if (!Shizuku.pingBinder()) {
            refreshFromBinder();
            return;
        }
        if (Shizuku.isPreV11()) {
            state = ShizukuProbeState.unsupported(isShizukuInstalled());
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
                                "O probe precisa apenas confirmar a identidade shell/ADB (UID 2000). "
                                + "Nenhum comando privilegiado será executado."
                        )
                        .setNegativeButton("Cancelar", (dialog, which) -> dialog.dismiss())
                        .setPositiveButton("Continuar", (dialog, which) ->
                                Shizuku.requestPermission(REQUEST_CODE))
                        .show();
            } else {
                Shizuku.requestPermission(REQUEST_CODE);
            }
        } catch (RuntimeException binderError) {
            state = ShizukuProbeState.binderUnavailable(isShizukuInstalled());
            renderState();
        }
    }

    private void renderState() {
        String binder;
        switch (state.getBinderState()) {
            case AVAILABLE:
                binder = "AVAILABLE";
                break;
            case UNSUPPORTED:
                binder = "UNSUPPORTED (Shizuku API pre-v11)";
                break;
            default:
                binder = "UNAVAILABLE";
                break;
        }

        String permission = state.getPermissionState().name();
        String identity = state.getUid() < 0 ? "UNKNOWN" : Integer.toString(state.getUid());
        String readiness;
        if (state.isShellReady()) {
            readiness = "READY_SHELL_UID_2000";
        } else if (state.isRootRejected()) {
            readiness = "REJECTED_ROOT_UID_0";
        } else if (state.isOtherIdentityRejected()) {
            readiness = "REJECTED_UNEXPECTED_UID";
        } else {
            readiness = "NOT_READY";
        }

        statusView.setText(
                "Shizuku instalado: " + state.isShizukuInstalled()
                + "\nBinder: " + binder
                + "\nPermissão: " + permission
                + "\nUID efetivo: " + identity
                + "\nEstado: " + readiness
                + "\n\nNenhuma operação privilegiada foi executada."
        );
        requestButton.setEnabled(state.canRequestPermission());
    }
}
