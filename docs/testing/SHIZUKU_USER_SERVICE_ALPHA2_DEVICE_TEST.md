# Teste de dispositivo — Mahoraga Shizuku UserService v0.2-alpha2

## Objetivo

Validar separadamente a inicialização de um processo UserService, uma operação AIDL tipada de leitura de identidade e seu encerramento explícito no Realme 14 5G / Android 16.

Este APK é um protótipo isolado. Não faz parte do Android Capability Lab read-only.

## Pré-condições obrigatórias

- Alpha1 observado no aparelho com Binder AVAILABLE, permissão GRANTED e UID 2000.
- Registrar a versão exata do aplicativo Shizuku instalada em Configurações do Shizuku / Sobre antes de instalar o alpha2.
- Shizuku iniciado em modo Wireless Debugging/ADB, não Sui/root.
- Manter o aparelho desbloqueado e o Probe em primeiro plano durante o teste.
- Não repetir ciclos de instalação/force-stop/reinício. Há relatos públicos de processos UserService órfãos em alguns cenários de encerramento do cliente ou reinício do servidor.
- Se o bind falhar, registrar a versão do Shizuku e a tela; não fazer downgrade/upgrade automaticamente.

## Operações permitidas

1. Consultar Binder, permissão e UID Shizuku.
2. Iniciar UserService somente após toque explícito e somente com UID Shizuku 2000.
3. Consultar versão fixa do protocolo.
4. Executar runIdentityProbe: ler somente Process.myUid(), Process.myPid() e SystemClock.elapsedRealtime() no processo remoto.
5. Cancelar uma requisição identificada por UUID.
6. Encerrar com unbindUserService(remove=true), acionando o método AIDL destroy().

Não há shell arbitrário, ProcessBuilder, Runtime.exec, newProcess, transactRemote, rede, escrita em configurações, armazenamento persistente, captura ou sensores.

## Procedimento

1. Abrir o Probe Alpha2 e confirmar Binder AVAILABLE, Permissão GRANTED e UID Shizuku 2000.
2. Tocar **Iniciar UserService de teste**.
3. Aguardar estado CONNECTED; PROTOCOL 1.
4. Tocar **Executar prova de identidade**.
5. Resultado esperado: IDENTITY_CONFIRMED, UID remoto 2000, PID positivo e tempo monotônico.
6. Tocar **Encerrar UserService**. Resultado visual esperado: STOPPED_BY_USER.
7. Não reiniciar o servidor Shizuku nem forçar parada do Probe como parte do teste básico.

## Testes de falha controlados

- Binder indisponível/permissão negada/UID diferente de 2000: o botão de bind deve permanecer bloqueado.
- Bind sem callback em 10 segundos: BIND_TIMEOUT, com tentativa de remoção explícita do serviço.
- Operação sem callback em 5 segundos: OPERATION_TIMEOUT e pedido de cancelamento pelo UUID.
- Binder do UserService morre: USER_SERVICE_BINDER_DIED; não declarar operação concluída.
- UID remoto diferente de 2000: IDENTITY_REJECTED; não executar outra operação.

O teste de timeout real não deve ser induzido por comandos externos ou bloqueios artificiais no sistema. Pode ser validado em teste unitário/integração com callback controlado.

## Critérios de aprovação

- Binder/permission/UID da Alpha1 continuam válidos.
- UserService conecta e retorna protocolo 1.
- Operação retorna UID remoto 2000 e PID positivo.
- Cancelamento/timeout não produz sucesso tardio.
- Unbind aciona destroy e encerra o processo.
- Nenhum comando arbitrário, alteração de sistema ou transmissão de rede ocorre.

A confirmação final de encerramento do processo deve ser feita por evidência de runtime apropriada, não apenas pelo texto STOPPED_BY_USER da UI.

## Limitações conhecidas

A documentação oficial Shizuku afirma que unbindUserService não mata automaticamente o processo; o serviço precisa implementar destroy(). A implementação usa modo não-daemon, tag estável, versão explícita e destroy() com limpeza antes de System.exit(0).

Há relatos públicos de:
- falha de inicialização de UserService em alguns aparelhos Android 16/Shizuku 13.6.0 (#2561);
- processos órfãos após encerramento do cliente ou reinício do Shizuku (#2603).

Esses relatos não provam falha no Realme, mas tornam a versão instalada e o encerramento verificável gates obrigatórios.

## Fontes

- Guia/API oficial: https://github.com/RikkaApps/Shizuku-API
- Demonstração oficial: https://github.com/RikkaApps/Shizuku-API/tree/master/demo
- Issue #2561: https://github.com/RikkaApps/Shizuku/issues/2561
- Issue #2603: https://github.com/RikkaApps/Shizuku/issues/2603

## Evidência automatizada pré-dispositivo

- Snapshot público PR #18, run completo #45620798957: 141 testes Python passaram em 3.12 e 141 em 3.14; os dois módulos Android construíram e as políticas de manifesto passaram.
- Run Alpha2 dedicado #45620799012: 14 testes JVM passaram, sem falhas/erros/skips; AIDL compilado; APK montado; manifesto binário aprovado.
- Artifact ID 15024194114.
- APK SHA-256 3121a65003a44ec2783b548cb39dff57b4e4ae69949b89d2d8362bf1f1044fd8.

Esses resultados comprovam build e contratos automatizados, não runtime no Realme. Antes de instalar, registrar a versão exata do Shizuku que já está no aparelho. Não fazer downgrade/upgrade automático.

## Notas de concorrência após endurecimento Alpha2

- Cada bind usa `ServiceConnection` exclusivo por geração; callbacks de gerações encerradas devem ser ignorados e cleanup restrito à conexão antiga.
- Bind, execução, cancelamento remoto e unbind são serializados em fila process-scoped compartilhada entre Activity antiga e recriada. Ordem esperada: `run (se já enfileirado) → cancel → unbind → novo bind`.
- O handshake possui timeout independente de 5 segundos; seu timeout agenda cleanup sem depender do executor do Binder call. O pool de handshake é process-scoped e limitado a duas threads daemon.
- Conclusão e cancelamento usam gate terminal atômico; callback remoto atrasado não altera estado após cancelamento local.
- Binder death e encerramento da Activity invalidam a geração antes de cancelar operação e solicitar unbind.
- Testes determinísticos JVM: `docs/testing/SHIZUKU_USER_SERVICE_ALPHA2_CONCURRENCY_TESTS.md`. Eles não substituem validação de runtime Binder.
