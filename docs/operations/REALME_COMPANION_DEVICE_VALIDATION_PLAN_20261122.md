# Plano de validação real — Companion Android/Termux no Realme 14 5G
**Data:** 2026-11-22  
**Workstream:** MAH-COMPANION-DEVICE-001  
**Estado:** planejado; não executado no aparelho.

## 1. Objetivo

Comprovar o caminho completo Android WorkManager → Termux RUN_COMMAND → worker Python → IntegratedCore → fila SQLite → recibo → wake seguinte no Realme 14 5G (Android 16/API 36), distinguindo execução em primeiro plano, outro app em primeiro plano e tela apagada.

A validação não deve presumir execução contínua. WorkManager é inexacto e o fabricante pode adiar ou restringir o trabalho.

## 2. Pré-condições verificáveis

- Termux instalado e atualizado; versão e package target devem ser lidos do aparelho, não inferidos do upstream.
- Python e dependências do núcleo disponíveis no Termux.
- O checkout local deve corresponder ao commit privado aprovado para o teste; o hash do worker e os arquivos do Companion devem ser registrados.
- `$PREFIX/bin/timeout` deve existir e ser executável no sandbox do Termux. Verificar pelo próprio Termux (por exemplo, `test -x "$PREFIX/bin/timeout"`); o processo Mahoraga não pode inspecionar diretamente o armazenamento interno privado de outro app. O bridge passa o caminho fixo em RUN_COMMAND e trata a rejeição do Termux como falha fechada.
- O arquivo fixo `scripts/mahoraga_background_worker.py` deve existir e pertencer ao checkout esperado.
- O APK deve ser construído a partir do mesmo snapshot de código Android validado, com SHA-256 registrado.
- O manifesto de proveniência deve identificar o código Python correspondente. O APK não contém o worker Python.

## 3. Configurações manuais futuras

As configurações abaixo não foram alteradas. Cada uma exige ação explícita do usuário no momento do teste:

1. Permissão `com.termux.permission.RUN_COMMAND` para Mahoraga Bridge.
2. `allow-external-apps=true` em `~/.termux/termux.properties`.
3. Qualquer exceção de otimização de bateria, somente se evidência de bloqueio OEM justificar. Não conceder antecipadamente nem presumir que seja necessária.

Não conceder Draw Over Apps, localização, microfone, câmera, INTERNET ou acesso amplo a arquivos para esse fluxo.

## 4. Sequência de teste

### T0 — Integridade sem execução
- Registrar versão/target do Termux, versão do Termux:API, versão Python, presença de `timeout` verificada dentro do próprio Termux, branch/commit do núcleo e hashes dos arquivos.
- Confirmar que Mahoraga não tenta usar `File.isFile()`/`canExecute()` sobre `/data/user/0/com.termux/...`; essa área é privada ao UID do Termux.
- Executar `PRAGMA quick_check` no banco de teste ou leitura de integridade equivalente sem migrar nem alterar o banco ativo.
- Confirmar que o APK e o worker têm proveniência correspondente.
- Confirmar que a fila não contém leases ativos ou tarefas de teste abandonadas.

### T1 — Inicialização assistida
- Abrir o app Bridge e solicitar o agendamento.
- Observar o primeiro WorkInfo e a notificação/saída do Termux.
- Verificar se o serviço é iniciado via `startForegroundService()` em API 26+.
- Confirmar que o emissor do broadcast de wake é identificado como `com.termux` no Android 14+.
- Validar um único recibo completo, com task_id, estado e wake_schedule coerentes.

### T2 — Outro app em primeiro plano, tela ligada
- Abrir outro aplicativo após ativar o agendamento.
- Aguardar o próximo trabalho elegível; não exigir execução exatamente aos 15 minutos.
- Confirmar que o Companion não exige que sua Activity esteja visível.
- Confirmar orçamento `background_companion`, checkpoint e uma tarefa por invocação.
- Registrar atraso real, temperatura, RAM disponível, bateria, estado do WorkManager e recibo.

### T3 — Tela apagada
- Deixar o aparelho com tela apagada durante janela suficiente para o Android agendar o trabalho.
- Confirmar se o contexto é `background_idle` e se o Governor aplica orçamento correspondente.
- Registrar Doze, App Standby, atraso, temperatura, bateria, RAM e resultado.
- Ausência de execução dentro de uma janela curta não prova falha; comparar com o estado de jobs pendentes e motivos de adiamento.

### T4 — Falha, retry e lease
- Usar uma falha controlada e reversível em ambiente de teste, nunca corromper o banco ativo.
- Confirmar que o Android classifica falha transitória como retry.
- Confirmar que o comando Termux termina em até 30 s (SIGTERM e grace period SIGKILL de 2 s).
- Confirmar que o retry aguarda pelo menos 120 s, acima do lease Python de 90 s.
- Confirmar que o worker antigo não pode completar/release o lease de uma nova invocação.
- Confirmar reconciliação por recibo/checkpoint após encerramento abrupto.

### T5 — Morte de processo e reinicialização
- Encerrar o processo Termux de maneira controlada e observar retomada pelo Android.
- Reiniciar o aparelho e verificar se o agendamento persistente do WorkManager é restaurado.
- Não interpretar force-stop como morte normal: após force-stop, o Android pode impedir jobs até que o usuário abra o aplicativo novamente.
- Verificar que a fila e os recibos persistem e que nenhuma tarefa concluída é executada novamente.

