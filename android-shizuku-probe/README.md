# Mahoraga Shizuku Probe v0.2-alpha1

APK separado do Android Capability Lab v0.1.

## Escopo

- Observa o Binder Shizuku (received/dead).
- Mostra se o app Shizuku está instalado.
- Consulta o estado da permissão somente quando o Binder está vivo.
- Solicita a permissão exclusivamente após toque explícito.
- Consulta a identidade efetiva apenas após permissão concedida.
- Aceita somente UID 2000 (shell/ADB). UID 0/root e qualquer outro UID são rejeitados como estado não pronto.

## Não faz

- Não executa comandos shell ou operações privilegiadas.
- Não inicia UserService (planejado para alpha2).
- Não modifica arquivos, configurações ou estado do sistema.
- Não usa rede, câmera, microfone, sensores ou armazenamento persistente.
- Não solicita permissões Android adicionais.

## Dependências

- `dev.rikka.shizuku:api:13.1.5`
- `dev.rikka.shizuku:provider:13.1.5`

O app Shizuku observado mais recente é v13.6.0, enquanto os artefatos API/provider mais recentes no Maven Central continuam em 13.1.5. Essa diferença de versão exige validação no Android 16 real antes de qualquer afirmação de compatibilidade.

## Build

```bash
gradle -p android-shizuku-probe :app:testDebugUnitTest :app:assembleDebug
```

Build automatizado não autoriza instalação automática. O APK deve ser revisado e o teste de runtime no Realme deve ser uma etapa explícita posterior.
