# Alpha2 — concorrência e ciclo de vida IPC

## Escopo

Branch: `feat/android-shizuku-user-service-alpha2-20261125`  
PR: #278  
Base consultada: `97cb478f2da940b2471dae7a7a109241606cfbff`

Nenhuma permissão, operação AIDL ou capacidade foi adicionada. O contrato permanece limitado a versão do protocolo, leitura de UID/PID/tempo monotônico, cancelamento por UUID e destroy reservado.

## Alterações implementadas nesta revisão

### Gerações e callbacks antigos
- O `ServiceLifecycle` é process-scoped/static; gerações permanecem monotônicas entre recriações da Activity.
- Cada bind cria token de sessão e `ServiceConnection` exclusivos.
- Cada geração recebe `UserServiceArgs` próprios, com tag e process suffix derivados da geração; bind/unbind usam exatamente os argumentos do contexto correspondente.
- Isso é obrigatório porque `Shizuku.unbindUserService(args, conn, true)` ignora `conn` e remove o serviço identificado por package+tag; tags compartilhadas permitiriam cleanup obsoleto matar o serviço substituto.
- Callback de conexão, desconexão, Binder death, handshake e operação carrega a referência exata da sessão.
- Sessões invalidadas não podem avançar estado nem aceitar callbacks.
- Cleanup tardio remove somente a conexão obsoleta, sem reutilizar a conexão da sessão atual.

### Serialização IPC
- Bind, execução da operação, cancelamento remoto e unbind usam a mesma fila FIFO de thread única.
- O unbind é enfileirado após qualquer bind/operação já enfileirado.
- O handshake é separado para que uma chamada de protocolo bloqueada não impeça a fila de cleanup.
- O executor do handshake é limitado a duas threads daemon.

### Atomicidade
- Cada operação tem estado terminal atômico: PENDING → COMPLETED, CANCELLED ou FAILED.
- Somente uma transição pode vencer.
- Cancelamento local invalida imediatamente callbacks tardios; cancelamento remoto segue pela fila IPC.
- O servidor usa `OperationRegistry` para coordenar admissão, duplicidade, conclusão, cancelamento e destroy sob um protocolo atômico.
- `destroyAndCancelPending()` impede novas admissões, cancela as entradas pendentes e impede callback de conclusão quando destroy vence a corrida.

### Timeout de handshake
- A verificação do protocolo começa após a conexão Binder e tem timeout independente de 5 segundos.
- Timeout e resposta competem por gate one-shot.
- A fila de bind/cancel/unbind não depende do executor do handshake.

### Binder death e Activity
- DeathRecipient é específico da sessão.
- Binder death invalida sessão e operação antes de solicitar cleanup.
- `onStop` e `onDestroy` invalidam a sessão. A fila FIFO é process-scoped e permanece viva entre recriações da Activity para drenar bind/cancel/unbind; não é encerrada no ciclo de vida de uma Activity.
- Cada unbind usa os argumentos/tag e ServiceConnection da geração correspondente.

## Testes determinísticos adicionados

Arquivos: `ServiceLifecycleTest.java` e `OperationRegistryTest.java`.

1. Geração antiga não avança nem altera a sessão substituta.
2. Apenas uma sessão pode possuir o ciclo de vida.
3. Protocolo não fica READY antes de CONNECTED → VERIFYING.
4. Cancelamento suprime conclusão tardia.
5. Corrida conclusão × cancelamento: exatamente um vencedor, repetida 250 vezes com barreira.
6. Corrida resultado × timeout do handshake: exatamente um vencedor, repetida 100 vezes.
7. Binder death invalida sessão e torna callback pendente obsoleto.
8. Fila FIFO preserva bind → cancel → unbind → próximo bind sem sobreposição.
9. Registry rejeita UUID duplicado sem substituir a operação original.
10. Destroy cancela operações pendentes e rejeita novas admissões.
11. Conclusão que vence antes de destroy mantém seu estado terminal.
12. Corrida conclusão × destroy: exatamente um vencedor, repetida 200 vezes.
13. Corrida cancelamento × destroy: exatamente um vencedor.
14. Falha de operação remove a entrada pendente e bloqueia conclusão posterior.
15. Tag e process suffix são únicos por geração e rejeitam gerações não positivas.
16. Geração compartilhada permanece monotônica entre donos de Activity no mesmo processo.
17. Recriação da Activity recebe tag e process suffix distintos da sessão anterior.