## 5. Evidências obrigatórias

Para cada invocação registrar:
- data/hora local e atraso em relação ao agendamento;
- estado WorkManager e número de tentativas;
- resultado RUN_COMMAND: err, errmsg, exitCode, comprimentos originais de stdout/stderr;
- status do worker, task_id, execution_performed, completion_receipt_valid;
- status e atraso do próximo wake;
- queue summary, lease e checkpoint;
- estado de tela, foreground, bateria, RAM, armazenamento e thermal;
- hash do APK, hash do worker e commit de origem.

## 6. Critérios de aprovação

O Companion só será considerado **validado no aparelho** quando:
- T1, T2 e T3 tiverem evidências completas e repetíveis;
- o recibo for validado e reconciliado sem falsos positivos;
- falha e retry respeitarem o lease e não duplicarem efeitos;
- encerramento de processo e reinicialização recuperarem a fila sem corrupção;
- nenhum fluxo exigir permissões fora do escopo declarado;
- o comportamento e as limitações OEM estiverem documentados.

Um teste isolado bem-sucedido não comprova residência contínua. O resultado deve ser classificado como: implementado, compilado, testado em CI, testado no dispositivo ou validado em uso repetido.

## 7. Recuperação

- Não apagar o banco ativo nem limpar dados do Termux.
- Antes de qualquer teste que escreva no banco, criar backup consistente e confirmar restauração.
- Usar tarefa de teste identificável e remover somente após confirmar seu estado terminal.
- Em falha de build, manter o APK anterior e registrar hash.
- Em falha de dispositivo, parar novas execuções pelo Bridge; não reinstalar, limpar dados ou alterar políticas do Android sem diagnóstico.

### Trust do pacote Termux

- Registrar a origem de instalação (F-Droid/GitHub/Google Play), versão e SHA-256 do certificado de assinatura instalado.
- O bridge atual não fixa nem valida criptograficamente o signer do pacote Termux. As distribuições oficiais usam chaves diferentes; a chave de teste de builds GitHub não deve ser aceita como âncora de confiança.
- Até existir política source-aware de signer ou confirmação explícita do fingerprint, não habilitar execução unattended/background em produção. O teste físico atual deve permanecer supervisionado e read-only/one-shot.


## Trust-boundary validation update — 26/11/2026

### Termux signer pinning

Before enabling the cycle on the Realme:
1. Confirm the Activity reports the installed Termux release channel as `F-Droid` (the expected channel for the documented installation).
2. Confirm an unrecognized/malformed signer produces `termux_signer_untrusted` and no RUN_COMMAND dispatch or WorkManager scheduling.
3. Confirm the worker repeats signer verification immediately before dispatch; UI preflight alone is not the security boundary.
4. Do not change Termux source, allow-external-apps, permissions or Android settings as part of this test.

### Wake sender authentication

- On the Realme Android 16/API 36 device, verify `getSentFromUid()` equals the installed `com.termux` UID and that the ordered broadcast returns result code 1 only after WorkManager accepts the one-shot request.
- Verify wrong UID and unavailable UID are rejected.
- Below API 34, background scheduling must remain disabled: Activity stops existing work and the worker refuses execution because sender UID cannot be authenticated. No periodic fallback is claimed on those releases.

### Cancellation and bounded process

- Interrupt/cancel a worker while awaiting Termux's result; the bridge must restore the Java thread interrupt flag, remove the pending result waiter and cancel the one-shot PendingIntent.
- Verify Termux's command remains bounded by 30 seconds plus 2-second kill grace; do not interpret WorkManager cancellation as synchronous process termination.

No device validation has been performed by this source change. Keep background scheduling disabled until CI passes and the explicit Realme checks above are completed.


## Native LiteRT-LM provider validation — pending

1. Import the existing `Qwen3-1.7B_dynamic_wi4b32_afp32.litertlm` file through the app's SAF picker. Do not copy or delete the Termux source file manually during this test.
2. Compare the provider's imported SHA-256 with the local Termux artifact SHA-256. The provider must independently recompute and verify the app-private copy before loading.
3. Confirm the provider reports `backend_policy=cpu_only_until_device_validation`; a request for GPU must be rejected before Engine construction.
4. Keep the device screen interactive and run the authenticated Termux client in the foreground for the first load and short inference; the Mahoraga companion Activity may be background after the model has been imported. Record load duration, first-token latency, tokens/second, peak available-RAM drop, thermal status and battery impact.
5. Exercise one request through submit → poll → result → acknowledge. Then exercise cancellation during streaming and verify the request reaches a terminal cancelled state without leaving an active Conversation.
6. Test background inference only after explicitly enabling the WorkManager cycle; use `task_class=background` and `allow_background=true`. With the schedule enabled, screen-on execution may use the reduced budget; screen-off execution requires charging. Screen-off/non-charging requests must be rejected.
7. Verify a non-Termux UID and a Termux package signed by an unknown certificate cannot call the provider. Do not install a spoofed package on the primary device; use a controlled test fixture or emulator for negative identity tests.
8. Do not enable GPU until a separate device experiment proves OpenCL availability, successful load, stable inference, acceptable thermal behavior and memory headroom.

No native-provider device test has been performed by this branch. CPU is the only authorized backend; the Python provider fallback remains disabled pending end-to-end validation.
