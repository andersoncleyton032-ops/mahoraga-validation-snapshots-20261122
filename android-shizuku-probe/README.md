# Mahoraga Shizuku Probe v0.2-alpha2

APK separado do Android Capability Lab v0.1 e evolução do Probe alpha1.

## Escopo alpha2

- Mantém observação de Binder, permissão e identidade do Shizuku.
- Inicia UserService somente após ação explícita e somente se o Binder estiver vivo, a permissão concedida e o UID for 2000.
- Usa AIDL tipado: versão do protocolo, leitura de UID/PID/tempo monotônico e cancelamento por UUID.
- Cada geração de conexão usa tag e process suffix exclusivos; cleanup tardio não pode remover o UserService da geração substituta.
- Cada bind usa uma geração monotônica e um `ServiceConnection` exclusivo; callbacks obsoletos não alteram a sessão atual.
- Bind, execução, cancelamento remoto e unbind são serializados em uma fila FIFO process-scoped compartilhada entre recriações da Activity.
- Handshake usa executor process-scoped limitado a duas threads daemon, com timeout independente de 5 segundos.
- Cancelamento, conclusão e destruição competem por transições terminais atômicas no cliente e no servidor; Binder death e Activity stop invalidam a geração antes do cleanup.
- UserService é não-daemon, usa tag/process suffix exclusivos por geração e versão explícita; implementa destroy para cancelar tarefas, encerrar executor e terminar o processo. Os mesmos UserServiceArgs são reutilizados apenas dentro daquela geração.
- O teste remoto só retorna UID 2000; qualquer identidade diferente é rejeitada.

## Não faz

- Não executa shell, ProcessBuilder, Runtime.exec, Shizuku.newProcess ou transactRemote.
- Não modifica arquivos, configurações ou estado do sistema.
- Não usa rede, câmera, microfone, sensores ou armazenamento persistente.
- Não adiciona services, receivers ou componentes de fundo ao manifesto.
- A única permissão declarada é a runtime permission customizada Shizuku API_V23, solicitada apenas pelo fluxo explícito.

## Dependências

- dev.rikka.shizuku:api:13.1.5
- dev.rikka.shizuku:provider:13.1.5

A versão do aplicativo Shizuku instalado no dispositivo precisa ser registrada antes do teste real. A compatibilidade do UserService no Android 16 não é inferida do sucesso do Binder alpha1.

## Build

    gradle -p android-shizuku-probe :app:testDebugUnitTest :app:assembleDebug

Build e testes automatizados não comprovam execução no Realme. O protocolo físico está em docs/testing/SHIZUKU_USER_SERVICE_ALPHA2_DEVICE_TEST.md.
## Endurecimento de concorrência Alpha2

A revisão de ciclo de vida e os testes determinísticos estão descritos em `docs/testing/SHIZUKU_USER_SERVICE_ALPHA2_CONCURRENCY_TESTS.md`. O build e a execução desta revisão só serão considerados aprovados após evidência de CI vinculada ao commit exato.
