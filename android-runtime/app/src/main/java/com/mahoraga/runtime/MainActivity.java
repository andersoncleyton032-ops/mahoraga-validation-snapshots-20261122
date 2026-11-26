package com.mahoraga.runtime;

import android.app.Activity;
import android.os.Handler;
import android.os.Looper;
import android.os.Bundle;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.work.WorkInfo;
import androidx.work.WorkManager;

public final class MainActivity extends Activity {
    private TextView status;
    private TextView oneShotStatus;
    private TextView pollStatus;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int padding = (int) (20 * getResources().getDisplayMetrics().density);
        layout.setPadding(padding, padding, padding, padding);

        TextView explanation = new TextView(this);
        explanation.setText(
                "Mahoraga Android Bridge\n\n"
                + "Agenda invocações curtas pelo WorkManager. Cada invocação "
                + "pede ao Termux uma única tarefa local e checkpointable.\n\n"
                + "A admissão é adaptativa: carregamento é opcional, 2 GiB de RAM/armazenamento "
                + "são preferenciais e limites críticos são avaliados pelo Governor. "
                + "O Android pode adiar execuções. Sem permissão INTERNET, microfone ou localização.\n\n"
                + "Requisitos configurados manualmente: Termux >= 0.109, permissão "
                + "RUN_COMMAND concedida a este app e allow-external-apps=true no Termux. "
                + "Este app não altera essas configurações."
        );
        layout.addView(explanation, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        status = new TextView(this);
        status.setText("\nEstado: desativado.");
        layout.addView(status);

        TextView prerequisites = new TextView(this);
        prerequisites.setText("Requisitos manuais do Termux:\\n- Termux 0.109 ou superior\\n- Permissão RUN_COMMAND concedida ao Bridge\\n- allow-external-apps=true em termux.properties\\n- $PREFIX/bin/timeout disponível\\nO Bridge não altera essas configurações.");
        layout.addView(prerequisites);

        oneShotStatus = new TextView(this);
        oneShotStatus.setText("Execução única: ainda sem leitura.");
        layout.addView(oneShotStatus);

        pollStatus = new TextView(this);
        pollStatus.setText("Polling periódico: ainda sem leitura.");
        layout.addView(pollStatus);

        Button refresh = new Button(this);
        refresh.setText("Atualizar estado das execuções");
        refresh.setOnClickListener(view -> refreshWorkStatus());
        layout.addView(refresh);

        Button start = new Button(this);
        start.setText("Ativar ciclo em segundo plano");
        start.setOnClickListener(view -> startCycle());
        layout.addView(start);

        Button stop = new Button(this);
        stop.setText("Parar novas execuções");
        stop.setOnClickListener(view -> stopCycle());
        layout.addView(stop);

        setContentView(layout);
        if (WorkScheduler.isEnabled(this)) {
            TermuxSignerPolicy.Verification signer =
                    TermuxBridge.verifyInstalledSigner(this);
            if (!signer.trusted) {
                WorkScheduler.stop(this);
                status.setText(
                        "\nAgendamento desativado: assinatura do Termux não reconhecida ("
                        + signer.reason + ")."
                );
            } else {
                status.setText(
                        "\nEstado: agendamento habilitado. Termux verificado: "
                        + signer.source + "."
                );
            }
        }
        refreshWorkStatus();
    }

    private void startCycle() {
        if (!TermuxBridge.isInstalled(this)) {
            status.setText("\nTermux não encontrado. Nenhuma tarefa foi iniciada.");
            return;
        }
        TermuxSignerPolicy.Verification signer =
                TermuxBridge.verifyInstalledSigner(this);
        if (!signer.trusted) {
            status.setText(
                    "\nAssinatura do Termux não reconhecida (" + signer.reason
                    + "). Nenhuma tarefa foi agendada."
            );
            return;
        }
        if (!TermuxBridge.hasRunCommandPermission(this)) {
            status.setText(
                    "\nPermissão RUN_COMMAND ausente. Conceda-a manualmente "
                    + "nas configurações do Android e tente novamente."
            );
            return;
        }
        WorkScheduler.start(this);
        status.setText(
                "\nAgendamento solicitado. Assinatura Termux verificada: " + signer.source
                + ". O Android decide os horários reais; a primeira execução depende "
                + "da disponibilidade de recursos e das políticas do sistema."
        );
        refreshWorkStatus();
    }


    @Override
    protected void onResume() {
        super.onResume();
        refreshWorkStatus();
    }

    private void refreshWorkStatus() {
        queryWorkStatus(WorkScheduler.ONE_SHOT_WORK, oneShotStatus, "Execução única");
        queryWorkStatus(WorkScheduler.PERIODIC_POLL_WORK, pollStatus, "Polling periódico");
    }

    private void queryWorkStatus(String uniqueName, TextView target, String label) {
        var future = WorkManager.getInstance(this).getWorkInfosForUniqueWork(uniqueName);
        future.addListener(() -> {
            String value;
            try {
                var infos = future.get();
                if (infos == null || infos.isEmpty()) {
                    value = label + ": sem trabalho registrado.";
                } else {
                    StringBuilder builder = new StringBuilder(label).append(":");
                    int shown = 0;
                    for (WorkInfo info : infos) {
                        if (shown++ >= 4) break;
                        var output = info.getOutputData();
                        builder.append("\n")
                                .append(info.getState())
                                .append(" | tentativas=")
                                .append(info.getRunAttemptCount());
                        appendField(builder, "status", output.getString("status"));
                        appendField(builder, "task", output.getString("task_id"));
                        appendField(builder, "wake", output.getString("wake_status"));
                        appendField(builder, "erro", output.getString("error_code"));
                        if (output.getKeyValueMap().containsKey("completion_receipt_valid")) {
                            builder.append(" | recibo=")
                                    .append(output.getBoolean("completion_receipt_valid", false));
                        }
                        if (output.getKeyValueMap().containsKey("queue_queued")) {
                            builder.append(" | fila=")
                                    .append(output.getInt("queue_queued", -1)).append("q/")
                                    .append(output.getInt("queue_claimed", -1)).append("c")
                                    .append(" | ativos=")
                                    .append(output.getInt("queue_active_items", -1))
                                    .append(" | rev=")
                                    .append(output.getInt("queue_revision", -1))
                                    .append(" | pendente=")
                                    .append(output.getBoolean("queue_pending", false));
                        }
                    }
                    value = builder.toString();
                }
            } catch (Exception failure) {
                value = label + ": falha ao consultar WorkManager.";
            }
            String finalValue = value;
            new Handler(Looper.getMainLooper()).post(() -> target.setText(finalValue));
        }, Runnable::run);
    }

    private static void appendField(StringBuilder builder, String label, String value) {
        if (value != null && !value.trim().isEmpty()) {
            builder.append(" | ").append(label).append("=").append(value);
        }
    }

    private void stopCycle() {
        WorkScheduler.stop(this);
        status.setText(
                "\nNovas execuções canceladas. Uma invocação Termux já iniciada "
                + "pode concluir seu checkpoint limitado."
        );
        refreshWorkStatus();
    }
}
