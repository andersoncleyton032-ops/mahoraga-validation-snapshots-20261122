package com.mahoraga.capabilitylab;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.os.Bundle;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

public final class MainActivity extends Activity {
    private TextView reportView;
    private final CapabilityReportSession reportSession = new CapabilityReportSession();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int padding = (int) (18 * getResources().getDisplayMetrics().density);
        layout.setPadding(padding, padding, padding, padding);

        TextView heading = new TextView(this);
        heading.setText(
                "Mahoraga Android Capability Lab v0.1\n\n"
                + "Inventário read-only de APIs e capacidades. Não solicita permissões, "
                + "não inicia câmera/microfone/MediaProjection, não agenda jobs, "
                + "não conecta Binder Shizuku e não envia dados pela rede."
        );
        layout.addView(heading, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        Button probe = new Button(this);
        probe.setText("Executar inventário read-only");
        probe.setOnClickListener(view -> runProbe());
        layout.addView(probe);

        Button copy = new Button(this);
        copy.setText("Copiar relatório JSON");
        copy.setOnClickListener(view -> copyReport());
        layout.addView(copy);

        reportView = new TextView(this);
        reportView.setText("Nenhuma coleta executada.");
        ScrollView scroll = new ScrollView(this);
        scroll.addView(reportView);
        layout.addView(scroll, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f
        ));

        setContentView(layout);
    }

    private void runProbe() {
        // A previous successful report must not survive a new, failed observation.
        reportSession.beginCollection();
        reportView.setText("Coletando inventário read-only...");
        try {
            String report = new AndroidCapabilityProbe(this).collect().toJson();
            reportSession.complete(report);
            reportView.setText(reportSession.latestReport());
        } catch (RuntimeException error) {
            reportSession.fail();
            reportView.setText("Probe failed: " + error.getClass().getSimpleName()
                    + ": " + String.valueOf(error.getMessage()));
        }
    }

    private void copyReport() {
        if (!reportSession.hasReport()) {
            reportView.setText("Execute o inventário com sucesso antes de copiar.");
            return;
        }
        ClipboardManager clipboard = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        if (clipboard != null) {
            clipboard.setPrimaryClip(ClipData.newPlainText(
                    "AndroidCapabilityReport", reportSession.latestReport()));
            reportView.setText("Relatório copiado para a área de transferência. Nenhum upload foi feito.");
        }
    }
}
