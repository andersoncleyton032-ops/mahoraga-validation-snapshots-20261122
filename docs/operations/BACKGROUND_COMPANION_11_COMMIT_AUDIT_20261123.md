# Auditoria dos 11 commits do modo Background Companion

**Workstream:** MAH-COMPANION-MANIFEST-GATE-001  
**Data:** 2026-11-23  
**Intervalo:** `db1463ff166cd30052ed1e286dcfc62cc6bd0433` → `87aed75ca0b24ca358c969fcae2245cf4b6a84f8`  
**Resultado da comparação:** 11 commits à frente, 0 atrás; 8 arquivos modificados.

## Proveniência

Os 11 commits foram criados pelo mesmo autor/committer da conta do repositório, em sequência de aproximadamente 88 segundos. Não foram encontrados autores externos, merges ou commits sem pai esperado. A branch intermediária é ancestral da base da PR #157; não foi encontrada PR própria para essa branch. Nenhum merge foi realizado.

| # | Commit | Mensagem |
|---:|---|---|
| 1 | `06f4b1fe17b398026ebe3a06b0fa7ed6ac931f78` | feat: add bounded background companion mode for foreground chat |
| 2 | `049031ecc78c34f80225c283b28168fb50f5bf92` | feat: support checkpointed background work alongside foreground chat |
| 3 | `763f20421342bfaa0f297a4c2eb429eb9df3f724` | feat: select companion or screen-off background mode from runtime context |
| 4 | `ac8380b315f4cbabc238758b17d5f9c8b62991c9` | test: cover companion foreground and fail-closed runtime selection |
| 5 | `db638fa55c4f0cc5449c2017df7f997bb4028c21` | test: verify deferred workers reschedule without consuming attempts |
| 6 | `952fd6e449bcb42ae3283cd5785cb78bc9748b62` | test: cover foreground-chat companion background admission |
| 7 | `e959ede86b76e7ca920721b5f8fbf0c7b0ace1d6` | test: cover checkpointed companion mode with chat foreground |
| 8 | `bcdd4a0fe14167e3991333c18201a7fd9b3526e7` | test: require checkpoints for companion background work |
| 9 | `347f278edee11521a29a2d92255a997f2c3dc04a` | docs: distinguish chat-foreground companion work from screen-off idle work |
| 10 | `5cacfba73b618a9b44cffefa2289c4ca97da886f` | docs: distinguish chat-foreground companion work from screen-off idle work |
| 11 | `87aed75ca0b24ca358c969fcae2245cf4b6a84f8` | docs: correct background policy for chat-foreground companion mode |

Os commits 9 e 10 têm a mesma mensagem, mas alteram arquivos diferentes; não são duplicatas de conteúdo.

## Mudanças funcionais confirmadas

- `AutonomyGovernor` adiciona `background_companion`, distinto de `background_idle`.
- Companion exige Mahoraga fora do primeiro plano, tela interativa, carregamento confirmado, bateria mínima de 40%, estado térmico normal/light e pelo menos 2 GiB de RAM e armazenamento disponíveis.
- Orçamento Companion: até 8 s e 64 MiB; em estado térmico light, até 5 s e 48 MiB.
- Idle permanece separado: tela apagada, bateria mínima de 30%, até 20 s e 128 MiB; estado térmico light reduz para 12 s e 96 MiB.
- `ResearchOrchestrator` exige que o permit corresponda ao modo exato e que tarefas background sejam internas e checkpointable.
- `BackgroundWorkScheduler` seleciona Companion quando Mahoraga está em segundo plano e a tela permanece interativa; seleciona Idle quando a tela está apagada; contexto desconhecido ou Mahoraga em primeiro plano libera a tarefa sem consumir tentativa.
- A execução permanece one-shot: uma tarefa por invocação, sem loop contínuo. A retomada depende de checkpoints e de novo agendamento da plataforma.

## Cobertura de testes encontrada

Foram adicionados testes para:
- Companion com tela interativa e app Mahoraga em segundo plano;
- redução de orçamento sob estado térmico light;
- bloqueio quando app foreground, tela, carregamento, bateria, temperatura, RAM ou armazenamento não atendem;
- seleção entre Companion e Idle;
- adiamento sem consumir tentativas;
- obrigatoriedade de checkpoint;
- execução checkpointed no Orchestrator.

## Avaliação

A revisão estática não identificou defeito funcional nos 11 commits. A separação Companion/Idle é coerente com os contratos do Governor, Orchestrator e Scheduler. A alteração não transforma o sistema em serviço residente e não garante wakeups exatos do Android.

**Limite da evidência:** os testes de CI posteriores cobrem essa linha de código dentro do snapshot integrado, mas não comprovam comportamento em Android/Realme. O T0 do aparelho mostrou Termux atualizado, porém `allow-external-apps` permanece comentado; nenhuma configuração foi alterada. A validação no dispositivo continua pendente e requer autorização/etapa própria.

## Decisão

- Proveniência: reconciliada.
- Conteúdo: revisado estaticamente.
- Testes: cobertura identificada; evidência de CI do snapshot deve ser citada separadamente.
- Device validation: pendente.
- Merge: nenhum.
