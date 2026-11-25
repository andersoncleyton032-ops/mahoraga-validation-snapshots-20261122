# Android Shizuku UserService e agendamento API 36 — pesquisa 2026-11-25

## Objetivo

Definir a próxima etapa Android do Mahoraga sem ampliar prematuramente o APK read-only do Android Capability Lab v0.1. A pesquisa separa três superfícies: Binder/identidade Shizuku, processo UserService e agendamento de trabalho no Android 16 (API 36).

## 1. Shizuku: modelo de identidade e ciclo de vida

Fontes primárias:
- Shizuku-API, guia oficial: https://github.com/RikkaApps/Shizuku-API#readme
- Shizuku: https://github.com/RikkaApps/Shizuku

Achados:
- Shizuku é um aplicativo Android separado. Em aparelho não root, o serviço precisa ser iniciado novamente por ADB após reinicialização; no Android 11+, Wireless debugging permite iniciar pelo próprio aparelho.
- A API oficial é distribuída como `dev.rikka.shizuku:api`; o suporte ao provider usa `dev.rikka.shizuku:provider`. A versão deve ser resolvida do Maven Central no momento da implementação, sem copiar uma versão antiga do README.
- O app normal recebe o Binder via ShizukuProvider. A API oferece listeners `addBinderReceivedListener` e `addBinderDeadListener`; não se deve chamar métodos de serviço quando o Binder está morto, pois a API pode lançar `IllegalStateException`.
- O fluxo de permissão usa listener de resultado, `checkSelfPermission()`, `shouldShowRequestPermissionRationale()` e `requestPermission(requestCode)`. O listener deve ser removido no ciclo de vida apropriado. A permissão não deve ser solicitada automaticamente na inicialização do Mahoraga.
- `Shizuku.getUid()` diferencia root (0) de shell/ADB (2000). O alvo inicial do Mahoraga continua sendo shell/ADB, sem root.
- Remote Binder Wrapper é adequado para chamadas Binder pontuais e simples. Para executar código Java/JNI próprio com identidade shell, a API recomenda UserService; `newProcess` está em processo de remoção e não deve ser a base de uma nova implementação.

## 2. UserService: implicações arquiteturais

A documentação oficial descreve UserService como um processo separado executado com UID root ou shell. Esse processo **não é um processo Android de aplicação normal**: obter um `Context` não torna disponíveis APIs como `Context.registerReceiver` ou `Context.getContentResolver`.

Regras de implementação:
1. A aplicação principal continua responsável por UI, permissões, armazenamento normal, lifecycle Android e comunicação com o serviço.
2. UserService recebe apenas operações tipadas por AIDL/Binder; não expor uma interface de shell arbitrário.
3. Cada operação deve declarar capacidade requerida, entradas validadas, orçamento de recursos, timeout, cancelamento e evidência de resultado.
4. Usar `UserServiceArgs.tag` estável e `version` explícita. O tag evita depender de nome de classe que pode mudar com R8/ProGuard.
5. `unbindUserService` não encerra automaticamente o processo. Implementar o método `destroy` previsto pela API para liberar recursos e terminar o serviço.
6. Tratar Binder death, desconexão, timeout de bind, negação de permissão e serviço indisponível como estados distintos; nenhum deles pode ser convertido em sucesso implícito.
7. Primeira etapa usa apenas UID shell 2000. Não adicionar root, Hidden API bypass, alteração de SELinux ou escrita em configurações do sistema.

## 3. Android 16 / API 36: quotas e UIDT

Fontes primárias:
- Android Developers — mudanças em foreground services: https://developer.android.com/develop/background-work/services/fgs/changes
- Android Developers — User-initiated data transfer jobs: https://developer.android.com/develop/background-work/background-tasks/uidt
- Android Developers — opções para transferência de dados: https://developer.android.com/develop/background-work/background-tasks/data-transfer-options

Achados:
- No Android 16, jobs iniciados enquanto um Foreground Service está ativo continuam sujeitos às quotas de runtime do tipo de job. WorkManager, JobScheduler e DownloadManager não ganham uma isenção geral por estarem associados a FGS.
- UIDT (User-Initiated Data Transfer) existe desde Android 14/API 34, mas é específico para transferência de dados iniciada pelo usuário, não um scheduler genérico para CPU/GPU ou inferência local.
- UIDT exige `RUN_USER_INITIATED_JOBS`, um `JobService` declarado com `BIND_JOB_SERVICE`, agendamento enquanto o app está visível ou em condição permitida, notificação durante execução e estimativa de bytes quando conhecida.
- A documentação informa que não existe atualmente uma biblioteca Jetpack que abstraia UIDT; é necessário usar JobScheduler diretamente e fazer gate por API.
- Para investigar paradas, registrar `JobParameters.getStopReason()`; Android 16 também expõe histórico de razões pendentes via JobScheduler.
- Para transferências curtas/interrompíveis, manter WorkManager. FGS é para trabalho curto/crítico que precisa começar imediatamente e permanecer visível; não deve ser usado para contornar quotas.

## 4. Decisões para Mahoraga

### Android Capability Lab v0.1
Permanece read-only. Não adicionar ShizukuProvider, permissões, Binder, UserService, serviços ou jobs a esse APK. Ele é uma sonda de inventário e deve continuar simples, auditável e sem efeitos colaterais.

