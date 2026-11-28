# Teste de dispositivo — Mahoraga Shizuku Probe v0.2-alpha1

## Objetivo

Confirmar no Realme 14 5G / Android 16 que o APK consegue:
1. detectar o app Shizuku;
2. observar o Binder ativo/inativo;
3. solicitar a permissão Shizuku somente após toque explícito;
4. ler a identidade efetiva e aceitar exclusivamente UID 2000 (ADB/shell).

O teste não executa comandos, não inicia UserService e não modifica o sistema.

## Pré-condições

- Shizuku instalado e iniciado pelo modo ADB/Wireless Debugging, sem root.
- Não usar Sui/root nesta validação. O APK desabilita a inicialização automática do Sui.
- APK separado: pacote `com.mahoraga.shizukuprobe`, versão `0.2.0-alpha1`.
- SHA-256 esperado: `1826eb3c47fbff64e3caf04f1cc0370af59795a0506583aedf5a015c06f45a40`.

## Procedimento

1. Instalar o APK de teste e abrir **Mahoraga Shizuku Probe**.
2. Conferir o campo **Shizuku instalado** e o estado do Binder.
3. Se o Binder estiver `AVAILABLE`, tocar em **Solicitar permissão Shizuku**.
4. Aprovar a permissão customizada Shizuku API_V23 no fluxo do Shizuku.
5. Tocar em **Atualizar estado**.

## Resultado esperado

```text
Shizuku instalado: true
Binder: AVAILABLE
Permissão: GRANTED
UID efetivo: 2000
Estado: READY_SHELL_UID_2000
```

## Teste negativo opcional

1. Parar o serviço Shizuku no aplicativo Shizuku.
2. Voltar ao Probe e tocar em **Atualizar estado**.
3. Resultado esperado: Binder `UNAVAILABLE`, UID `UNKNOWN`, estado `NOT_READY`.
4. Iniciar Shizuku novamente e atualizar; o Binder deve voltar a `AVAILABLE`.

## Interpretação de falhas

- `Shizuku instalado: false`: pacote não visível/instalado; verificar o app Shizuku.
- Binder `UNAVAILABLE`: Shizuku não está iniciado ou o Binder morreu.
- Permissão `DENIED`/`RATIONALE_REQUIRED`: repetir somente pelo botão explícito e aprovar no Shizuku.
- `REJECTED_ROOT_UID_0`: o serviço está em modo root/Sui; interromper o teste e iniciar Shizuku em modo ADB/shell.
- `REJECTED_UNEXPECTED_UID`: não prosseguir; registrar a tela e investigar a identidade retornada.

## Limites

- A permissão `moe.shizuku.manager.permission.API_V23` é a permissão customizada runtime exigida pelo provider oficial; o usuário a concede pelo fluxo explícito.
- O provider é protegido por `android.permission.INTERACT_ACROSS_USERS_FULL`; o app não declara essa permissão em `uses-permission`.
- Não há INTERNET, comandos shell, UserService, câmera, microfone, sensores ou gravação persistente.
- Este resultado valida somente Binder/permission/UID. Não valida UserService, execução de tarefas nem integração Termux.
- Não instalar alpha2 nem avançar para operações privilegiadas antes de registrar o resultado alpha1.