O teste de contrato verifica também que `HANDSHAKE_TIMEOUT_MS` é positivo e limitado. A suíte Alpha2 contém 31 casos JVM no total após os três testes de identidade por geração (9 lifecycle + 6 registry + 8 contract + 8 ShizukuProbeState), sujeito à confirmação por JUnit XML. Os contratos Python foram atualizados para refletir a nova arquitetura e agora contêm 8 casos focados (além dos 5 casos da política de manifesto).

## Limites

Os testes JVM exercitam gates e fila determinística, não simulam Binder Android real nem processo Shizuku. Build AIDL/Gradle, política de manifesto binário e execução no dispositivo são gates separados. Nenhum APK será instalado nesta etapa.

## Critério de aprovação

- Python de contratos/política: aprovado no commit exato.
- JUnit: todos os testes, zero falhas/erros/skips, contagem confirmada por XML.
- `:app:assembleDebug`: sucesso.
- Política do manifesto binário: aprovada.
- Revisão independente do diff e logs.
- Runtime Realme: não é repetido nesta etapa; o APK instalado não será substituído.

## Checkpoint de execução desta revisão

- Commit de endurecimento inicial: `c7d9a003bcc92d8ed12f858ec1ede8cb082d953e`.
- Commit de coordenação de destroy/Activity recreation: `a431c77e1b750b2bb1c9cc72f235a9bc0c959317`.
- Um harness Java isolado foi compilado com `javac` e executado no ambiente local. Resultado: PASS para geração obsoleta, corrida cancelamento/conclusão (250 repetições), gate handshake/timeout (100 repetições), registry conclusão/destroy (200 repetições), admissão após destroy e fila FIFO sem sobreposição.
- Limite do harness: ele valida os algoritmos puros reproduzidos no harness; não é execução do Gradle/JUnit do projeto nem substitui a compilação Android.
- GitHub Actions run `45708138074`, no commit `a431c77e1b750b2bb1c9cc72f235a9bc0c959317`, e run `45709022409`, no commit final `4fdbe397bb15a866e683dd4c47c4602aeceb92e4`: jobs terminaram em failure antes dos steps; consulta de steps retornou listas vazias. Nenhum pytest, Gradle, JUnit ou build Android foi executado nesses runs.
- Portanto, os testes determinísticos foram escritos, mas a suíte oficial do projeto ainda NÃO está validada. Build, AIDL, JUnit XML, manifesto binário e APK desta revisão permanecem pendentes.

- Commit final de alinhamento dos contratos e sincronização de conclusão/destroy: `a4652708bf883079247849f7e7980adb9b389613`.
- GitHub Actions run `45708620312` corresponde exatamente a esse commit; job `139536935216` terminou em failure com `steps=[]` e sem logs. A execução não iniciou pytest, Gradle, JUnit ou build Android.
- O HEAD da branch foi confirmado como `a4652708bf883079247849f7e7980adb9b389613`; PR #278 continua aberta e sem merge. A main observada permaneceu em `497e377ded6186d79a39b93c1eb687e6f413d7c1`.

- Commit de correção do cleanup em falha: `4fdbe397bb15a866e683dd4c47c4602aeceb92e4`; harness Java isolado foi reexecutado após incluir o estado FAILED e passou. Isso não altera o status de JUnit/Gradle pendente.


## Revisão adicional — identidade por geração e semântica do unbind — 26/11/2026

A revisão do código-fonte oficial Shizuku identificou que `unbindUserService(args, conn, true)` chama `removeUserService(null, args.forRemove(true))`; o argumento `conn` é ignorado no caminho `remove=true`. Portanto, uma limpeza atrasada de uma conexão antiga, usando a mesma tag, poderia remover o serviço de uma sessão substituta.

Correção implementada nesta branch:
- `ServiceLifecycle` tornou-se process-scoped/static para manter gerações monotônicas entre recriações da Activity.
- Cada `ConnectionContext` cria e guarda seu próprio `UserServiceArgs`.
- `tag` e `processNameSuffix` incorporam a geração monotônica; bind, stale cleanup e stop usam os argumentos daquele contexto, isolando a remoção por identidade do serviço.
- Dois testes verificam unicidade por geração e rejeição de geração zero/negativa.

A correção precisa passar novamente por Python contract tests, AIDL/Gradle, JUnit e política binária do manifesto. Nenhuma validação física adicional foi executada.