### Próxima ferramenta auxiliar: Android Shizuku Capability Probe v0.2
Construir como APK/módulo separado, com:
- tela explícita de conexão/desconexão;
- estado do Binder (ausente, recebido, morto);
- UID efetivo (esperado 2000 em modo ADB);
- estado de permissão Shizuku (não solicitada, concedida, negada, rationale);
- ação de solicitação de permissão somente após toque do usuário;
- UserService de teste que retorna apenas identidade/versão e responde a ping;
- encerramento explícito e teste de Binder death;
- relatório local, sem upload e sem executar comandos arbitrários.

### Scheduler Companion / WorkManager
- Usar WorkManager para tarefas persistentes, adiáveis e interrompíveis.
- Usar JobScheduler diretamente para capacidades Android 16 específicas, como UIDT somente quando a operação for transferência de dados realmente iniciada pelo usuário.
- Não usar UIDT para inferência, treinamento, renderização ou manutenção local.
- Manter FGS somente para sessões visíveis de curta duração ou trabalho crítico compatível com tipo e quota.
- Medir `getStopReason`, temperatura, bateria, memória livre, armazenamento e progresso real; ajustar os orçamentos dinamicamente sem limites universais fixos.

## 5. Plano de testes da etapa v0.2

- Binder indisponível na inicialização: nenhum IPC privilegiado.
- Binder recebido: estado muda para disponível; ping não executa comandos.
- Binder morto durante chamada: operação cancela/retorna estado interrompido; não repete automaticamente.
- Permissão não concedida: nenhuma chamada UserService.
- Permissão solicitada: apenas após ação explícita; resultado tratado por requestCode.
- UID diferente de shell 2000: marcar ambiente distinto; não elevar nem tentar root.
- Bind timeout/desconexão: liberar callback e estado pendente.
- Unbind: executar destroy e confirmar encerramento por resposta/estado.
- Payload AIDL inválido/oversized: rejeitar antes de atravessar Binder.
- Testes de manifesto confirmam permissões e provider estritamente necessários, sem INTERNET e sem componentes de fundo não aprovados.

## Estado

Pesquisa concluída; nenhum código UserService foi adicionado e nenhum APK foi instalado. O v0.2 só deve começar depois de a revisão v0.1 ter execução de build/testes comprovada e o usuário autorizar a instalação/teste do módulo Shizuku no ambiente Realme.


## Atualização de versões e recorte de implementação — 25/11/2026

Fontes oficiais/primárias consultadas:
- Shizuku API README: https://github.com/RikkaApps/Shizuku-API
- Shizuku releases: https://github.com/RikkaApps/Shizuku/releases
- Maven Central API: https://central.sonatype.com/artifact/dev.rikka.shizuku/api
- Maven Central provider: https://central.sonatype.com/artifact/dev.rikka.shizuku/provider

Versões observadas:
- Aplicativo Shizuku: release mais recente encontrada `v13.6.0`, com suporte anunciado a Android 16 QPR1 e auto-start sem root em Android 13+ sob Wi-Fi confiável.
- Artefatos de desenvolvimento `dev.rikka.shizuku:api` e `dev.rikka.shizuku:provider`: versão mais recente publicada no Maven Central `13.1.5`, de 21/09/2023. O README da API também termina seu changelog em 13.1.5.
- Portanto, há um descompasso entre a versão atual do app Shizuku e a API/provider publicada. O alpha deve fixar API/provider 13.1.5, compilar contra Android 16 e manter teste em dispositivo como gate obrigatório; não inferir compatibilidade da versão do app.

### Recorte em etapas

**v0.2-alpha1 — Binder/permission/identity probe**
- APK separado do Capability Lab v0.1.
- Observa Binder received/dead e estado de permissão.
- Solicita permissão somente por toque explícito.
- Consulta UID apenas após permissão concedida e aceita somente UID 2000 (ADB/shell); UID 0/root é incompatibilidade e nunca é solicitado.
- Não executa comandos, não inicia UserService, não altera sistema, não usa rede nem grava dados fora do armazenamento normal.
- O provider Shizuku é o único componente extra esperado; protegido por `android.permission.INTERACT_ACROSS_USERS_FULL`, com autoridade `${applicationId}.shizuku`.
- O AAR oficial `provider:13.1.5` adiciona `uses-permission moe.shizuku.manager.permission.API_V23`. O app Shizuku declara essa permissão customizada como `dangerous`; ela é a permissão de runtime específica da API Shizuku e só deve ser solicitada pelo fluxo explícito do usuário. A política do APK permite exatamente essa permissão e rejeita qualquer outra.
- Usar `addBinderReceivedListenerSticky`, `addBinderDeadListener` e `addRequestPermissionResultListener` com Handler principal; remover listeners no ciclo de vida. Só chamar APIs Shizuku com Binder vivo.

**v0.2-alpha2 — typed UserService**
- Só depois do alpha1 compilar e o probe de Binder/UID ser validado no Realme.
- AIDL com operações estreitas e tipadas; sem comando shell arbitrário.
- `UserServiceArgs.tag` e `version` estáveis; `destroy` explícito; timeout, cancelamento e Binder death tratados.
- Não usar `newProcess`; a documentação da API o marca deprecated e recomenda UserService para execução própria.
- O processo UserService tem UID shell 2000, mas não é processo Android normal; evitar APIs de Context como `registerReceiver` e `getContentResolver`.

O alpha1 pode ser desenvolvido e construído agora, mas não será instalado automaticamente. A instalação/runtime no Realme fica como etapa manual posterior, após revisão do APK e dos relatórios.
