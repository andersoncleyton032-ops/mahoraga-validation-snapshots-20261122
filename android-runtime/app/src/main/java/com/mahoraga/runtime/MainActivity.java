package com.mahoraga.runtime;

import android.app.Activity;
import android.os.Bundle;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public final class MainActivity extends Activity {
    private TextView status;

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
            status.setText("\nEstado: agendamento habilitado.");
        }
    }

    private void startCycle() {
        if (!TermuxBridge.isInstalled(this)) {
            status.setText("\nTermux não encontrado. Nenhuma tarefa foi iniciada.");
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
                "\nAgendamento solicitado. O Android decide os horários reais; "
                + "a primeira execução depende da disponibilidade de recursos e das políticas do sistema."
        );
    }

    private void stopCycle() {
        WorkScheduler.stop(this);
        status.setText(
                "\nNovas execuções canceladas. Uma invocação Termux já iniciada "
                + "pode concluir seu checkpoint limitado."
        );
    }
}
