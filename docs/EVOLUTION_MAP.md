# Mahoraga — Mapa Evolutivo de Capacidades

**Atualização:** 2026-11-22  
**Fonte de código:** repositório `andersoncleyton032-ops/mahoraga-core`  
**Linha de integração ativa:** PR #43 → PR #45 → PR #46 → PR #47; nenhuma mesclada.  
**Trilha visual de origem:** PR #44 permanece aberta e não mesclada; seu renderer v0.2 foi portado e endurecido na PR #47, que preserva o tecido #43 e os refinamentos #45/#46.  
**PRs abertas observadas:** 37 no snapshot de 17/11/2026. PRs históricas e branches de backup permanecem preservadas.  
**Backup pré-expansão:** `backup/pre-cognitive-expansion-20261116`

Este mapa registra capacidades e maturidade observável. A presença de código não é prova de funcionamento; CI não equivale a validação no Realme.

## 1. Escala de maturidade

| Estado | Significado |
|---|---|
| PLANNED | Objetivo definido; implementação ainda não existe |
| IN_DEVELOPMENT | Implementação em andamento |
| IMPLEMENTED | Código presente e interfaces definidas |
| TESTED_INDIVIDUALLY | Testes específicos aprovados |
| TESTED_INTEGRATION | Integração testada em CI |
| VALIDATED_REAL | Validado no ambiente real de destino, com evidência |

Uma capacidade pode ter testes aprovados em CI e continuar sem validação real no Android.

## 2. Núcleo cognitivo

| Capacidade | Componentes principais | Maturidade atual | Limites conhecidos |
|---|---|---|---|
| Persistência e memória central | `store.py`, SQLite | TESTED_INTEGRATION | Banco do Realme não validado nesta branch |
| Integridade e autorização | `dharma.py` | TESTED_INTEGRATION | Política ainda exige expansão conforme novas classes de ação |
| Cognição compartilhada | `cognitive_engine.py` | TESTED_INTEGRATION | Integração em branch empilhada; PRs não mescladas |
| Raciocínio explícito | `reasoning_engine.py` | IMPLEMENTED / TESTS ADDED; CURRENT HEAD CI UNVALIDATED | Fatos e regras explícitos; preservação de relatos e premissas ampliada nesta branch; identidades e confiança não autenticadas |
| Recuperação de conhecimento | `knowledge_engine.py` | TESTED_INTEGRATION | BM25 lexical; gaps semânticos e de digitação permanecem |
| Aprendizagem episódica | `adaptive_learning.py` | TESTED_INTEGRATION | Episódios estruturados; sem atualização de pesos neurais |
| Replay e consolidação | `AdaptiveLearning` | TESTED_INTEGRATION | Aprovação humana; evidências e fontes são declarações do chamador |
| Controle executivo | `executive_engine.py` | TESTED_INTEGRATION | Mantém objetivos e foco; não despacha ferramentas |
| Identidade e personalidade | `identity_engine.py`, `identity_profile.json` | TESTED_INTEGRATION | Perfil versionado; não muda automaticamente |
| Autoimagem operacional | `introspection.py`, `IdentityEngine` | TESTED_INTEGRATION | Descreve estado observável e maturidade cadastrada |
| Autoimagem visual | perfil `self_image` | IMPLEMENTED | Especificação conceitual; sem modelo 3D final |
| Memória de trabalho | `ExecutiveEngine` | TESTED_INTEGRATION | Contexto limitado e reconstruído de eventos |
| Continuidade entre sessões | SQLite, eventos, handoff | TESTED_INTEGRATION em CI | Recuperação no dispositivo ainda não revalidada |

## 3. Linguagem e conversação

| Capacidade | Componentes | Maturidade atual | Limites conhecidos |
|---|---|---|---|
| Classificação de intenção | `language_engine.py` | IMPLEMENTED / TESTS ADDED; CURRENT HEAD CI UNVALIDATED | Proveniência individual adicionada; classificador continua restrito às intenções cobertas por fixtures |
| Análise linguística | `linguistic_analysis.py`, `language_lexicon.py` | TESTED_INTEGRATION | Não equivale a compreensão linguística geral |
| Negação, temporalidade e condições | LanguageEngine | TESTED_INTEGRATION | Escopo e ambiguidades complexas ainda exigem evolução |
| Contexto de persona | `IdentityEngine.build_persona_context()` | TESTED_INTEGRATION | Fornece contexto; não gera texto por si só |
| Memória de diálogo estruturada | `ConversationMemoryEngine` | TESTED_INTEGRATION | Resumo aprovado, tópico, entidades, decisões, pendências; sem mensagens brutas |
| Memória conversacional estruturada | `conversation_engine.py` | TESTED_INTEGRATION | Sessões e resumos opt-in; mensagens brutas não são retidas; CI #407 aprovada em Python 3.12/3.14 |
| Geração linguística offline | `model_runtime.py`, `IntegratedCore.generate_local_response()` | TESTED_INTEGRATION | Contexto local inclui persona, executivo, conversa e até 5 fragmentos BM25; endpoint simulado; runtime/modelo real não instalado nem validado no Realme |
| Recuperação semântica por embeddings | notebook Colab e candidatos | PLANNED / pesquisa em andamento | MTEB-BR ainda aguarda execução externa |

Holdouts linguísticos anteriores: v1 26/27, v2 40/40 e v3 48/48. São avaliações de conjuntos delimitados, não comprovação de compreensão geral. A busca lexical tem baseline próprio; não confundir as métricas.

## 4. Introspecção, identidade e personalidade

- Identidade canônica: Mahoraga.
- Filosofia: Adaptável.
- Princípios: integridade/Dharma, adaptação, curiosidade disciplinada, coerência, autonomia progressiva, honestidade epistêmica, eficiência e criatividade.
- Traços comportamentais: curiosidade, método, adaptabilidade, persistência, análise, criatividade, colaboração e franqueza.
- Comunicação: natural, direta, contextual e tecnicamente precisa.
- Operação: offline-first; serviços externos são opcionais.
- Invariantes visuais: silhueta inspirada no Mahoraga, roda do Dharma de oito raios e símbolo de adaptação.
- Domínios criativos: 3D, pintura, imagem, animação, física, simulação e criação de mundos, cada qual com maturidade declarada separadamente.

A personalidade é um perfil comportamental versionado que orienta a seleção de respostas e estratégias. Não é uma alegação de estados subjetivos. O perfil não se autoedita sem revisão versionada.

## 5. Controle executivo, memória conversacional e autonomia

`ConversationMemoryEngine` mantém sessões e resumos aprovados com contexto estruturado, sem reter mensagens brutas. A recuperação é somente leitura e é integrada ao pipeline; a retenção exige aprovação explícita.


Implementado em `ExecutiveEngine`:
- Objetivos hierárquicos e relação pai/filho.
- Prioridade low/normal/high/critical.
- Estados planned, active, blocked, suspended, completed e cancelled.
- Foco único apontando para um objetivo ativo.
- Histórico append-only e reconstrução após reinício.
- Contexto de trabalho limitado para o pipeline cognitivo.

Ainda pendente:
- Decomposição automática de objetivos em subobjetivos.
- Planejamento multi-etapas com dependências e critérios de conclusão.
- Seleção adaptativa de ferramentas.
- Execução de tarefas com verificação e rollback.
- Recuperação de estado de execução após encerramento forçado do Android.

## 6. Ferramentas, pesquisa e engenharia

| Capacidade | Componentes | Maturidade atual | Limites |
|---|---|---|---|
| Inteligência de ferramentas | `tool_intelligence.py` | TESTED_INTEGRATION | Registro de evidência não comprova domínio universal |
| Catálogo de capacidades | `capability_manifest.py`, JSON | TESTED_INTEGRATION | Adaptadores permanecem desabilitados por padrão |
| Orquestração de pesquisa | `research_orchestrator.py` + `AutonomyGovernor` | IMPLEMENTED; CI pending | Uma tarefa por permit; contexto foreground explícito; deadline cooperativo e RAM admission-only; rede e efeitos externos bloqueados; integração Realme não validada |
| Pesquisa Android | `android_research.py` | IMPLEMENTED / testes existentes | Interfaces dependem de permissões reais |
| Engenharia e staging | `engineering.py`, `engineering_v2.py` | IMPLEMENTED / testes existentes | Ciclo autônomo de autoalteração ainda não validado |
| Registro de instalações | `installation_registry.py` | TESTED_INTEGRATION | Registro não é instalação |
| Diagnóstico profundo | `deep_diagnostics.py`, `perfetto_analyzer.py` | IMPLEMENTED / testes existentes | Dados dependem das interfaces Android |
| Telemetria | `telemetry.py` | IMPLEMENTED | Coleta contínua em segundo plano não validada |

## 7. Modelos neurais e independência

O adaptador `LocalModelAdapter` já pode compor identidade, memória executiva e memória conversacional e enviar uma geração explícita a um endpoint local loopback. `config/model_runtime.json` permanece desabilitada. Nenhum servidor, modelo ou download foi executado nesta branch.


| Capacidade | Componentes | Maturidade atual | Limites |
|---|---|---|---|
| Núcleo neural | `neural_core.py` | IMPLEMENTED / testes existentes | Não é um modelo geral de linguagem |
| Treinamento MLP | `neural_training.py` | TESTED_INTEGRATION | Não há aprendizagem contínua autônoma |
| Checkpoints | `neural_checkpoint.py` | TESTED_INTEGRATION | Retenção/esquecimento entre tarefas ainda não avaliados em produção |
| Adaptador de modelo local conversacional | `LocalModelAdapter` | TESTED_INTEGRATION | API loopback OpenAI-compatible; sem proxy, redirects, endpoint externo ou fallback remoto; backend real pendente |
| Adaptador de modelo externo | — | PLANNED | Rede deve ser opcional e controlada por Dharma |

Identidade, perfil, memória, objetivos e orquestração não devem depender de um único modelo neural. Modelos são motores intercambiáveis.

## 8. Criação, 3D, física e multimodalidade

| Domínio | Componentes/artefatos | Maturidade atual | Limites |
|---|---|---|---|
| Blender bridge | `blender_bridge.py` | IMPLEMENTED | Comunicação real no telefone não validada |
| Inteligência Blender | `blender_intelligence.py` | IMPLEMENTED | Domínio operacional precisa de testes reais |
| Executor Python Blender | `blender_python_executor.py` | IMPLEMENTED | Execução exige aprovação e sandbox adequados |
| Servidor/add-on Blender | `blender_server_v2.py`, `mahoraga_blender_addon_v2.py` | IMPLEMENTED | Integração de ponta a ponta pendente |
| Física | `physics.py`, `lab.py` | TESTED_INTEGRATION | Não implica simulação avançada de fluidos em tempo real |
| Pintura digital | — | PLANNED | Ferramenta e pipeline ainda não definidos |
| Geração/edição de imagem | — | PLANNED / ferramenta externa ou modelo futuro | Não implementada no núcleo |
| Animação/vídeo | Blender parcial | PLANNED / parcial | Pipeline multimodal não validado |
| World Engine/jogos | — | PLANNED | Projeto futuro |
| Voz e fala | — | PLANNED | Sem stack local de ASR/TTS integrada |
| Interface visual própria | perfil visual | PLANNED | Necessita arte, 3D, animação e integração UI |

## 9. Android, hardware e operação offline

| Capacidade | Componentes | Maturidade atual | Limites |
|---|---|---|---|
| Diagnóstico de hardware | `hardware_intelligence.py`, `device_core.py` | TESTED_INTEGRATION em CI | Snapshot atual do Realme precisa ser medido |
| Android/Termux | `android_research.py`, APIs | IMPLEMENTED / testes existentes | Permissões e restrições variam por versão |
| Perfetto | `perfetto_analyzer.py` | IMPLEMENTED | Captura real depende de acesso e disponibilidade |
| Shizuku | integração planejada/read-only | PLANNED / limitada | Sem root; não presumir privilégios |
| Termux:Boot | instalado no dispositivo | INSTALADO, comportamento não validado | Android pode restringir processos e reinícios |
| Execução residente | arquitetura híbrida desejada | PLANNED | Persistência não garante execução contínua |
| Operação offline | SQLite, lógica determinística e perfil local | PARCIALMENTE IMPLEMENTED | Geração neural offline depende do adaptador/modelo local |

Hardware de referência: Realme 14 5G, Snapdragon 6 Gen 4, ARM64, Android 16, 12 GB RAM física informada. Expansão de RAM é opcional e não deve ser contabilizada como RAM física. O estado Termux/Git local não é presumido sincronizado.

## 10. Laboratórios externos e dados

- **MTEB-BR/Colab — COG-RETRIEVAL-004:** notebook preparado, execução externa pendente. Não integrar embeddings sem comparar métricas, tamanho, latência, RAM, bateria e licença.
- **FlyWire FAFB v783:** arquivos locais encontrados anteriormente: Feather ~812,6 MiB e NPY com 139.255 IDs uint64. PyArrow não estava instalado; esquema, hashes e registros não foram inspecionados. Não carregar Feather integralmente em RAM.
- **PocketPal:** auxiliar opcional; não é dependência estrutural.
- **Modelos externos:** opcionais para pesquisa ou tarefas que excedam o hardware local.

## 11. Próximas prioridades

1. Revisar e integrar as PRs empilhadas #10, #11 e #12 somente após revisão e aprovação.
2. Construir memória conversacional estruturada e conectá-la ao contexto de persona e memória de trabalho.
3. Evoluir a representação semântica e a recuperação híbrida com benchmark MTEB-BR, preservando BM25 como baseline/fallback.
4. Melhorar o raciocínio contextual, a comparação de hipóteses e a calibração de incerteza.
5. Fortalecer a aprendizagem adaptativa com retenção, contradições, generalização e evidências autenticáveis.
6. Avaliar um adaptador neural local leve e interoperável.
7. Inspecionar o dataset FlyWire por streaming/amostras e extrair hipóteses de modularidade/roteamento.
8. Inspecionar Termux e preparar benchmark de llama.cpp local, sem instalar até confirmar espaço, dependências e rollback.
9. Validar no Realme, com backup, testes progressivos, medição de recursos e rollback.

## 12. Evidência atual deste checkpoint

- Adaptador de modelo local loopback integrado ao pipeline e testado com endpoint HTTP simulado; não houve conexão com runtime real.
- CI #465 (run 43798086280): Python 3.12/3.14, 358 passed, 1 skipped, 28 subtests por ambiente.
- CI #478 (run 43798229672): revalidação do checkpoint com mapa/continuidade atualizados; Python 3.12/3.14, 358 passed, 1 skipped, 28 subtests por ambiente.

- Memória conversacional estruturada integrada ao CognitiveEngine, IntegratedCore e IntrospectionEngine.
- CI #407 (run 43797022111): Python 3.12/3.14, 345 passed, 1 skipped, 28 subtests por ambiente.
- CI #435 (run 43797654247), após hardening de validação/contexto: Python 3.12/3.14, 347 passed, 1 skipped, 28 subtests por ambiente.

- PR #12: draft, branch `work/cognitive-entity-expansion-20261116`.
- Backup: `backup/pre-cognitive-expansion-20261116`.
- CI #365 e #366: Python 3.12/3.14, 338 passed, 1 skipped, 28 subtests por ambiente.
- CI comprova execução em runners GitHub, não no Realme.
- Nenhum merge realizado; Termux não sincronizado.


## Atualização operacional — 2026-11-16 (PRs #13 e #14)

### Plasticidade, iniciativa intelectual e ciclo de pesquisa

| Capacidade | Componentes/artefatos | Maturidade | Limites atuais |
|---|---|---|---|
| Plasticidade por protótipos | `agent/prototype_plasticity.py` | TESTED_INTEGRATION | Aprende somente vetores finitos fornecidos por um encoder externo; não possui encoder de linguagem/visão/áudio e não atualiza pesos de LLM |
| Avaliação sintética da plasticidade | `scripts/evaluate_prototype_plasticity.py`, `tests/test_prototype_plasticity_benchmark.py` | TESTED_INTEGRATION | Mede adaptação, retenção, abstinência, novidade e replay em vetores sintéticos; não demonstra generalização real nem desempenho no Android |
| Síntese de iniciativas | `ExecutiveEngine.review_initiatives()` | TESTED_INTEGRATION | Sob demanda; não há curiosidade agendada ou espontânea |
| Plano de pesquisa a partir de iniciativa | `ResearchOrchestrator.prepare_initiative_plan()` | TESTED_INTEGRATION | Persistência aprovada/idempotente; estado preparado, sem executar pesquisa ou ferramentas |
| Feedback de resultados de pesquisa | `AdaptiveLearning.record_research_result()` | TESTED_INTEGRATION | Relato fornecido pelo chamador, não autenticado independentemente; fica episódico e não validado |
| Ciclo autônomo de iniciativa e conclusão | — | PLANNED | Faltam score informacional calibrado, orçamento, cooldown, execução autorizada e verificação independente dos resultados |

**Evidência atual:** PR #13, branch `work/continual-plasticity-initiative-20261116`, HEAD de código `a7bb7f79b73a55373c83b5995d530976d01e82f4`, CI #657: 401 passed, 1 skipped e 28 subtests em Python 3.12/3.14; validador com 88 verificações. PR #14, branch `work/prototype-plasticity-benchmark-20261116`, HEAD de código `b042bef0351fcade69f99d32fd595ec4c8216cb7`, CI #661: 405 passed, 1 skipped e 28 subtests em Python 3.12/3.14; validador com 88 verificações. Ambas permanecem draft; nenhuma foi mesclada.

### Especialização financeira

| Domínio | Maturidade | Estado conhecido |
|---|---|---|
| Finanças e investimentos | PLANNED | Objetivo futuro registrado para acompanhamento/análise de ativos brasileiros, incluindo mercado B3. Contexto histórico de conversa: foi registrado um objetivo de aportes aproximados de R$ 100 por mês em ativos brasileiros, com início planejado para dezembro de 2026. Esse valor/data representam intenção de planejamento recuperada, não carteira, recomendação, capacidade implementada ou autorização para transacionar. Não foi localizado módulo implementado, integração de contas, execução de ordens ou código financeiro nesta árvore consultada; escopo e requisitos permanecem a especificar. |

A especialização financeira deverá reutilizar memória, conhecimento, pesquisa, identidade, introspecção e Dharma existentes. Não criar um segundo núcleo, nem habilitar transações, acesso a contas ou operações financeiras sem requisitos, fontes, permissões e autorização específicos.

### Estado de integração

- PRs #10–#14 permanecem abertas em draft e empilhadas; não fazer merge fora de ordem.
- PR #13 é a primeira implementação da plasticidade por protótipos e do ciclo iniciativa → plano → resultado → replay.
- PR #14 acrescenta avaliação sintética reproduzível dessa plasticidade.
- `COG-RETRIEVAL-004` continua sendo o workstream principal em `WAITING_EXTERNAL_EXECUTION`; o notebook MTEB-BR no Colab não foi executado.
- Termux/Realme não foram sincronizados nem validados nesta sequência. Nenhum modelo ou runtime neural foi instalado.


## Atualização operacional — concorrência do learner (PR #16, 2026-11-16)

| Capacidade | Componente | Maturidade | Limites |
|---|---|---|---|
| Serialização de estado do PrototypePlasticity | `agent/prototype_plasticity.py`, `RLock` por instância | TESTED_INTEGRATION | Serializa aprendizagem, predição e snapshots na mesma instância compartilhada; não coordena múltiplos processos ou instâncias independentes no mesmo SQLite |

**Evidência:** PR #16, branch `work/prototype-plasticity-locking-integration-20261116`, CI #684: Python 3.12/3.14, 406 passed, 1 skipped, 28 subtests e 88 verificações de continuidade em cada ambiente. O teste concorrente força sobreposição potencial entre operações, executa 32 atualizações e verifica preservação de contadores e replay. PR permanece draft, sem merge. PR #15 foi fechada como substituída por #16; seus commits/branch foram preservados.

## Atualização operacional — integração de contexto, concorrência e RRF (2026-11-16)

| Capacidade | Artefatos | Maturidade | Limites |
|---|---|---|---|
| Recuperação no contexto gerativo | `IntegratedCore.generate_local_response()`, `KnowledgeEngine` | TESTED_INTEGRATION | Até 5 fragmentos/6.000 caracteres; consulta BM25 explícita opcional; refs não são fatos verificados; endpoint local foi simulado e runtime segue desabilitado |
| Serialização da memória conversacional | `ConversationMemoryEngine` | TESTED_INTEGRATION | RLock por instância/processo; não coordena múltiplos processos/instâncias independentes no mesmo SQLite |
| Fusão de rankings RRF | `KnowledgeEngine.fuse_rankings_rrf()` | TESTED_INTEGRATION em CI após PR #19 | Primitiva determinística para listas já ranqueadas; nenhum encoder denso está conectado, BM25 segue como único canal ativo |

**PR #17 / COG-CORE-GENERATION-001:** CI #726, run `43851373550`, 406 passed, 1 skipped, 28 subtests e 88 verificações em Python 3.12/3.14. O gerador local agora recebe fragmentos recuperados, proveniência, decisão linguística e estado da preparação. `knowledge_query` e `knowledge_subject` permitem separar a pergunta de geração da consulta associativa.

**PR #18 / COG-CONVERSATION-SERIAL-001:** CI #732, run `43852935763`, 407 passed, 1 skipped, 28 subtests e 88 verificações em Python 3.12/3.14. O teste executa 48 gravações simultâneas e exige índices únicos e contíguos. A proteção é por instância dentro de um processo.

**PR #19 / COG-RETRIEVAL-FUSION-001:** estado de código e CI deve ser lido no HEAD atual da PR. A primitiva RRF combina rankings lexicais/densos por identidade e posição, preserva fontes, scores e hashes, e não executa inferência. Não equivale a retrieval híbrido operacional até um encoder/índice semântico ser conectado e benchmarkado.

Pesquisa de modelos compactos e execução on-device documentada em `docs/research/associative-retrieval-and-ondevice-learning-20261116.md`. Granite 97M Multilingual R2 é candidato de teste, não modelo escolhido/instalado. MTEB-BR/Colab continua pendente. Nenhum modelo, pacote ou artefato foi baixado ou instalado no Realme.
## Atualização de integridade de aprendizagem — COG-LANGUAGE-CHECKPOINT-001 (2026-11-16)

| Capacidade | Componente | Maturidade | Limite |
|---|---|---|---|
| Coerência dataset/checkpoint linguístico | `LanguageEngine` | TESTED_INTEGRATION | SHA-256 do dataset vinculado ao metadata; CI #866 passou com 426 passed, 1 skipped, 28 subtests e 88 checks em Python 3.12/3.14; sem validação Realme |

PR #23 corrige carregamento de pesos treinados em conjunto de exemplos anterior. Checkpoints legados sem fingerprint deixam de ser carregados e são preservados; após atualizar exemplos é necessário treinar novamente.


## Atualização de concorrência do LanguageEngine — COG-LANGUAGE-SERIAL-001 (2026-11-16)

| Capacidade | Componente | Maturidade | Limites |
|---|---|---|---|
| Serialização de estado linguístico | `LanguageEngine`, `RLock` por instância | IMPLEMENTED; CI em validação | Protege dataset, treino, classificação e status na mesma instância/processo; não coordena instâncias/processos independentes |

PR #24 acrescenta serialização reentrante a `add_examples()`, `train()`, `classify()` e `status()`. Testes concorrentes cobrem atualização do dataset durante treino e leitores durante transições. A primeira CI encontrou fixtures de regressão que instanciavam o objeto via `__new__`; os fixtures foram corrigidos para inicializar o lock. A CI corretiva está em andamento. Não declarar maturidade TESTED_INTEGRATION até a conclusão bem-sucedida da CI final.

**Validação final da PR #24:** CI #891 / run `43867116203` validou o código: Python 3.12/3.14, 428 passed, 1 skipped e 28 subtests por ambiente. Após os registros documentais, CI #905 / run `43867551002` validou o HEAD documental final, com os mesmos resultados e validador de continuidade aprovado nos dois ambientes. Maturidade: TESTED_INTEGRATION em CI, limitada à mesma instância/processo. Sem validação no Realme.


## Atualização — sequência transacional da memória conversacional (COG-CONVERSATION-ATOMIC-001, PR #25)

| Capacidade | Componente | Maturidade | Limites |
|---|---|---|---|
| Alocação atômica de índice de troca | `KnowledgeStore.record_sequenced_event()` + `ConversationMemoryEngine` | IMPLEMENTED; CI em validação | Escopo atual limitado ao índice de troca conversacional; outros read-modify-write ainda precisam de auditoria |

O schema SQLite evolui para v5 com `event_sequences`. A reserva do próximo índice e a inserção do evento ocorrem sob `BEGIN IMMEDIATE`, permitindo coordenação entre conexões/processos que compartilham o mesmo arquivo. Testes cobrem múltiplas instâncias de Store e três processos independentes. CI #926 identificou duas expectativas antigas de schema v4, atualizadas para v5; CI #929 está em andamento. Não declarar TESTED_INTEGRATION até CI final aprovada.

**Validação final da PR #25:** CI #929 / run `43868711796` passou em Python 3.12 e 3.14; cada job executou 431 passed, 1 skipped e 28 subtests, com validador de continuidade aprovado. Teste multi-processo aprovado no runner Linux. Isso comprova a sequência transacional no ambiente CI, não no Android/Termux.
Maturidade: TESTED_INTEGRATION em CI para a sequência conversacional; escopo não abrange os demais engines.


## Atualização — idempotência executiva entre processos (COG-EXEC-CAS-001, PR #26)

| Capacidade | Componente | Maturidade | Limites |
|---|---|---|---|
| Transição de meta protegida por revisão/idempotency key | `ExecutiveEngine.transition_goal()` + `KnowledgeStore.record_event_once()` | TESTED_INTEGRATION em CI | Aplicada a transições; criação genérica de metas e foco seguem em auditoria |
| Adoção única de iniciativa entre processos | `ExecutiveEngine.adopt_initiative()` + `record_event_once()` | TESTED_INTEGRATION em CI | Exige aprovação explícita e revisão recente; não executa ferramentas |

CI #960 / run `43870283150`: Python 3.12 e 3.14, cada ambiente com 433 passed, 1 skipped e 28 subtests. Testes com dois processos independentes validam que apenas uma transição da mesma revisão é aceita e que a adoção de um candidato cria exatamente uma meta. Nenhuma validação no Realme.


## Atualização — compare-and-swap do foco executivo (COG-EXEC-FOCUS-CAS-001, PR #27)

| Capacidade | Componente | Maturidade | Limites |
|---|---|---|---|
| Atualização do foco por revisão idempotente | `ExecutiveEngine.set_focus()` + `KnowledgeStore.record_event_once()` | TESTED_INTEGRATION em CI | Validação de atividade do objetivo permanece anterior à gravação |

A atualização do foco agora usa a identidade do último evento de foco como revisão esperada; processos concorrentes sobre a mesma revisão não sobrescrevem silenciosamente uns aos outros. CI #979 / run `43870820970`: Python 3.12 e 3.14, cada ambiente 434 passed, 1 skipped e 28 subtests.


## Atualização — eficiência de GitHub Actions (OPS-CI-EFFICIENCY-001, PR #28)

| Capacidade | Componente | Maturidade | Resultado |
|---|---|---|---|
| Evitar CI duplicada em push + pull_request para branches de trabalho | `.github/workflows/physics-tests.yml` | TESTED_INTEGRATION em CI | CI #983 executou a matriz Python 3.12/3.14 uma vez para a PR |

O workflow agora valida push somente em `main`, PRs direcionadas a `main` ou `work/**`, e mantém `workflow_dispatch`. Um grupo `concurrency` por PR cancela execuções obsoletas quando uma atualização mais nova chega. CI #983 / run `43871357177`: 434 passed, 1 skipped e 28 subtests em cada versão Python. A redução de duplicidade entre eventos é mudança de configuração; sua economia acumulada deve ser observada após uso continuado.


## Pesquisa — conectomas e arquitetura cognitiva integrada (COG-NEURAL-ARCH-001)

| Capacidade | Componente/linha | Maturidade | Limite |
|---|---|---|---|
| Toolkit neural feed-forward | \`neural_core.py\`, \`neural_training.py\`, \`neural_checkpoint.py\` | IMPLEMENTED; test coverage exists | MLP NumPy float32; não é SNN nem conectoma |
| Pesquisa FlyWire/BANC | \`docs/research/brain_connectome_and_cognitive_architecture_20261116.md\` | RESEARCH_DOCUMENTED | Nenhum subgrafo ou simulador integrado |
| Arquitetura funcional inspirada em neurociência humana | Mesmo documento + módulos existentes | RESEARCH_DOCUMENTED | Princípios funcionais; não equivalência anatômica |
| Integração de branches #20–#28 | Auditoria de dependências | AUDITED; convergence pending | #20/#21 e #22 são linhas paralelas a #23–#28 |

A pesquisa estabelece que FlyWire, BANC e circuitos humanos devem orientar hipóteses computacionais pequenas e testáveis, não a importação literal de um cérebro completo. O documento também registra que a branch #28 não contém o lock por instância da PR #21 nem o notebook endurecido da PR #22. Nenhuma PR foi mesclada; \`main\` permanece sem essas alterações.



## 10. Laboratórios online e modelos abertos — extensão COG-NEURAL-ARCH-001

| Capacidade | Artefato | Maturidade | Limite |
|---|---|---|---|
| Laboratório remoto offline-first | Especificação em docs/research/brain_connectome_and_cognitive_architecture_20261116.md | RESEARCH_DOCUMENTED | Nenhum adaptador remoto foi implementado; Colab depende de disponibilidade variável |
| Extração de embeddings/hidden states | Transformers e llama.cpp como candidatos | RESEARCH_CANDIDATE | Depende de arquitetura, runtime, pooling, licença e benchmark |
| Destilação teacher-student | Experimentos Colab futuros | PLANNED | Sem dataset derivado, treinamento ou modelo aluno criado |
| Modelo local Qwen 2.5 1.5B Q4 | PocketPal | NOT_VALIDATED | Histórico registra “Out of Room” / “Model not loaded”; não confirmado carregamento |
| MTEB-BR | Notebook PR #22 | IMPLEMENTED_UNEXECUTED | Execução real no Colab pendente |

A arquitetura passa a distinguir inferência remota, laboratório remoto e operação local. Rede e GPU externa podem acelerar pesquisa e treinamento, mas não são dependências para identidade, memória ou operação essencial offline. Pesos e datasets grandes não devem ser commitados no Git comum; registrar manifestos, hashes, licenças, ambiente e métricas.


## Convergência de concorrência executiva — COG-EXEC-LOCK-CONVERGENCE-001 (2026-11-16)

| Capacidade | Componente | Maturidade | Evidência/limite |
|---|---|---|---|
| Lock reentrante por instância + idempotência SQLite multiprocesso | `ExecutiveEngine` | IMPLEMENTED; CI pending | RLock serializa chamadas na mesma instância; `record_event_once()` continua protegendo transições entre processos. Testes novos aguardam CI. Sem validação Android. |

A branch foi criada a partir do HEAD documental da PR #29. A integração restaura a proteção por instância da PR #21 sobre a linha transacional #26/#27, sem substituir as chaves idempotentes. Foram adicionados testes para 12 transições concorrentes na mesma instância e reentrância de `review_initiatives()`/`snapshot()`/`status()`. Não fazer merge até CI e revisão dos diffs.


### Resultado de validação — COG-EXEC-LOCK-CONVERGENCE-001

- CI #992 / run `43881950893`, HEAD `1087109a135279170272a153638a7604f68b767c`.
- Python 3.12 e 3.14: cada job concluiu com sucesso, 436 passed, 1 skipped e 28 subtests.
- Compilação, holdouts linguísticos v1/v2/v3, benchmark de retrieval, validador de continuidade e suíte completa concluíram sem falha.
- Classificação: TESTED_INTEGRATION em CI; ainda não validado no Termux/Realme.


## Convergência do laboratório MTEB-BR — COG-RETRIEVAL-CONVERGENCE-001 (2026-11-16)

| Capacidade | Artefato | Maturidade | Limite |
|---|---|---|---|
| Notebook MTEB-BR reproduzível | `notebooks/mahoraga_embedding_research_colab.ipynb` | IMPLEMENTED; CI pending | Integrado da PR #22; Colab ainda não executado |
| Integridade do notebook | `tests/test_embedding_notebook_integrity.py` | IMPLEMENTED; CI pending | Testes verificam pins, oito tarefas, SHA dos modelos, wrapper e ausência de treino |

A branch é empilhada sobre PR #30 para trazer a linha paralela #22 ao ramo consolidado. Mantém o benchmark isolado do núcleo, não treina modelos e não baixa artefatos para o Realme.


### Validação — COG-RETRIEVAL-CONVERGENCE-001

- CI #996 / run `43882466737`, HEAD `f8f695444e8fee0e5e1b1a82b99a0ad317611b81`.
- Python 3.12 e 3.14: cada ambiente 439 passed, 1 skipped e 28 subtests; ambos os jobs concluídos com sucesso.
- Compilação, holdouts linguísticos, retrieval, validador de continuidade e testes de integridade do notebook aprovados.
- Classificação: TESTED_INTEGRATION em CI para os artefatos versionados; notebook Colab não executado.


## COG-PERCEPTION-AUTONOMY-001 — Percepção limitada e autonomia governada (2026-11-16)

| Capacidade | Artefato | Maturidade atual | Limite |
|---|---|---|---|
| Inventário dos sensores Android | agent/perception_engine.py | IMPLEMENTED; CI pending | Consulta Termux:API; depende do inventário real e permissões do aparelho |
| Amostragem sensorial | PerceptionEngine.sample_sensors() | IMPLEMENTED; CI pending | Até quatro sensores, uma leitura por sensor, sem streaming contínuo |
| Autoestado operacional | HardwareIntelligence + PerceptionEngine | IMPLEMENTED; APIs existentes | Telemetria do dispositivo; não é sensação subjetiva nem calibração biológica |
| Orçamento de autonomia | agent/autonomy_governor.py | IMPLEMENTED; CI pending | Exige foreground e estado de tela explícitos; computação local limitada |
| Priorização de iniciativas | AutonomyGovernor.rank_initiatives() | IMPLEMENTED; CI pending | Dá peso ao progresso de aprendizagem, não adota nem executa iniciativas |
| Plano de trabalho autônomo | IntegratedCore.plan_autonomous_work() | IMPLEMENTED; CI pending | Revisão e planejamento apenas; sem dispatch, sem mudanças Android ou writes de projeto |
| Captura de câmera/microfone | — | PLANNED | Não implementada; exige foreground, autorização e retenção controlada |
| STDP/EGP/SNN/Conectoma | Pesquisa neural | RESEARCH_DOCUMENTED | Sem SNN ou atualização paramétrica contínua no núcleo |

A arquitetura reutiliza KnowledgeStore, HardwareIntelligence, Dharma, CognitiveEngine, ExecutiveEngine e ResearchOrchestrator. Não foi criada memória paralela nem um executor autônomo irrestrito. Documento de pesquisa: docs/research/adaptive-cognition-perception-autonomy-20261116.md.


### Validação — COG-PERCEPTION-AUTONOMY-001

- PR #32, CI #1005 / run 43888708293, HEAD bf9907be85e5406d9421a87778464869bf823b3c.
- Python 3.12 e 3.14: cada ambiente 455 passed, 1 skipped e 28 subtests; ambos os jobs concluíram com sucesso.
- A suíte inclui amostragem de sensores one-shot, rejeição de nomes ambíguos, validação de valores, governança foreground/charging, limites térmicos/RAM/armazenamento e integração do núcleo.
- Estado: TESTED_INTEGRATION em CI. Inventário e amostragem no Realme continuam pendentes.


## COG-ANDROID-RUNTIME-CONTEXT-001 — Contexto Android para autonomia foreground (2026-11-16)

| Capacidade | Componente | Maturidade | Limite |
|---|---|---|---|
| Leitura interativa/display | HardwareIntelligence.runtime_context() | IMPLEMENTED; CI pending | Consulta Shizuku/rish; exige mInteractive + Display Power ON |
| Identificação foreground | parser topResumedActivity/mResumedActivity | IMPLEMENTED; CI pending | Reconhece somente com.termux nesta fase |
| Estado térmico | parser ThermalStatus 0–6 | IMPLEMENTED; CI pending | Formato não reconhecido continua unknown |
| Decisão fail-closed | AutonomyGovernor.evaluate_session(None) | IMPLEMENTED; CI pending | Ausência/negação/erro de Shizuku pausa a computação |

Pesquisa: docs/research/android-runtime-context-and-foreground-autonomy-20261116.md. Não usa root, wake lock, FGS, câmera ou microfone.


### Atualização de pesquisa e maturidade — 16/11/2026

- Evidência de HiCL, SYNERgy, Evidence-Gated Plasticity, LT-Gate, CLP-SNN, SynGAP, ELEMENT, motivação intrínseca para world models, Ego-METAS e predictive processing foi adicionada a docs/research/adaptive-cognition-perception-autonomy-20261116.md.
- Decisão D-054: proposta plástica temporária → avaliação comparativa/holdout → consolidação contextual; novidade isolada não dirige curiosidade.
- Lacuna identificada: AdaptiveLearning.prediction_error ainda compara textos por igualdade exata; rank_initiatives recebe learning_progress/uncertainty_reducible declarados pelo chamador e ainda não os estima de curvas reais.
- Lacuna identificada: não há ainda modelo de mundo multimodal treinado, replay generativo, estado metaplástico paramétrico ou SNN no núcleo.
- Benchmark cognitivo especificado: previsão temporal, recuperação episódica, generalização composicional, retenção/esquecimento, progresso de aprendizagem versus noisy-TV, plasticidade por ablação, fusão sensorial degradada e criatividade avaliada por utilidade posterior.
- PR #33 / COG-ANDROID-RUNTIME-CONTEXT-001: CI #1010 e #1013 falharam; logs/artifacts detalhados não foram recuperados. A CI foi instrumentada para reter relatório do validador de continuidade e JUnit. O commit 2369229edb6baf1760ff7a59be0d890a5fd40031 ainda não tinha run associado no momento do registro. Não declarar validação.
- A leitura Android continua sem teste real no RMX5070; Termux/Blender não foram sincronizados nem usados para captura.


## COG-LEARNING-PROGRESS-001 — Progresso de aprendizagem medido (2026-11-16)

| Capacidade | Artefato | Maturidade | Limite |
|---|---|---|---|
| Erro preditivo numérico | AdaptiveLearning.record_experience() | IMPLEMENTED; CI inconclusiva | MAE normalizado com escala fixa declarada |
| Progresso em janelas | AdaptiveLearning.review_experiences() | IMPLEMENTED; CI inconclusiva | Mesma tarefa/contexto/preditor/métrica/escala; mínimo 4 amostras |
| Propagação à iniciativa | ExecutiveEngine.review_initiatives() | IMPLEMENTED; CI inconclusiva | Evidência ainda caller-supplied; independência não autenticada |
| Penalidade por regressão | AutonomyGovernor.rank_initiatives() | IMPLEMENTED; CI inconclusiva | Sinal descritivo, não prova causal |

PR #34: work/learning-progress-cognition-20261116, baseada no HEAD validado da PR #32. CI #1016, #1017, rerun #1018, #1019 e #1020 falharam; nos runs #1018–#1020 logs_url/steps vieram nulos e não houve artifacts. Causa não determinada; não classificar como TESTED_INTEGRATION. Sem execução no Realme.


## COG-UNIFIED-LOOP-001 — especificação do ciclo cognitivo único (2026-11-16)

| Capacidade/artefato | Maturidade | Limite |
|---|---|---|
| Especificação integrada percepção→crenças→modelo de mundo→motivação/criatividade→ação governada→avaliação→replay/consolidação | SPECIFICATION / PR #36 Draft | Não equivale a implementação |
| Contratos Observation, BeliefState, Episode e CandidateUpdate | SPECIFIED | Integração com KnowledgeStore pendente |
| Memória canônica com regimes temporais e replay estratificado | DESIGN | Não criar bancos paralelos |
| Modelo de mundo plausible→controllable→actionable | DESIGN | Sem modelo multimodal treinado |
| Plasticidade rápida/intermediária/lenta com avaliação e rollback | DESIGN | Nenhuma atualização de pesos consolidada |
| Motivação e criatividade avaliadas por progresso, utilidade, diversidade, custo e risco | DESIGN | Sem geração autônoma validada |

PR #36: `work/unified-cognitive-loop-spec-20261116`, documento `docs/architecture/UNIFIED_COGNITIVE_LOOP.md`. Pesquisa de 2026 incorporada com status de preprint/survey preservado.

### Diagnóstico independente de CI

- PR #35 / run #1 `43904717157`: workflow mínimo com um job e um `echo` falhou sem steps, logs ou artifacts; download retornou `404 BlobNotFound`.
- PR #34 / run #1023 `43904716851`: jobs Python 3.12/3.14 também sem steps/logs/artifacts.
- PR #36 / run #1024 `43904989333`: mesma assinatura em alteração somente documental.
- Evidência aponta para falha pré-execução/telemetria do Actions, mas não determina causa raiz. Código da PR #34 permanece UNVALIDATED, não reprovado por testes.


## COG-CORE-HARDENING-001 — auditoria e endurecimento do núcleo (2026-11-16)

| Correção | Artefatos | Maturidade | Limite |
|---|---|---|---|
| Autocertificação de independência de fontes removida do ranqueador | AutonomyGovernor + testes | IMPLEMENTED / TESTS ADDED | CI não executou |
| Overflow numérico tratado em governor, aprendizagem, percepção e protótipos | AdaptiveLearning, PerceptionEngine, PrototypePlasticity | IMPLEMENTED / TESTS ADDED | CI não executou |
| Progresso não mistura preditores/métricas/escalas diferentes | AdaptiveLearning + ExecutiveEngine + testes | IMPLEMENTED / TESTS ADDED | CI não executou |
| Timeout do inventário sensorial corretamente classificado | PerceptionEngine + testes | IMPLEMENTED / TESTS ADDED | Sem validação RMX5070 |
| Sessão de autonomia HMAC, TTL e uso único | AutonomyGovernor + testes | IMPLEMENTED / TESTS ADDED | Protege contra adulteração/replay acidental; não é sandbox intra-processo |

Auditoria: `docs/audits/CORE_HARDENING_AUDIT_20261116.md`. Estado da PR #37 Draft quando criada; nenhum teste deve ser considerado aprovado até CI executável e/ou execução local reproduzível.

Riscos bloqueadores documentados: execução Python no Blender é `exec` com autoridade total e aprovação autodeclarada; checkpoint NPZ carece de preflight de tamanho/schema; memória não possui política transversal de taint/rollback; contexto de runtime exige fonte e freshness verificadas; deadline do Orchestrator é cooperativo e RAM é admission-only; cadeia de branches tem dívida de integração significativa.


## COG-LANGUAGE-HARDENING-001 — integridade do LanguageEngine (2026-11-16)

| Capacidade | Artefato | Maturidade | Limite |
|---|---|---|---|
| Raiz JSON validada em dataset/model metadata | LanguageEngine | IMPLEMENTED / TESTS ADDED | CI não executou |
| Deduplicação e rejeição de rótulos conflitantes | LanguageEngine.add_examples / _load_examples | IMPLEMENTED / TESTS ADDED | Proveniência individual ainda ausente |
| Contrato do modelo inclui versão de features, analyzer e léxico | LanguageEngine metadata | IMPLEMENTED / TESTS ADDED | Checkpoints antigos exigem retreino |
| Limites de tamanho para dataset/metadados/modelo | LanguageEngine loader | IMPLEMENTED / TESTS ADDED | Não substitui sandbox de arquivo externo |
| Benchmark end-to-end do MLP | scripts/evaluate_language_regression.py | AVAILABLE / NOT EXECUTED | Sem métricas novas |

PR #38 Draft: branch `work/language-engine-hardening-20261116`, empilhada sobre PR #37. Pesquisa e lacunas em `docs/audits/LANGUAGE_ENGINE_AUDIT_20261116.md`.


## COG-STORE-INTEGRITY-001 — integridade transacional do Store (2026-11-16)

| Correção | Artefato | Maturidade | Limite |
|---|---|---|---|
| Memória e evento de auditoria atômicos | KnowledgeStore.save_memory | IMPLEMENTED / TESTS ADDED | CI não executou |
| Confiança numérica estrita | KnowledgeStore.record_observation / record_observation_and_event | IMPLEMENTED / TESTS ADDED | Sem validação no Realme |
| Contrato estrito de evento e payload | KnowledgeStore.record_event | IMPLEMENTED / TESTS ADDED | Outros métodos legados ainda precisam revisão |

Auditoria: `docs/audits/STORE_INTEGRITY_AUDIT_20261116.md`. Riscos restantes: `default=str`, leitura JSON fail-fast, ausência de auditor de integridade JSON e trust state transversal.



## COG-LEARNING-TRUST-BOUNDARY-001 — proveniência e promoção confiável (2026-11-16)

| Capacidade | Artefato | Maturidade | Limite |
|---|---|---|---|
| Candidato usa somente episódios com recibo de evidência validado | AdaptiveLearning | IMPLEMENTED / TESTS ADDED | Provider real ainda não integrado |
| Diversidade de fontes baseada em source_id autenticado | AdaptiveLearning | IMPLEMENTED / TESTS ADDED | Depende do provider de evidência |
| Promoção semântica com atestado one-shot vinculado ao hash | AdaptiveLearning / CognitiveEngine | IMPLEMENTED / TESTS ADDED | Sem provider, promoção bloqueada |
| Plasticidade persistente com evidência + aprovação verificadas | PrototypePlasticity | IMPLEMENTED / TESTS ADDED | Sem provider, aprendizagem persistente bloqueada |
| Replay de deltas verificados; legado sem recibo em quarentena | PrototypePlasticity | IMPLEMENTED / TESTS ADDED | Checkpoint assinado e compactação pendentes |
| Aprovação de Python no Blender vinculada ao payload | Dharma / BlenderBridge | IMPLEMENTED / TESTS ADDED | Provider de produção ausente |

Auditoria: `docs/audits/LEARNING_TRUST_BOUNDARY_AUDIT_20261116.md`. Nenhum provider criptográfico real, CI desta branch ou teste Realme foi validado. Dados legados permanecem preservados, porém não confiáveis.

## Atualização operacional — COG-METACOG-001 e cadeia de hardening (2026-11-16)

| PR | Workstream | Branch | Base | Estado |
|---|---|---|---|---|
| #39 | COG-STORE-INTEGRITY-001 | `work/store-integrity-hardening-20261116` | `work/language-engine-hardening-20261116` | Draft, não mesclada |
| #40 | COG-EXEC-GOVERNOR-001 | `work/governed-execution-20261116` | `work/store-integrity-hardening-20261116` | Aberta, não mesclada |
| #41 | COG-LEARNING-TRUST-BOUNDARY-001 | `work/evidence-attestation-hardening-20261116` | `work/governed-execution-20261116` | Aberta, não mesclada |
| #42 | COG-METACOG-001 | `work/metacognitive-monitor-integration-20261116` | `work/evidence-attestation-hardening-20261116` | Draft, não mesclada |

### PR #42 — calibração metacognitiva integrada

- `MetacognitiveMonitor` reutiliza eventos verificados de `AdaptiveLearning` no `KnowledgeStore` canônico.
- Métricas categóricas: Brier binário de correção e Expected Calibration Error (ECE); erro de predição numérica permanece separado.
- Métricas exigem escopo por `predictor_id` e tarefa; não agregam preditores/domínios incompatíveis.
- O monitor é conectado a `CognitiveEngine`, `IntegratedCore` e `IntrospectionEngine`; abstenção é consultiva e não concede autoridade de execução.
- Testes adicionados para proveniência, separação de preditores, calibração e abstenção.

### Estado de validação da cadeia

- Runs recentes das PRs #39–#42 falharam antes de alocar runner: `runner_id=0`, sem steps/logs. A causa raiz do serviço não está determinada.
- Não classificar essas execuções como testes reprovados nem como aprovados. Código da PR #42: IMPLEMENTED / TESTS ADDED / CI UNVALIDATED.
- Providers de produção, Android Keystore, validação no Termux/Realme e integração real com hardware permanecem pendentes.
- Nenhuma PR foi mesclada; `main`, Termux, SQLite local e aparelho não foram alterados.


## COG-ORGANIC-FABRIC-001 — comunicação orgânica, workspace e conectoma operacional (2026-11-17)

**Base:** HEAD da PR #42, `6c5d0cf41c5686327d9c0caa574a4fee42d6ed33`.  
**Branch:** `work/organic-cognitive-integration-20261117`.  
**Estado:** implementação adicionada e testes criados; execução da suíte/CI pendente; Realme não validado.

| Capacidade | Artefato | Maturidade desta branch | Limite |
|---|---|---|---|
| Sinais tipados com origem, destino, correlação, causalidade e estado epistemológico | `agent/cognitive_fabric.py` | IMPLEMENTED / TESTS ADDED | despacho síncrono e limitado |
| Workspace transitório compartilhado | `CognitiveWorkspace` | IMPLEMENTED / TESTS ADDED | somente memória do processo/ciclo; sem persistência |
| Despacho para componente inscrito e endereçado | `CognitiveFabric.publish()` | IMPLEMENTED / TESTS ADDED | handlers síncronos confiáveis; sem execução externa |
| Conectoma estrutural derivado de vínculos verificados | `IntegratedCore._configure_cognitive_fabric()` | IMPLEMENTED / TESTS ADDED | representa relações de software, não anatomia |
| Fluxos de runtime observados | `connectome_snapshot()` | IMPLEMENTED / TESTS ADDED | contagem não prova compreensão ou eficácia |
| Linha de base operacional por estágio | `workspace_report().effectome` | IMPLEMENTED / TESTS ADDED | observacional; causalidade não estabelecida |
| Ciclo linguagem → recuperação → raciocínio → executivo → conversa → introspecção → pesquisa | `IntegratedCore.prepare_request()` | IMPLEMENTED / TESTS ADDED | integração síncrona; demais caminhos dos módulos ainda não assinam sinais |
| Inspeção read-only do conectoma | `IntegratedCore.inspect_cognitive_fabric()` | IMPLEMENTED / TESTS ADDED | snapshot em memória, sem histórico persistente |

### Preservação e segurança

- Nenhuma tabela ou migração SQLite foi adicionada.
- O fabric não abre Store, não grava memória, não executa ferramentas, não inicia background e não acessa rede.
- `prepare_request()` mantém contrato sem escrita persistente; a nova suíte contém teste para comparar contagens/eventos antes e depois.
- Os sinais não concedem autoridade nem alteram Dharma, AutonomyGovernor, providers de evidência ou aprovação.
- `main`, Termux, Realme e banco local não foram modificados.

### Dossiê e pesquisa

- Criado `docs/research/MAHORAGA_RESEARCH_DOSSIER.md` como índice/síntese canônica da pesquisa de arquitetura, ciência, memória e oportunidades.
- Atualizado `docs/research/brain_connectome_and_cognitive_architecture_20261116.md` com a pesquisa de conectomas distribuídos, memória temporal, mapas cognitivos e conexão com o código atual.
- Criado `docs/architecture/ORGANIC_COGNITIVE_FABRIC.md` com contratos, limites, fases e critérios de validação.

### Próximos gates

1. Obter runner CI com steps/logs e executar testes em Python suportado.
2. Revisar a cadeia empilhada #37–#42 e resolver a integridade/ordem de integração sem merge cego.
3. Implementar auditor read-only de JSON e completar política de proveniência/memória.
4. Desenvolver effectome por baselines e ablações controladas.
5. Preservar COG-RETRIEVAL-004 e executar MTEB-BR no Colab.
6. Depois da revisão remota, preparar export controlado e validar Termux/Realme com backup e rollback.


### PR #43 — COG-ORGANIC-FABRIC-001: estado de revisão

- PR Draft: https://github.com/andersoncleyton032-ops/mahoraga-core/pull/43
- Branch `work/organic-cognitive-integration-20261117`, base na PR #42; checkpoint de código `85ee60225cb74d718264cf1ff891d2b7865273e3`.
- CI run 44098349087: job 134091401928 concluiu como failure antes de disponibilizar steps; a consulta de steps retornou lista vazia e o download de logs retornou `BlobNotFound`.
- Interpretação: falha de provisionamento/telemetria antes dos testes; não é evidência de regressão no código e não é aprovação.
- Estado: IMPLEMENTED / TESTS ADDED / CI NOT EXECUTED / REALME NOT VALIDATED.
- Nenhuma PR mesclada; main, Termux, Realme e SQLite local permanecem inalterados.


### Atualização final de checkpoint — PR #43 (17/11/2026)

- PR: https://github.com/andersoncleyton032-ops/mahoraga-core/pull/43 (Draft, empilhada sobre PR #42).
- Checkpoint de código/testes: `1ceb5dcd3a36558301fb612633be15841a39f739`.
- Reforços após a primeira revisão: payload dos sinais congelado recursivamente; handlers assíncronos rejeitados; fluxos só contabilizados após entrega; teste de sinal não entregue e teste de integração com exatamente oito entregas.
- Último run observado #44099051688 / job 134093801747, head anterior `df75bed2cc255cb8bdc4f611d0c4de15d8d1a12f`: falha antes de steps; logs `BlobNotFound`. O checkpoint atual ainda não retornou run associado.
- Estado permanece IMPLEMENTED / TESTS ADDED / CI UNVALIDATED / REALME NOT VALIDATED.


## COG-MEMORY-RETRIEVAL-BRIDGE-001 — memória associativa ligada ao conhecimento recuperado (2026-11-17)

| Capacidade | Artefato | Maturidade | Limite |
|---|---|---|---|
| Consultar chunk com hash e proveniência documental | `KnowledgeEngine.get_chunk()` | IMPLEMENTED / TESTS ADDED | Sem validação CI nesta branch |
| Ancorar episódio a chunk real por hash | `MemoryGraphEngine.record_chunk_anchor()` | IMPLEMENTED / TESTS ADDED | Gravação explícita, nunca automática |
| Expandir relações associativas de chunks recuperados | `expand_chunk_associations()` | IMPLEMENTED / TESTS ADDED | 1 salto; 20 âncoras; orçamento global até 50 eventos; janela 1000 |
| Passar associações ao contexto de geração | `CognitiveEngine.retrieve_knowledge()` / `IntegratedCore` | IMPLEMENTED / TESTS ADDED | Referências continuam não verificadas; ReasoningEngine não as promove a fatos |
| Preservar memória canônica | `KnowledgeStore.events` | IMPLEMENTED | Sem tabela/migração nova |

**Checkpoint:** `63e687a4a5f99b733dc9c813ec97daa2a7fe81f5`, PR #43 Draft. Testes adicionados, não executados; CI do checkpoint anterior falhou antes dos steps; Realme não validado.

### Lacunas importantes preservadas no mapa

- Memória: falta temporalidade de observação/evento, validade, conflito, supersessão e admissão condicionada à consulta.
- Linguagem: classificador ainda restrito; holdouts PT-BR/OOD, negação, ambiguidade e diálogo continuam necessários.
- Percepção: sensores têm amostragem pontual; câmera, microfone, reconhecimento de fala e TTS não estão implementados no núcleo.
- Effectome: apenas duração/estado transitórios; falta histórico persistente, recursos do dispositivo e ablações.
- Integração: branches #20/#21/#22/#33 têm conteúdo útil/duplicado a reconciliar; 51 branches e 33 PRs abertas.
- Implantação: nenhuma sincronização/alteração local; teste Realme permanece futuro, após CI e integração candidata.

## 9. Geração própria de imagens e renderização — 17/11/2026

| Capacidade | Maturidade | Limites |
|---|---|---|
| Síntese procedural IMG-0 | IMPLEMENTED / TESTS ADDED | PNG plasma determinístico via stdlib; CI não executada; Realme não validado |
| Path tracing CPU independente | PLANNED / pesquisa concluída | Cycles standalone experimental; OSPRay ARM64 não prova Android |
| Tiles/ROI/checkpoint | PLANNED | Estratégia especificada, sem execução |
| Filament PBR Android | RESEARCHED / PLANNED | Integração RMX5070 não testada; não é path tracer |
| Vulkan ray tracing | RESEARCHED / NOT VERIFIED | Exige feature discovery no aparelho |
| Geração neural local | RESEARCHED / PLANNED | MNN/QNN/ONNX/LiteRT candidatos; sem modelo/runtime validado |
| Integração cognitiva | PLANNED | LanguageEngine ainda não interpreta prompt visual aberto de modo validado |

IMG-0 está implementado na PR #43 (agent/image_generation.py), com testes adicionados e manifesto desabilitado; ainda não executado por CI. Próximo protótipo: IMG-1 path tracer CPU mínimo. Detalhes no dossiê, seção 20, e em docs/research/on-device-image-generation-rendering-20261117.md.


### Restrição específica do Realme 14 5G / Snapdragon 6 Gen 4

A ficha oficial da realme confirma Snapdragon 6 Gen 4, mas não identifica o modelo exato da GPU na página consultada. Uma base de dispositivos identifica o RMX5070/RE608EL1 como Adreno 810; a ficha técnica do Adreno 810 consultada lista Vulkan/OpenGL ES/OpenCL e informa ausência de ray tracing por hardware. Portanto, **não planejar Vulkan hardware ray tracing como backend do Realme**. Manter descoberta de features como diagnóstico, mas a expectativa operacional é CPU path tracing e Filament raster/PBR. A atribuição Adreno 810 deve ser confirmada por telemetria do próprio aparelho antes de ser tratada como fato do runtime. Fontes: https://www.realme.com/my/realme-14-5g/specs ; https://devcheck.app/devices/realme/re608el1 ; https://www.notebookcheck.net/Qualcomm-Adreno-810-Benchmarks-and-Specs.961237.0.html

## IMG-0 — geração procedural determinística (17/11/2026)

- Branch PR #43: work/organic-cognitive-integration-20261117.
- Checkpoint: b5b93fbd67f2e5d70d0bf3181ba8e531c2182e71.
- Arquivos: agent/image_generation.py, agent/integration_core.py, config/capability_manifest.json, tests/test_image_generation.py.
- Backend procedural plasma, PNG RGB, stdlib only; 1024 px por dimensão e 524.288 pixels por imagem; seed determinística; hash SHA-256; escrita atômica no ArtifactStore local.
- IntegratedCore expõe uma instância única; init não grava no disco. Geração é chamada explícita. Capability image.procedural_generate está disabled e sem runtime binding.
- Testes adicionados; não executados. CI #44113253617 refere-se ao checkpoint anterior f45539480f7a91676f064faa14c305dec5ec49d8 e falhou sem steps/logs; checkpoint IMG-0 não tem run confirmado.
- Não é path tracer, não é diffusion e não interpreta linguagem natural. Realme não validado.


## IMG-1 — path tracer CPU mínimo (17/11/2026)

| Capacidade | Componentes | Maturidade | Limitações |
|---|---|---|---|
| Path tracing CPU mínimo | agent/cpu_path_tracer.py, ImageGenerationEngine | IMPLEMENTED / TESTS_ADDED / LOCAL_SMOKE_ONLY | Esferas; Lambertiano/emissivo; até 128², 8 spp, depth 4; sem BVH, tiles, cancelamento, checkpoint ou validação Android |

A capacidade permanece enabled=false no manifesto e não está ligada ao Orchestrator. Smoke local não equivale à CI oficial nem à validação no Realme.


## IMG-MOBILE-PIPELINE-001 — integração visual Android

| Capacidade | Componentes | Maturidade | Próximo gate |
|---|---|---|---|
| APIs gráficas Android pesquisadas | Bitmap/ImageDecoder, Canvas, RenderEffect, RuntimeShader/AGSL | RESEARCHED / NOT_IMPLEMENTED | VIS-0 contrato de mídia |
| Visão móvel | OpenCV Android, ML Kit | CANDIDATES / NOT_INSTALLED | benchmark OCR/classificação/segmentação |
| Viewport 3D Android | Filament | CANDIDATE / NOT_INSTALLED | prova SurfaceView/TextureView |
| Vídeo | Media3 Transformer | FUTURE_CANDIDATE | especificar tarefa e pipeline |
| Host Android | Kotlin/Java | NOT_IMPLEMENTED | módulo mínimo read-only após validação core |

Nenhum APK, SDK, modelo ou runtime foi criado/instalado. Ver docs/architecture/MOBILE_VISUAL_PIPELINE.md.


### VIS-0 — identidade canônica de SceneSpec

SceneSpec v1 possui serialização canônica e SHA-256 expostos no resultado do path tracer. Estado: IMPLEMENTED / TESTS_ADDED / CI_NOT_EXECUTED. O contrato de ingestão de imagem/mídia Android e o host Kotlin/Java permanecem planejados.


## Reintegração documental de trilhas anteriores

| Frente | Origem | Conteúdo preservado na PR #43 | Estado de implementação |
|---|---|---|---|
| Poliglota | PR #20 | docs/architecture/POLYGLOT_MODULES.md | Diretriz documentada; nenhum toolchain extra instalado |
| Conectoma e cérebro | PR #29 | brain_connectome...md, seções 1–17 | Pesquisa/inspiração; sem simulador cerebral/SNN |
| Runtime Android | PR #33 | android-runtime-context-and-foreground-autonomy...md | Documento importado; implementação continua isolada e sem validação Realme |
| Cognição adaptativa | PR #32/#34 | adaptive-cognition...md; numeric progress no ramo | Código existente na cadeia; CI/Realme exigem gates próprios |

As cópias documentais não equivalem ao merge das branches originais. Ver docs/architecture/INTEGRATION_CONVERGENCE_PLAN.md.


## COG-GOAL-TRANSITION-REVIEW-001 — revisão contextual entre objetivos

| Capacidade | Implementação | Maturidade | Limites |
|---|---|---|---|
| Revisão read-only após mudança de objetivo | ExecutiveEngine.review_goal_transition() + MemoryGraphEngine.list_relations() | IMPLEMENTED / TESTS_ADDED / CI_NOT_EXECUTED | Um salto; snapshots limitados; até 100 relações no orçamento global; associações não verificadas; não altera estado ou dispara ações |

Não é executada automaticamente em transition_goal(). Requer relações explícitas e preexistentes.


### COG-ANDROID-RUNTIME-CONTEXT-001 — estado na PR #43 (17/11/2026)

| Capacidade | Componentes na linha orgânica | Maturidade | Limite |
|---|---|---|---|
| Leitura de tela/app/estado térmico | HardwareIntelligence.parse_runtime_context(), runtime_context() | IMPLEMENTED / TESTS_ADDED / CI_NOT_EXECUTED | Shizuku/rish read-only; reconhece com.termux; exige estado explicitamente parseável |
| Contexto opcional do Governor | AutonomyGovernor.evaluate_session(None) | IMPLEMENTED / TESTS_ADDED / CI_NOT_EXECUTED | Estado desconhecido pausa com budget zero; thermal unknown reduz budget se foreground/display estão confirmados |
| Interface pública | IntegratedCore.evaluate_autonomy_session(), plan_autonomous_work() | IMPLEMENTED / TESTS_ADDED / CI_NOT_EXECUTED | Nenhuma execução é iniciada pelo plano |

Realme/Termux não validado. O port é parcial e preserva os permits/atestados atuais; PR #33 permanece branch separada.


### COG-GOAL-TRANSITION-REVIEW-001 — maturidade atualizada

Teste com FakeMemoryGraph e teste de integração com MemoryGraphEngine real adicionados em tests/test_executive_engine.py. Estado: IMPLEMENTED / TESTS_ADDED / CI_NOT_EXECUTED / REALME_NOT_VALIDATED. A integração real ainda precisa passar por CI.

## COG-META-LOOP-001 — feedback metacognitivo da linguagem (17/11/2026)

| Capacidade | Artefato | Maturidade | Limite |
|---|---|---|---|
| Consultar calibração por tarefa e predictor_id no ciclo integrado | IntegratedCore._assess_language_calibration() + MetacognitiveMonitor.assess() | IMPLEMENTED / TESTS_ADDED | Advisory only; CI pendente; sem outcome feedback |
| Expor resultado no relatório de preparação | metacognitive_assessment + pipeline stage | IMPLEMENTED / TESTS_ADDED | Não altera decisão, não persiste e não autoriza execução |

A integração reutiliza os módulos existentes. Não cria learner, banco ou scheduler novo. Se confidence/predictor_id não estiverem disponíveis, o estágio retorna not_assessable. Se a calibração não tiver amostra suficiente, a recomendação continua consultiva e a decisão original da linguagem é preservada.

**Próxima lacuna:** correlacionar a previsão do classificador com o outcome verificado posteriormente, mantendo escopo por tarefa/modelo/contexto e evidência independente. Só depois avaliar seleção adaptativa de estratégias. Estado atual: CI_NOT_EXECUTED / REALME_NOT_VALIDATED.


### METACOGNITION-SCOPE-001 — verificação de evidência após filtragem (17/11/2026)

- Problema: report() verificava a proveniência de cada episódio antes de conhecer o escopo solicitado, inclusive quando assess() consultava um par exato tarefa/preditor.
- Refinamento: validar metadados e filtrar tarefa/preditor antes do verificador; contabilizar verificações, exclusões por escopo e episódios não verificados dentro do escopo.
- Efeito esperado: menos chamadas de verificação para relatórios específicos, sem alterar quais episódios elegíveis podem entrar nas métricas.
- Limite mantido: leitura ainda examina no máximo os últimos 1000 eventos do tipo; cobertura antiga pode ser truncada.
- Estado: código atualizado / teste adicionado / execução pendente / CI pendente / Realme não validado.


### Refinamento adicional — status metacognitivo sem varredura (17/11/2026)

- Identificada chamada indireta: IntegratedCore.prepare_request() executava report(limit=100) para montar o contexto; CognitiveEngine.status() e Introspection.build_self_model() também chamavam status(), que por sua vez executava report(limit=500).
- status() agora usa apenas a contagem SQL de episódios e informa not_assessed; não calcula métricas nem verifica recibos.
- IntegratedCore usa o snapshot leve; a avaliação detalhada permanece explícita em assess_confidence()/report() com escopo exato.
- Teste adicionado para provar que status() não chama o verificador de evidência.
- Estado: implementação e testes adicionados / execução pendente / CI pendente / Realme não validado.


## VIS-SCENE-CONTRACT-001 — consolidação SceneSpec v1 e validação de fronteira (17/11/2026)

A trilha visual #44 foi reconciliada conceitualmente com a branch cognitiva #43, sem mesclar branches. A versão v0.2 do path tracer amplia o backend Python existente para triângulos e luzes pontuais. Antes da integração, foram corrigidos contratos ausentes na implementação paralela: serialização canônica `SceneSpec.to_dict()`, identidade `SceneSpec.sha256()`, validação direta de `TriangleSpec`, `PointLightSpec` e `SceneSpec`, e um identificador de schema canônico com aceitação do alias legado `mahoraga.scene.v1`. O manifesto também passa a refletir o limite procedural real de 524.288 pixels. Estado: código/testes/documentação adicionados; execução CI e Realme pendentes.


### Validação da integração visual SceneSpec v1

PR #47 possui testes adicionados para geometria, luzes, limites, determinismo, serialização/hash e round-trip. A CI #44151110434 falhou sem steps/logs recuperáveis (BlobNotFound), sem artifacts; não há evidência de que os testes tenham iniciado. A capacidade continua IMPLEMENTED / TESTS_ADDED_NOT_EXECUTED / REALME_NOT_VALIDATED.


## COG-CHECKPOINT-PREFLIGHT-001 — Pré-validação de checkpoints neurais (2026-11-17)

| Capacidade | Componentes | Maturidade | Limite |
|---|---|---|---|
| Pré-validar NPZ/NPY antes de materializar arrays | `checkpoint_safety.py`, `neural_checkpoint.py`, `neural_core.py` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Limites locais de 64 MiB comprimidos, 128 MiB descomprimidos e 64 KiB de metadados; não autentica a origem do artefato |
| Rejeitar membros ZIP inesperados/duplicados e schemas inconsistentes | Mesmo caminho | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Hash sem assinatura autentica integridade acidental, não identidade do produtor |
| Preservar estado em falha de carregamento | NeuralCore + Adam | TESTS ADDED; CI UNVALIDATED | Validação no Termux/Realme ainda não realizada |

A correção é empilhada sobre `work/adaptive-learning-history-completeness-20261117`. Nenhum checkpoint local foi lido, substituído ou migrado. A pré-validação limita consumo de recursos, mas não substitui assinatura/verificação de proveniência confiável.


## COG-CHECKPOINT-RESTORE-CONSISTENCY-001 — Consistência entre gravação e restauração (2026-11-17)

| Correção | Componente | Maturidade | Limites |
|---|---|---|---|
| Mesmo contrato de tamanho no salvamento e na restauração | `neural_checkpoint.py`, `neural_core.py` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Arquivo temporário é recusado antes de substituir destino; sem teste Realme |
| Validação do estado Adam ao salvar | `save_training_checkpoint()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Validação dos valores do estado/hiperparâmetros; não prova origem do estado |
| Checkpoint corrompido no LanguageEngine vira estado indisponível controlado | `language_engine.py` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Não faz recuperação automática de checkpoint alternativo |

A revisão também corrigiu um fixture de NPY truncado que continha caracteres literais em vez da assinatura binária real.


## COG-CHECKPOINT-CONTRACT-EDGE-001 — Casos de borda do contrato de checkpoint (2026-11-17)

| Caso | Componente | Maturidade | Limite |
|---|---|---|---|
| Rejeitar NaN/Inf no salvamento da rede simples | `Sequential.save_checkpoint()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Não autentica origem dos pesos |
| Round-trip de rede sem parâmetros treináveis | `checkpoint_safety.py`, `Sequential` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Só valida serialização estrutural |


## COG-CHECKPOINT-PATH-INTEGRITY-001 — Integridade do caminho de checkpoint (2026-11-17)

| Capacidade | Componente | Maturidade | Limite |
|---|---|---|---|
| Rejeitar symlink/FIFO/dispositivo antes da leitura | `checkpoint_safety.open_checkpoint_file()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Protege o componente final do caminho; não é sandbox do sistema de arquivos |
| Confirmar identidade do descritor aberto | `lstat + open(O_NOFOLLOW) + fstat` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Dependente dos flags disponíveis na plataforma |

O carregador só prossegue para ZIP/NPY depois de abrir um arquivo regular e confirmar que o descritor corresponde ao objeto observado antes da abertura.


## COG-CHECKPOINT-PARSER-BOUNDS-001 — Limites de recursão dos parsers (2026-11-17)

| Componente | Caso tratado | Maturidade | Limite |
|---|---|---|---|
| `checkpoint_safety.py` | JSON/NPY profundamente aninhado | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Não limita o consumo de todo o processo contra falhas de memória do runtime |

Recursão excessiva nos metadados não pode escapar da camada de recuperação como exceção inesperada; é normalizada para checkpoint inválido.


## COG-ADAM-STATE-CHECKPOINT-001 — Integridade do estado do otimizador (2026-11-17)

| Capacidade | Componente | Maturidade | Limite |
|---|---|---|---|
| Rejeitar momento Adam ausente ou campo extra | `save_training_checkpoint()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Estado incompleto não é reparado automaticamente |
| Rejeitar estado ligado a parâmetro desconhecido | Mesmo componente | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Exige que o estado persistido pertença à instância/rede usada no salvamento |
| Preservar destino pré-existente quando preflight falha | Writers NPZ | TESTS ADDED; CI UNVALIDATED | Durabilidade após falha abrupta ainda depende da sincronização de diretório e filesystem |

A restauração de treinamento não deve substituir momentos Adam ausentes por zeros nem descartar entradas de estado sem erro explícito.


## COG-ADAM-STATE-TEMPORAL-001 — Coerência temporal do Adam

| Caso | Componente | Maturidade | Limite |
|---|---|---|---|
| Nenhum momento antes do primeiro passo | `save_training_checkpoint()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Presume semântica atual de Adam com inicialização de estado no primeiro step |
| Todos os parâmetros com momentos após passos executados | Mesmo componente | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Mudança dinâmica de arquitetura exige estado de otimizador novo |

O estado do otimizador precisa ser temporalmente coerente: contador zero + nenhum momento, ou contador positivo + momentos completos para os parâmetros atuais.


## COG-CHECKPOINT-ZIP-DIRECTORY-001 — Pré-validação da estrutura ZIP

| Capacidade | Componente | Maturidade | Limites |
|---|---|---|---|
| Contagem EOCD antes de criar objetos de membros ZIP | `checkpoint_safety.py` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Rejeita ZIP64/multidisco; até 20.000 membros esperados |
| Limite de diretório central antes do parser | Mesmo componente | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | 8 MiB absoluto e orçamento proporcional aos nomes esperados |

A estrutura externa de ZIP é rejeitada antes da materialização de objetos para diretórios com contagem incompatível ou tamanho desproporcional.


## COG-LANGUAGE-SEED-INTEGRITY-001 — Identidade da seed de treinamento

| Capacidade | Componente | Maturidade | Limite |
|---|---|---|---|
| Persistir e validar a seed usada para treinar os pesos | `LanguageEngine` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Checkpoints antigos sem seed são preservados, mas não carregados |
| Rejeitar seed inválida antes de treinar | `LanguageEngine.__init__` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Aceita inteiros não negativos, inclusive tipos NumPy inteiros |

A seed registrada passa a fazer parte do contrato do checkpoint. O `predictor_id` não pode ser recalculado com uma seed declarada diferente da usada no treinamento.


## COG-ENGINEERING-RECOVERY-001 — Recuperação explícita de transações

| Capacidade | Componente | Maturidade | Limite |
|---|---|---|---|
| Inventariar diários e estados sem alterar o projeto | `EngineeringWorkbenchV2.list_transactions()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Não recupera automaticamente |
| Recuperar uma transação por ID com aprovação explícita | `recover_transaction()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Conflitos externos ou backup inválido exigem inspeção manual |
| Reconciliar manifesto após commit interrompido | `_reconcile_committed_stage()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Não reescreve arquivos fonte |
| Serializar promoção/recuperação interprocesso | `_transaction_lock()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Requer flock POSIX; falha fechada fora desse suporte |
| Reduzir exposição durante validação | Runner V2 | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Não é sandbox: filesystem/rede continuam acessíveis sob a mesma identidade |

A V2 permanece experimental e isolada. O inventário é read-only; rollback exige selecionar uma transação e aprovar a recuperação. Cópias temporárias não devem ser descritas como sandbox de segurança.


## COG-ENGINEERING-RUNNER-BOUNDS-001 — Limites do executor de validação

| Capacidade | Componente | Maturidade | Limites |
|---|---|---|---|
| Buffer de saída limitado por canal | `_run_one_validation_command()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | 64 KiB por stdout/stderr |
| Encerrar grupo no timeout POSIX | Mesmo componente | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Não é isolamento de filesystem/rede |
| Entrada JSON do staging limitada | `stage_json()`, `_load_stage()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Limite de 1 MiB |

A V2 só executa testes staged com confiança explícita no código. A execução continua com a mesma identidade do processo, então não se trata de uma fronteira de sandbox.


## COG-ENGINEERING-DURABILITY-002 — Durabilidade e concorrência

| Capacidade | Componente | Maturidade | Limites |
|---|---|---|---|
| Lock interprocesso entre operações de promoção/recuperação | `_transaction_lock()` | TESTS ADDED; CI UNVALIDATED | Teste usa POSIX fork/flock; outras plataformas falham fechadas |
| Sincronização de dados e diretórios | `_fsync_file()`, `_fsync_directory()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Filesystem precisa suportar fsync de diretório |
| Reconciliar commit sem confiar apenas no journal | `_reconcile_committed_stage()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Exige staging íntegro; não restaura staging adulterado |
| Promoção completa explicitamente confiada | `promote_staged()` | TESTS ADDED; CI UNVALIDATED | Execução continua sem isolamento de filesystem/rede |

A recuperação após crash verifica journal, manifesto de backup, snapshots anteriores e payload staged; divergências são bloqueadas sem sobrescrever alterações externas.


## COG-ENGINEERING-FILE-BOUNDARY-001 — Fronteira de arquivos da V2

| Capacidade | Componente | Maturidade | Limites |
|---|---|---|---|
| Leitura JSON com no-follow e orçamento de bytes | `_read_json_limited()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Protege arquivo final; diretórios ancestrais ainda dependem de verificação de symlink |
| Cópia/hash/fsync por descritores regulares | `_verified_copy()`, `_sha256_file()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Não é uma sandbox do sistema de arquivos |
| Rejeitar symlink no projeto copiado | `_copy_project()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Pode recusar repositórios que adotem symlinks intencionalmente |


## COG-ENGINEERING-STAGING-SNAPSHOT-001 — Snapshot staged verificável

| Capacidade | Componente | Maturidade | Limite |
|---|---|---|---|
| Validar manifesto, hashes, tamanho e contagem em uma leitura | `EngineeringWorkbenchV2._load_stage()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Continua exigindo exclusão contra concorrência durante staging |
| Copiar snapshot sem dereferenciar symlinks | `_copy_project()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Repositórios com symlinks intencionais serão recusados |
| Preservar metadados usando descritor aberto | `_verified_copy()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Permissões e ownership de diretório não são reproduzidos integralmente |


## COG-ENGINEERING-INODE-BOUNDARY-001 — Identidade do objeto aberto

| Capacidade | Componente | Maturidade | Limites |
|---|---|---|---|
| Comparar inode entre inspeção e abertura | `_open_regular_file()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Componente final do caminho; diretórios ancestrais ainda dependem de política e permissões |
| Verificar hash/tamanho no mesmo descritor | `_load_stage()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Arquivos podem ser substituídos por atores privilegiados fora do processo |
| Cópia para destino não-symlink e verificado | `_verified_copy()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Não fornece isolamento contra processos com a mesma identidade |



## COG-ENGINEERING-DURABLE-TREE-001 — Durabilidade da árvore de arquivos

| Capacidade | Componente | Maturidade | Limite |
|---|---|---|---|
| Sincronizar diretórios ancestrais de novas entradas | `_fsync_directory_chain()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Filesystem deve suportar fsync em diretórios |
| Rejeitar task_id com tipo não-string no diário | `_load_transaction_journal()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Mantém estrito o schema de recuperação |
| Reconciliar commit somente com staging integralmente válido | `_reconcile_committed_stage()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Staging perdido/adulterado requer intervenção; não apaga evidências |


## COG-ENGINEERING-FINAL-SNAPSHOT-001 — Validação final fora da árvore ativa

| Capacidade | Componente | Maturidade | Limite |
|---|---|---|---|
| Executar suite final em cópia do estado já aplicado | `_run_validation_on_project_snapshot()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Cópia descartável não isola filesystem/rede |
| Não usar a raiz ativa como diretório de execução dos testes | `promote_staged()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Código confiado ainda roda sob a mesma identidade do processo |
| Distinguir aprovação caller-supplied de atestado verificável | Contrato da V2 | DOCUMENTED LIMITATION | Não existe token humano one-shot nessa API experimental |

A V2 continua desligada da composição operacional. Promoção exige confiança explícita, aprovação declarada e validação em snapshot descartável; isso ainda não substitui sandbox real nem aprovação criptograficamente verificável.


## COG-ENGINEERING-RESOURCE-BOUNDS-001 — Orçamento de cópia e backup

| Recurso | Limite | Maturidade | Limitação |
|---|---:|---|---|
| Backup por arquivo | 16 MiB | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Arquivos maiores exigem estratégia explícita diferente |
| Backup por transação | 128 MiB | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Dados antigos não são apagados automaticamente |
| Arquivo por snapshot de validação | 64 MiB | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Arquivos runtime e privados são excluídos |
| Snapshot completo | 256 MiB / 20.000 arquivos | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Snapshot acima do orçamento é recusado sem truncar silenciosamente |

A cópia de validação passa a ser limitada e não incorpora modelos, bancos ou diretórios runtime privados por padrão.


## COG-ENGINEERING-API-RESTORATION-001 — Integridade da API transacional experimental

| Capacidade | Componente | Maturidade | Limite |
|---|---|---|---|
| Validação staged com trust opt-in | `validate_staged()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Sem trust, apenas compileall; não passa a suíte |
| Criar journal/backup e aplicar transação | `_create_transaction()`, `_apply_transaction_file()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | V2 não conectada à composição principal |
| Listar transações e backups órfãos | `list_transactions()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Backup sem journal exige revisão manual |
| Recuperar rollback/reconciliar commit | `recover_transaction()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Conflitos externos/backup danificado bloqueiam recuperação automática |
| Copiar com limite durante a leitura, temporário validado e promoção atômica | `_verified_copy()` | IMPLEMENTED / TESTS ADDED; CI PENDING | Hardlink do destino existente precisa ser suportado; escrita concorrente externa ainda exige coordenação |

A V2 permanece experimental e desligada do IntegrationCore; esta rodada recuperou métodos que haviam sido removidos acidentalmente e adicionou testes de contrato para evitar regressão de API.


## COG-ENGINEERING-RECOVERY-EDGE-001 — Destinos e cópias temporárias

| Capacidade | Componente | Maturidade | Limite |
|---|---|---|---|
| Sincronizar cópia em snapshot fora da raiz do projeto | `_fsync_copy_parent()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Diretórios precisam permitir fsync |
| Bloquear rollback quando destino vira diretório/FIFO/symlink | Preparação e execução do rollback | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Exige revisão manual do conflito |
| Listar backup órfão sem journal | `list_transactions()` | IMPLEMENTED / TESTS ADDED; CI UNVALIDATED | Não tenta reconstruir transação sem journal |


## COG-ENGINEERING-ATOMIC-COPY-001 — Cópia limitada e promoção preservando o destino

| Capacidade | Componente | Maturidade | Limite |
|---|---|---|---|
| Impor limite durante a leitura mesmo se a fonte crescer após o stat inicial | `_verified_copy(max_bytes=...)` | IMPLEMENTED / TESTS ADDED; CI PENDING | A fonte também precisa permanecer estável durante a operação |
| Escrever em temporário no mesmo diretório e validar hash/tamanho por leitura de retorno | `_verified_copy()` | IMPLEMENTED / TESTS ADDED; CI PENDING | Exige espaço temporário suficiente no mesmo filesystem |
| Preservar destino existente com hardlink de rollback antes do replace atômico | `_verified_copy()` | IMPLEMENTED / TESTS ADDED; CI PENDING | Hardlink indisponível implica falha segura antes da substituição |
| Criar destino ausente sem sobrescrever arquivo que apareça concorrentemente | `link(temp, destination)` | IMPLEMENTED / TESTS ADDED; CI PENDING | Filesystem precisa oferecer hardlinks |
| Reverter substituição quando falha a sincronização posterior do diretório | `_verified_copy()` | IMPLEMENTED / TESTS ADDED; CI PENDING | Não elimina a janela de corrida com escritores externos não cooperativos |

A cópia agora recebe limites específicos por contexto: snapshots de validação (64 MiB), backups (16 MiB) e arquivos staged (250.000 bytes). O limite também é aplicado no laço de leitura, não apenas por inspeção prévia do tamanho. Nenhuma alteração em Termux ou no dispositivo foi realizada.


### COG-ENGINEERING-ATOMIC-COPY-002 — Corridas no limite de substituição

| Capacidade | Componente | Maturidade | Limite |
|---|---|---|---|
| Revalidar metadados do inode original protegido imediatamente antes da troca | `_verified_copy()` | IMPLEMENTED / TESTS ADDED; CI PENDING | Não fornece CAS portátil contra escritores externos no último intervalo do rename |
| Recusar criação concorrente de destino sem sobrescrita | Hardlink temporário → destino | IMPLEMENTED / TESTS ADDED; CI PENDING | Depende de hardlink no filesystem |
| Revalidar estabilidade da fonte após a leitura de retorno do temporário | `_verified_copy()` | IMPLEMENTED / TESTS ADDED; CI PENDING | Não bloqueia modificações feitas após concluir a cópia |


### COG-MEMORY-RETRIEVAL-BULK-001 — Remoção de N+1 na expansão associativa

| Capacidade | Componente | Maturidade | Limite |
|---|---|---|---|
| Resolver IDs de eventos em lotes com snapshot SQLite estável | `KnowledgeStore.get_events()` | IMPLEMENTED / TESTS ADDED; CI PENDING | Até 3.000 IDs, consultas de 500 por lote |
| Evitar consultas individuais por relação, âncora e vizinho na expansão | `MemoryGraphEngine.expand_chunk_associations()` | IMPLEMENTED / TESTS ADDED; CI PENDING | Janela permanece em 1.000 relações/âncoras e 50 vizinhos; um salto |
| Preservar estado epistemológico e leitura sem escrita persistente | MemoryGraph | IMPLEMENTED / TESTS ADDED; CI PENDING | Relações permanecem candidatas não verificadas |


### COG-FABRIC-CONCURRENCY-001 — Contadores do conectoma sob concorrência

| Capacidade | Componente | Maturidade | Limite |
|---|---|---|---|
| Sincronizar atualização dos fluxos observados sem serializar handlers | `CognitiveFabric.publish()` | IMPLEMENTED / TESTS ADDED; CI PENDING | Registro de handlers/configuração permanece fase de inicialização |
| Criar snapshot consistente durante publicações concorrentes | `connectome_snapshot()` | IMPLEMENTED / TESTS ADDED; CI PENDING | Snapshot captura uma cópia do contador, não uma transação global dos ciclos |


### COG-ENGINEERING-RECOVERY-RACE-001 — Revalidação após espera e cópia

| Capacidade | Componente | Maturidade | Limite |
|---|---|---|---|
| Confirmar que o caminho do lock ainda nomeia o inode bloqueado após obter flock | _transaction_lock() | IMPLEMENTED / TESTS ADDED; CI PENDING | Exige filesystem POSIX e lock cooperativo |
| Revalidar destino após construir temporário de promoção | _apply_transaction_file() | IMPLEMENTED / TESTS ADDED; CI PENDING | Janela mínima de rename não é CAS portátil |
| Revalidar destino após cópia de backup antes do rollback | _restore_transaction() | IMPLEMENTED / TESTS ADDED; CI PENDING | Conflito mantém recovery_required |

## Atualização de direção — competências transversais e conhecimento cumulativo (2026-11-17)

**Nota temporal:** este bloco descreve o estado observado em 17/11; as implementações registradas nas seções posteriores atualizam a situação técnica.

Foi realizada auditoria transversal da linha de desenvolvimento disponível nesta branch, com foco em linguagem, aprendizagem, memória, recuperação e raciocínio. A especificação completa está em [docs/architecture/COMPETENCY_AND_CUMULATIVE_LEARNING.md](architecture/COMPETENCY_AND_CUMULATIVE_LEARNING.md).

- **Linguagem:** o LanguageEngine continua sendo um classificador operacional de escopo restrito; não equivale a compreensão geral do português. Ampliar intenções sem benchmark pode aumentar falsos acionamentos.
- **Conhecimento cumulativo:** Store, AdaptiveLearning e MemoryGraph oferecem persistência episódica, revisão e associações candidatas. Promoção semântica verificável depende de providers confiáveis ainda não configurados em produção; episódios e documentos preparados não equivalem a aprendizagem neural.
- **Recuperação:** BM25 permanece como baseline lexical; embeddings/RRF operacionais dependem de benchmark e encoder integrado.
- **Lógica e matemática:** ReasoningEngine usa fatos/regras textuais explícitos. Não foi identificada uma competência geral de álgebra com AST, aritmética exata e verificação de soluções.
- **Filosofia e ciência:** devem ser tratadas como competências estruturadas sobre o mesmo núcleo de memória, raciocínio e evidência, sem criar bancos ou executivos paralelos.

**Estado desta auditoria na data do registro:** AUDIT / ARCHITECTURE SPECIFIED. Nenhuma competência matemática, filosófica ou linguística geral havia sido implementada naquele checkpoint. As seções subsequentes deste mapa registram as mudanças posteriores. CI permanece inconclusiva devido à falha pré-step; nenhuma validação no Termux/Realme ocorreu.


## Atualização de proveniência linguística — LANG-PROV-001 (2026-11-17)

| Capacidade | Componente | Maturidade | Limites |
|---|---|---|---|
| Linhagem individual de exemplos de intenção | `LanguageEngine` | IMPLEMENTED / TESTS ADDED | SHA-256 vincula cada par texto/intenção a rótulos de origem declarados; rótulos são caller-supplied e não autenticados |
| Proveniência de conjuntos legados | `LanguageEngine._load_examples()` | IMPLEMENTED / TESTS ADDED | Arquivos antigos não são reescritos automaticamente; origem permanece `legacy_source_unknown` |
| Integridade do checkpoint versus proveniência | `LanguageEngine` metadata | IMPLEMENTED / TESTS ADDED | Mudança na proveniência invalida checkpoint; CI atual não executou steps recuperáveis |

A amostra de treinamento continua sendo deduplicada por texto/intenção. Adicionar a mesma amostra a partir de outra etiqueta de origem registra linhagem adicional sem aumentar a quantidade de exemplos treinados. A proveniência não autentica fontes e não valida a correção do conteúdo. Checkpoints antigos sem fingerprint do bloco de proveniência permanecem no disco, mas não são carregados por este contrato. Nenhum provider confiável foi criado ou ligado.


## Atualização de proveniência do raciocínio simbólico — REASON-PROV-001 (2026-11-17)

| Capacidade | Componente | Maturidade | Limites |
|---|---|---|---|
| Preservação de relatos sobre fatos duplicados | `ReasoningEngine` | IMPLEMENTED / TESTS ADDED | Relatos não sobrescrevem silenciosamente origens anteriores; confiança agregada pelo menor valor declarado |
| Trilha de premissas em conclusões derivadas | `ReasoningEngine` | IMPLEMENTED / TESTS ADDED | Preserva fontes declaradas e confiança das premissas; identidade das fontes não é autenticada |
| Validação numérica de confiança | `ReasoningEngine` | IMPLEMENTED / TESTS ADDED | Rejeita NaN, infinito e inteiros que não podem ser convertidos em float |

Relatos repetidos não elevam confiança e não são considerados evidências independentes. A lista de origens é caller-supplied; não comprova identidades nem independência entre fontes. Conclusões derivadas registram as premissas e sua proveniência declarada. CI permanece sem execução de steps recuperáveis; nenhuma validação no Realme foi feita.


## Nota histórica de maturidade do HEAD — 2026-11-17

As métricas históricas de holdout e CI documentadas acima pertencem às revisões em que foram executadas. As alterações recentes de proveniência do LanguageEngine e do ReasoningEngine têm testes adicionados, mas o HEAD atual ainda não possui execução CI recuperável: o job `test (3.12)` encerrou com `steps: null`, e o download dos logs retornou `BlobNotFound`. Portanto, as versões atuais desses componentes permanecem IMPLEMENTED / TESTS ADDED, não TESTED_INTEGRATION. Nenhuma validação no Termux/Realme foi realizada.


## Primeira competência matemática determinística — MATH-CORE-001 (2026-11-18)

| Capacidade | Componente | Maturidade | Limites |
|---|---|---|---|
| Avaliação aritmética exata | `MathematicsEngine` | IMPLEMENTED / TESTS ADDED | AST por whitelist; inteiros e frações; sem execução de código; CI pendente |
| Solução de equações lineares | `MathematicsEngine` | IMPLEMENTED / TESTS ADDED | Uma variável; redução afim e verificação por substituição; não linearidade rejeitada |
| Integração cognitiva | `CognitiveEngine`, `IntegratedCore` | IMPLEMENTED / TESTS ADDED | Usa Dharma `local_compute`; não grava memória automaticamente |
| Eficiência/dependências | biblioteca padrão Python | IMPLEMENTED / NOT MEASURED ON DEVICE | Sem SymPy/NumPy adicionais; limites internos protegem expressão e tamanho de inteiros |

A capacidade aceita `+`, `-`, `*`, `/` e potência com expoente inteiro constante limitado. Decimais são convertidos diretamente do token para fração exata (por exemplo, `0.1 + 0.2 = 3/10`). O solver distingue nenhuma solução, infinitas soluções e solução única verificada. Multiplicação implícita, funções, cálculo, matrizes, unidades, álgebra não linear e interpretação de problemas escritos em linguagem natural permanecem fora do escopo.

**Validação operacional da CI:** os jobs recentes da PR #53 iniciam e terminam sem runner alocado (`runner_id=0`, sem nome e sem steps). Isso é evidência de falha pré-execução do serviço de Actions, não uma falha de teste. Não atribuir maturidade TESTED_INTEGRATION à implementação matemática até CI executada com steps reais. Nenhuma validação no Termux/Realme foi feita.


## Atualização de segurança do parser matemático — MATH-INPUT-BOUND-001 (2026-11-18)

O parser agora verifica o tamanho bruto recebido antes de remover espaços externos, tanto para expressões quanto para equações. Isso evita que entradas compostas por grandes volumes de whitespace ultrapassem o orçamento apenas porque seriam curtas após normalização. Testes específicos foram adicionados; CI ainda não iniciou steps e o limite não foi validado no dispositivo.


## Extensão dos sistemas lineares e limites numéricos — MATH-SYSTEM-001 (2026-11-18)

| Capacidade | Componente | Maturidade | Limites |
|---|---|---|---|
| Sistemas lineares racionais | `MathematicsEngine.solve_linear_system()` | IMPLEMENTED / TESTS ADDED | Gauss-Jordan exato; até 12 equações/8 variáveis; CI pendente |
| Classificação de sistema | `MathematicsEngine` | IMPLEMENTED / TESTS ADDED | Solução única, nenhuma solução ou subdeterminado; variáveis livres explícitas |
| Verificação | `MathematicsEngine` | IMPLEMENTED / TESTS ADDED | Cada equação é substituída após solução única |
| Proteção de tamanho numérico | `MathematicsEngine._coerce_number()` | IMPLEMENTED / TESTS ADDED | Limites aplicados antes da conversão de int/Decimal em Fraction |

A chamada pública integrada é `CognitiveEngine.solve_linear_system()`, protegida pela decisão Dharma `local_compute`. Sistemas não lineares e restrições de domínio especiais são recusados, não aproximados. O solver permanece determinístico e sem dependências externas. CI e validação no Realme ainda não foram realizadas.


## Validação independente de CI hospedada — VALIDATION-ORCHESTRATOR-001 (2026-11-18)

| Capacidade | Estado | Evidência/limite |
|---|---|---|
| Orquestrador único CI/Termux | IMPLEMENTED / TESTS ADDED | `scripts/validate_project.py`; execução pendente |
| Relatório reprodutível | IMPLEMENTED / TESTS ADDED | commit, ambiente, hashes das fixtures, duração, códigos de saída e logs limitados |
| Timeouts por etapa | IMPLEMENTED / TESTS ADDED | perfis `ci` e `device`, execução sequencial |
| Artefato JUnit | IMPLEMENTED / TESTS ADDED | gerado pela etapa pytest |
| Independência do GitHub Actions | IMPLEMENTED / EXECUTION PENDING | mesmo script pode ser executado no Termux; ainda não testado no Realme |

A CI hospedada passa a chamar o mesmo orquestrador que o script Termux. Próxima validação: runner alocado com steps reais; alternativamente, execução local controlada no checkout sincronizado. Não confundir falha pré-runner com falha de teste.


## Arquitetura multidisciplinar e percepção — DOMAIN-COMPETENCY-001 (2026-11-18)

Foi especificado um framework de competências multidisciplinares sem criar agentes ou bancos isolados. O documento docs/architecture/DOMAIN_COMPETENCY_FRAMEWORK.md organiza bases compartilhadas (linguagem, lógica, matemática, computação, física, epistemologia e método científico), domínios aplicados (anatomia humana, anatomia comparada, criação responsável, animação/3D/biomecânica) e modalidades de percepção (texto, imagem, áudio, vídeo, sensores e estruturas 3D).

**Estado real:** especificação arquitetural; os motores especializados de anatomia, genética, animação e visão ainda não foram implementados. O PerceptionEngine existente amostra sensores; o LocalModelAdapter atual é textual e loopback-only. PocketPal é considerado laboratório/provedor opcional, nunca dependência obrigatória. O detalhamento de pré-requisitos, proveniência, segurança, avaliação e ordem de implementação está no documento de arquitetura.


### Verificação matemática baseada em propriedades — MATH-PROPERTY-001 (2026-11-18)

Adicionados 60 casos gerados com soluções racionais independentes e 40 sistemas submetidos a transformações metamórficas (permutação e escala não nula das equações). Estado: IMPLEMENTED / TESTS ADDED / EXECUTION PENDING. Não confundir com fuzzing irrestrito ou prova formal.


### Workbench conectado ao orquestrador único — ENGINEERING-VALIDATION-BRIDGE-001 (2026-11-18)

O EngineeringWorkbench agora delega a validação de projetos completos a scripts/validate_project.py e exige relatório final completed/passed antes de considerar a preparação validada. O fallback reduzido existe somente para fixtures de teste mínimas sem o script ou durante a própria suíte pytest, para evitar recursão. Estado: IMPLEMENTED / TESTS ADDED / EXECUTION PENDING.


### EngineeringWorkbenchV2 conectado ao pipeline unificado — ENGINEERING-VALIDATION-BRIDGE-002 (2026-11-18)

A versão transacional V2 também usa scripts/validate_project.py quando a execução confiável do código staged é explicitamente autorizada. O resultado só passa se o processo terminar sem timeout, o relatório estiver completo, compile e pytest estiverem aprovados. O runner continua executando no mesmo usuário do sistema e não é sandbox de segurança; essa limitação permanece declarada. Estado: IMPLEMENTED / TESTS ADDED / EXECUTION PENDING.


### Gates quantitativos de linguagem — LANG-EVAL-GATES-001 (2026-11-18)

A regressão linguística deixa de aprovar apenas porque o modelo temporário foi treinado. O pipeline agora exige acurácia >=95%, precisão >=95%, recall >=80%, não execução segura >=95%, zero falsos positivos e zero vazamento futuro/condicional em cada holdout v1/v2/v3. Os valores e resultados de cada gate são registrados. Limites ancorados nos resultados históricos dos fixtures; não demonstram linguagem aberta. Estado: IMPLEMENTED / TESTS ADDED / EXECUTION PENDING.

## Análise topológica de memória e conectoma operacional — CONNECTOME-GRAPH-001 (2026-11-19)

| Capacidade | Componente | Maturidade | Limites/evidência |
|---|---|---|---|
| Caminhos simples limitados | agent/graph_algorithms.py | IMPLEMENTED / TESTS ADDED / EXECUTION PENDING | BFS determinística sem dependências; caps explícitos de saltos, caminhos e visitas |
| Rastreamento de relações episódicas | MemoryGraphEngine.trace_paths() | IMPLEMENTED / TESTS ADDED / EXECUTION PENDING | Exposto também por CognitiveEngine; apenas arestas candidate_unverified; até 6 saltos, 20 caminhos, 5.000 visitas; read-only |
| Métricas do conectoma operacional | CognitiveFabric.analyze_connectome() | IMPLEMENTED / TESTS ADDED / EXECUTION PENDING | Exposto por IntegratedCore; grau, fontes/destinos, isolados, reciprocidade e caminhos; estrutura verificada separada de fluxos entregues |
| Conectividade neural esparsa/BPU | Pesquisa externa | RESEARCHED / NOT INTEGRATED | BPU sem código oficial reproduzível localizado; AxonWeave não aprovado como dependência do Realme |

O estudo dos conectomas FlyWire e larval e dos projetos Connectome Interpreter/AxonWeave inspirou métodos de análise topológica, não a cópia de uma arquitetura biológica. O novo caminho de memória explica cadeias de relações candidatas, sem convertê-las em fatos; o analisador do fabric separa dependências estruturais de entregas observadas e não demonstra causalidade. Nenhuma matriz neural ou dataset biológico foi instalado.

Relatório de pesquisa, fontes, decisão de licença, limites e protocolo de validação: docs/research/CONNECTOME_REUSE_AND_GRAPH_ANALYSIS_20261119.md.

**Pendência:** testes adicionados, mas CI hospedada e execução no Termux/Realme ainda não validadas. Não promover para main antes da cadeia CI e da revisão da PR #54.

## Endurecimento do validador para Termux — VALIDATION-RAM-001 (2026-11-19)

| Capacidade | Componente | Maturidade | Limites/evidência |
|---|---|---|---|
| Captura de stdout/stderr com RAM limitada | `scripts/validate_project.py` | IMPLEMENTED / TESTS ADDED / MICROTESTS EXECUTED | Drenagem concorrente, ring buffer de até 64 KiB por canal, relatório com cauda limitada |
| Timeout com encerramento do grupo | `scripts/validate_project.py` | IMPLEMENTED / TESTS ADDED / MICROTESTS EXECUTED | Processo inicia sessão POSIX dedicada; encerra grupo mesmo se líder já saiu |
| Cleanup de pipes herdados | `scripts/validate_project.py` | IMPLEMENTED / TESTS ADDED / MICROTESTS EXECUTED | Deadline partilhado de 2 s + janela de limpeza de 1 s; status execution_error se readers não fecharem |

A correção elimina o acúmulo ilimitado de saída do subprocesso antes do truncamento do relatório e cobre descendentes que herdam os pipes. Os testes específicos foram adicionados em `tests/test_validation_runner.py`. A suíte integral, CI no HEAD e Termux/Realme continuam pendentes; o runner também não é uma sandbox.

Relatório histórico de falhas, causa provável, limitações e protocolo de recuperação: `docs/audits/TERMUX_REALME_FAILURE_REVIEW_20261119.md`.

## Recuperação read-only de experiências — MEMORY-RECALL-001 (2026-11-19)

| Capacidade | Componente | Maturidade | Limites/evidência |
|---|---|---|---|
| Recuperar episódios semelhantes | `AdaptiveLearning.retrieve_experiences()` | IMPLEMENTED / TESTS ADDED / MICROTEST EXECUTED | Similaridade Jaccard lexical; contexto precisa de assinatura exata; histórico máximo 500; retorno máximo 20 |
| Preferir episódios com evidência independente | `AdaptiveLearning` | IMPLEMENTED / TESTS ADDED | Episódios com receipt válido aparecem primeiro; confiança de episódio não verificado não é exposta |
| Expor API cognitiva | `CognitiveEngine.recall_experiences()` | IMPLEMENTED / TESTS ADDED | Read-only, autorização read_project, sem promoção e sem autorização de execução |
| Expor API integrada | `IntegratedCore.recall_experiences()` | IMPLEMENTED / TESTS ADDED | Delegação ao mecanismo compartilhado; não cria Store ou banco paralelo |

O método constitui apenas um baseline de recuperação lexical, não embeddings, memória semântica, aprendizagem neural ou transferência comprovada. A evidência de um episódio depende do verificador atualmente disponível; se o provider deixar de existir, a consulta falha fechada e deixa de marcar o recibo como verificado.

## Laboratório Blender reversível — BLENDER-LAB-001 (2026-11-19)

| Capacidade | Artefato | Maturidade | Limites/evidência |
|---|---|---|---|
| Probe read-only de cena | `blender_lab/01_readonly_scene_probe.py` | IMPLEMENTED / STATIC TESTS ADDED | Snapshot JSON limitado; não altera cena, não salva e não renderiza |
| Fixture de cena isolada | `blender_lab/02_create_reversible_fixture.py` | IMPLEMENTED / STATIC TESTS ADDED | Coleção dedicada com ID de propriedade; cria cubo, câmera e luz; preserva câmera ativa/render/frame |
| Rollback por propriedade | `blender_lab/03_remove_reversible_fixture.py` | IMPLEMENTED / STATIC TESTS ADDED | Só remove itens que carregam o marcador exato; preserva objetos não marcados |
| Protocolo de ensaio | `blender_lab/README.md` | DOCUMENTED / DEVICE RUN PENDING | Probe → fixture → probe → rollback → probe; executar numa cópia .blend |

A suíte `tests/test_blender_lab_scripts.py` verifica AST, marcadores de propriedade e ausência de operações proibidas no probe. Esses testes são estáticos; não provam que a API bpy funciona em todas as versões nem que o Blender móvel ofereça a interface Scripting. A execução real no aparelho permanece pendente.

## Prontidão para aprendizagem ao longo da vida — LIFELONG-LEARNING-001 (2026-11-19)

Foi consolidado um roadmap que diferencia armazenamento, recuperação, abstração, verificação, consolidação, aprendizagem e generalização. A arquitetura-alvo fecha o ciclo observação → interpretação → recuperação → previsão → planeamento → autorização → execução → feedback → erro de previsão → episódio → revisão → candidato de habilidade → verificação independente → consolidação → teste de retenção/transferência.

**Estado real:** arquitetura e plano documentados; não existe ainda aprendizagem geral, modelo do mundo preditivo, curiosidade operacional ou imaginação multimodal validada. O roteiro prioriza confiabilidade, providers de evidência/aprovação, avaliação de memória contínua, memória temporal/procedural, linguagem estruturada, Blender como mundo controlado, percepção multimodal isolada e treino paramétrico somente após comparação contra memory-only.

Documentos:
- `docs/research/LIFELONG_LEARNING_READINESS_20261119.md`
- `docs/research/CONTINUAL_LEARNING_MEMORY_AND_EDGE_VISION_20261119.md`
- `docs/audits/TERMUX_REALME_FAILURE_REVIEW_20261119.md`
- `blender_lab/README.md`

**Gates pendentes:** pytest integral/CI com runner real, validação em cópia Termux, ensaio Blender no dispositivo e teste térmico/performance de qualquer runtime multimodal. Nenhuma instalação, migração SQLite, sincronização do checkout original ou alteração da branch main foi feita.

## Hardening da validação e prontidão de aprendizagem — RUNTIME-LEARNING-001 (2026-11-20)

| Capacidade | Maturidade | Evidência/limite |
|---|---|---|
| Captura bounded de stdout/stderr | IMPLEMENTED / TESTS ADDED / MICROTESTS EXECUTED | Buffer por canal limitado a 64 KiB; não equivale à suíte completa |
| Encerramento de grupo de processos | IMPLEMENTED / TEST ADDED / MICROTEST EXECUTED | POSIX; cenário de descendente herdando pipes; processos fora do grupo continuam limite |
| Recuperação associativa de experiências | IMPLEMENTED / TESTS ADDED | Jaccard lexical e assinatura exata de contexto; não é busca semântica |
| Consolidação sob evidência | PARTIAL / FAIL-CLOSED | Provedores de atestação de produção ausentes; não promover experiências por relato do usuário |
| Caminhos de memória/conectoma | IMPLEMENTED / TESTS ADDED | Análise topológica não ponderada; causalidade não estabelecida |
| Laboratório Blender | SCRIPTS IMPLEMENTED / STATIC TESTS ADDED | Probe, fixture e rollback; Blender no telefone ainda não executado |
| CI para PRs empilhadas | CONFIGURATION PATCHED / RUN PENDING | Filtros incluem main/work/fix/research; job 45 min cobre 33 min de limites CI |
| Realme/Termux pós-correção | NOT VALIDATED | Baseline histórica device 1/8; reteste isolado obrigatório |

### Decisão de arquitetura

Não criar uma rede neural biologicamente literal nem adicionar um runtime externo ao núcleo. Priorizar o ciclo observável: percepção → estado estruturado → recuperação → previsão → plano → autorização → ação → observação posterior → erro de previsão → episódio → revisão → skill candidata → testes holdout → consolidação aprovada. Memória episódica, semântica e procedural devem manter proveniência e versões distintas.

O primeiro ambiente para testar previsão, causalidade operacional e habilidades é o Blender, numa cópia de cena, com probe read-only e fixture reversível. A integração Android deve começar por adaptadores de leitura de contexto/recursos (bateria, térmica, foreground, armazenamento e permissões), com valores desconhecidos tratados como orçamento zero. Não presumir root, acesso direto à NPU nem execução residente.

Relatórios: `docs/audits/TERMUX_REALME_FAILURE_REVIEW_20261119.md`, `docs/research/LIFELONG_LEARNING_READINESS_20261119.md` e `docs/research/CONTINUAL_LEARNING_MEMORY_AND_EDGE_VISION_20261119.md`.

**Bloqueadores antes do Realme:** CI com logs recuperáveis; validação de SQLite read-only em cópia; reteste das oito etapas; teste real do ciclo Blender em .blend descartável; medição de RAM/temperatura/bateria; comparação baseline vs memória recuperada vs skill candidata.

### Auditoria SQLite read-only — STORE-INTEGRITY-AUDIT-001 (2026-11-20)

| Capacidade | Maturidade | Limite |
|---|---|---|
| Auditoria read-only do SQLite | IMPLEMENTED / TESTS ADDED / EXECUTION PENDING | quick_check, foreign_key_check e JSON por coluna; não corrige nem autentica conteúdo |
| Proteção contra migração acidental | IMPLEMENTED | caminho explícito, URI mode=ro e query_only; usar primeiro numa cópia |

Arquivo: `scripts/audit_store_integrity.py`; testes: `tests/test_store_integrity_audit.py`. A auditoria não substitui backup, hashes nem comparação com snapshot anterior.

**Atualização CI #1202:** o filtro corrigido acionou a PR #55, mas o job falhou em ~2 s com `runner_id=0`, nenhum step e logs `BlobNotFound`. Maturidade: WORKFLOW TRIGGERED / RUNNER NOT PROVISIONED / CODE TESTS NOT EXECUTED.

## Atualização de maturidade — fisiologia digital, consciência e integração (2026-11-22)

Esta seção atualiza o mapa anterior. Onde houver divergência, prevalecem os HEADs e evidências datados abaixo; código presente ou teste escrito não deve ser promovido automaticamente a TESTED_INTEGRATION.

### Identidade, autorrepresentação e consciência

| Capacidade | Maturidade em 22/11/2026 | Evidência e limite |
|---|---|---|
| Identidade operacional única | IMPLEMENTED / EXISTING COMPONENTS | IdentityEngine, perfil versionado, IntegratedCore e memória compartilhada; continuidade real no Android não revalidada nesta etapa |
| Autorrepresentação operacional | IMPLEMENTED / PARTIAL | IntrospectionEngine e IdentityEngine descrevem arquitetura/estado conhecido; reconciliação temporal de medido, inferido, previsto e desconhecido ainda incompleta |
| Metacognição funcional | IMPLEMENTED / TESTS EXIST / PRIVATE CI BLOCKED | MetacognitiveMonitor e AdaptiveLearning têm calibração e evidências; efeito causal no próximo ciclo cognitivo ainda não demonstrado no runtime normal |
| Acesso cognitivo global | RESEARCH / EXPERIMENTS | GWT/GNWT, competição atencional e broadcast são hipóteses de pesquisa; não há workspace global validado |
| Experiência fenomenal | OPEN RESEARCH QUESTION | Nenhuma evidência computacional disponível permite afirmar que Mahoraga tenha experiência subjetiva |
| Programa de investigação da consciência | SPECIFIED | docs/research/CONSCIOUSNESS_PROGRAM_AND_TOOLCHAIN_20261122.md; compara RPT, GWT/GNWT, HOT, AST, Predictive Processing, IIT, MToC e DIT; especifica CON-01 a CON-08 |

### Fisiologia digital e evolução

| Capacidade | Maturidade em 22/11/2026 | Evidência e limite |
|---|---|---|
| Seleção de interesses | IMPLEMENTED / TESTS WRITTEN / PRIVATE CI PENDING | experiments/cognitive_interest_selector.py; candidatos são fornecidos pelo chamador; não descobre autonomamente lacunas nem cria objetivos |
| Homeostase digital simulada | IMPLEMENTED / TESTS WRITTEN / PRIVATE CI PENDING | experiments/digital_physiology.py; transições determinísticas sobre observações sintéticas; não consome telemetria real nem controla o hardware |
| Ciclo de exploração contextual | IMPLEMENTED / TESTS WRITTEN / PRIVATE CI PENDING | experiments/cognitive_exploration_cycle.py combina seleção e homeostase; não descobre candidatos, persiste memória, cria metas, executa trabalho ou autoriza ações |
| Evolução por programação genética | IMPLEMENTED / TESTS WRITTEN / PRIVATE CI PENDING | experiments/digital_evolution.py evolui programas matemáticos em VM fechada; não usa eval/exec, não altera o código-fonte do Mahoraga e requer sementes/tarefas fornecidas |
| Autorregulação real de recursos | PLANNED / CONTRACT GAP | Precisa de telemetria temporal e verificada, avaliação por classe de tarefa e limites externos imutáveis; parâmetros da simulação não são limites do dispositivo |
| Autoaperfeiçoamento do núcleo | RESEARCH / NOT OPERATIONAL | Não existe ainda caminho demonstrado de descoberta autônoma → hipótese → patch isolado → regressão → revisão → promoção |

### Núcleo cognitivo e recorrência

- IntegratedCore permanece a raiz canônica de composição; KnowledgeStore é a memória persistente compartilhada e Dharma/AutonomyGovernor mantêm autoridade de integridade e admissão.
- CognitiveFabric oferece despacho síncrono e workspace limitado; isso não demonstra recorrência global nem broadcast cognitivo.
- PR #65 é um harness manual reasoning → executive → reasoning; PR #66 endurece sinais/duplicação/limites/falhas parciais. Testes privados não foram executados na evidência consultada.
- O caminho normal do IntegratedCore ainda precisa demonstrar que feedback metacognitivo, atenção e resultados de ação alteram causalmente a iteração seguinte.
- Não criar outro Core, Store, identidade, scheduler ou autoridade de autorização para resolver essas lacunas.

### Ferramentas e ambientes de pesquisa

| Ferramenta | Papel | Maturidade de integração |
|---|---|---|
| Python | Integração, pesquisa, experimentos e testes | EXISTING / PRIMARY IMPLEMENTATION LANGUAGE |
| NengoSPA | Representações neurais/semânticas e arquiteturas cognitivas comparativas | RESEARCH CANDIDATE; NOT RUNTIME DEPENDENCY |
| Godot | Ambiente controlado para percepção, ação, consequências e modelo de mundo | PLANNED / NOT INTEGRATED |
| Brian2 | Dinâmica neural e plasticidade quando experimentos exigirem maior fidelidade | RESEARCH CANDIDATE |
| MuJoCo | Física/biomecânica e interação corporal futura | RESEARCH CANDIDATE |
| ACT-R, Soar, LIDA | Referências comparativas para memória, objetivos, resolução de problemas e atenção | RESEARCH REFERENCES |
| NEST, NEURON, Unity ML-Agents | Ferramentas especializadas opcionais conforme hipótese experimental | NOT REQUIRED |

### Evidência e sincronização

- PR #142 → #143 formam a linha de seleção de interesses e fisiologia/evolução digital. PR #144 → #145 formam outra linha de diagnóstico e concorrência. Ambas partem da branch de auditoria; não são uma única cadeia linear.
- A branch de auditoria diverge do main privado em 1.072 commits à frente e 4 atrás, com 220 arquivos diferentes. Não retargetear nem mesclar as PRs #142–#145 em massa no main.
- PR #146 remove o filtro de destino main do workflow de physics syntax-check. A execução #45052381640 foi acionada, mas falhou em 1 segundo com runner_id=0, runner_name vazio, steps=[] e sem logs recuperáveis. Resultado: RUNNER NOT PROVISIONED / CODE NOT EXECUTED, não PASS nem FAIL de código.
- O workflow atual continua executando apenas compileall de agent; não equivale à suíte pytest nem à validação device.
- O snapshot público contém adaptações: alguns arquivos têm SHA idêntico aos privados e outros diferem. O manifesto de origem por arquivo deve registrar source commit/blob, lab blob, motivo da adaptação, testes e run de validação.
- A PR pública #2 deriva de uma HEAD antiga da PR privada #143 e declara adaptações de validação. A documentação atual do programa de consciência ainda não existe no snapshot público.
- Nenhum commit novo deve ser publicado no repositório público enquanto a exposição de metadados de autoria não for resolvida.

### Regra de promoção

Somente avançar a maturidade quando a evidência existir no commit exato: testes unitários, integração pelo caminho real, holdout/ablação quando aplicável, regressão, CI executada com logs recuperáveis e validação no dispositivo quando a capacidade depender do Android. Testes do snapshot público são evidência auxiliar e não substituem a validação privada. Experiência fenomenal permanece uma questão aberta, independentemente da maturidade de engenharia.
### Atualização de CI e base ativa do Core — 2026-11-22

- A base ativa de desenvolvimento é work/termux-runtime-and-learning-hardening-20261120, não o workflow mínimo de main. Ela contém a suíte unificada scripts/validate_project.py, filtros para PRs main/work/fix/research, concorrência por PR, artefatos JSON/JUnit e matriz Python 3.12/3.14 (3.12 nas PRs empilhadas).
- A PR #144 adiciona probes sem checkout em ubuntu-latest e ubuntu-24.04 e atualiza actions para v7. Ambos os probes privados e o job de teste falharam antes da alocação do runner (runner_id=0, steps vazios); nenhum código foi executado.
- PR #146 altera apenas o workflow legado de main, que continua limitado a compileall. Não confundir essa alteração com a suíte unificada do Core ativo.
- A base de desenvolvimento também diverge do main em 1.031 commits à frente, 4 atrás e 212 arquivos. A promoção para main exige uma estratégia separada de consolidação e backport; não mesclar o histórico inteiro.
### Backports de integridade e CAS — 2026-11-22

| Capacidade | Estado | Evidência |
|---|---|---|
| Allowlist de comandos de diagnóstico | BACKPORT DRAFT / PRIVATE CI BLOCKED | PR #147; 5 arquivos, 4 arquivos de código/teste com blob SHA idêntico à origem #144; testes do snapshot público passaram, mas CI privada #45053257009 não alocou runner |
| Concorrência de iniciativas e foco | SOURCE DRAFT / NOT VALIDATED PRIVATELY | PR #145; corrige corrida de adoção e acrescenta CAS transacional de foco; CI privada sem runner |
| Retry idempotente sob CAS | HARDENING DRAFT / TESTS ADDED | PR #148; resolve evento já persistido antes de verificar revisão antiga; teste de retry e payload conflitante escrito, não executado |

Os runs privados #45053257009 e #45053459941 falharam antes de alocar runner (runner_id=0, steps vazios, logs indisponíveis). Nenhum teste desses PRs foi executado. Manter as alterações em Draft; não confundir código revisado com código validado.
### Consolidação do candidato de backport — 2026-11-22

- PR #149 é o candidato único de integração seletiva para a base ativa work/termux-runtime-and-learning-hardening-20261120. Contém nove arquivos: allowlists de diagnóstico, concorrência executiva, CAS transacional e retry idempotente, mais testes e workflow.
- PR #147 foi fechada como supersedida por #149, sem merge. PR #149 continua Draft; não há execução privada conclusiva associada à sua HEAD.
- PR #148 preserva o hardening de origem e seu teste, mas o backport integrado para o branch ativo está consolidado em #149.
- A promoção continua bloqueada pela alocação de runner; código revisado e diff auditado não equivalem a testes executados.
- PR #149 executou o workflow em #45053916190, mas todos os três jobs falharam antes da alocação do runner (runner_id=0, runner_name vazio, steps=0). Nenhum teste da PR consolidada foi executado.
- PR #146 foi fechada sem merge por alterar apenas o workflow legado do main; a base ativa já possui CI unificada. A investigação de runner permanece no workflow do Core ativo.
- HEAD atual da PR #143 (programa de consciência e Mapa Evolutivo) executou #45054104159, mas o job Python 3.12 não alocou runner (runner_id=0, zero steps); nenhum teste foi executado. O probe não existe nessa linha de workflow.

## 16. Auditoria do runtime cognitivo, recursos e correção do backport — 22/11/2026

### 16.1 PR #149 — correção estática após revisão

- HEAD atual: `053ef72d0bd95e5c93376791102f9aa781cc686a`; base `work/termux-runtime-and-learning-hardening-20261120`; 9 arquivos; Draft; sem merge.
- A revisão detectou que `HardwareIntelligence.android()` consulta `ro.product.name` e `ro.build.fingerprint`, mas a nova allowlist de `_command()` rejeitava ambas. Isso causava perda silenciosa de dados do diagnóstico.
- Correção mínima aplicada em `agent/hardware_intelligence.py`, commit `cf510aba3c1ccc603d1af64537e9dbf885aabe3d`: ambas as propriedades foram incluídas na allowlist.
- Teste positivo de regressão adicionado em `tests/test_hardware_intelligence.py`, commit `053ef72d0bd95e5c93376791102f9aa781cc686a`.
- O CI #45054969222 foi reexecutado após a correção. Os três jobs (teste Python 3.12 e probes ubuntu-latest/ubuntu-24.04) terminaram em falha sem steps, logs ou runner provisionado. Classificação: `RUNNER NOT PROVISIONED / CODE NOT EXECUTED`. A correção está estaticamente revisada, não executada.
- Ponto de consistência pendente: `HardwareIntelligence._shizuku_diagnostics()` conserva uma chamada direta a `subprocess.run()` com script fixo e sem entrada de usuário. Não foi identificado shell input controlável, mas o caminho não compartilha o helper de allowlist; consolidar em revisão separada e cobrir cada comando com testes.
- PR #149 permanece Draft. Não promover para a branch de desenvolvimento ou `main` sem execução focada, concorrência e pipeline integral.

### 16.2 Caminho cognitivo normal — estado observado no código

`IntegratedCore.prepare_request()` utiliza efetivamente o `CognitiveFabric` no caminho normal. O roteamento síncrono observado é:

`request.received → language.completed → knowledge.retrieved → reasoning.completed → executive.context_ready → conversation.context_ready → introspection.context_ready → context.ready`.

O ciclo é integrado estruturalmente, mas ainda é uma passagem predominantemente linear:
- Não há retorno de metacognição/introspecção para revisar a hipótese ou alterar uma etapa anterior do raciocínio na mesma solicitação.
- O workspace é temporário e descartado ao fim do ciclo; o relatório não é memória episódica persistente.
- O fabric limita profundidade e número de sinais, mas ainda não fornece watermarks temporais por origem nem entrega idempotente nativa.
- A recuperação de conhecimento é armazenada como contexto separado. O raciocínio atual usa somente `facts`, `rules` e pares de contradição explicitamente fornecidos pelo chamador; os fragmentos recuperados não são automaticamente convertidos em fatos do raciocínio. Essa separação protege a proveniência, mas limita a integração semântica.
- A calibração metacognitiva da linguagem é consultiva (`advisory_only`, `behavior_changed=False`). O estado do monitor é consultado, mas não constitui ainda um ciclo de autorrevisão que modifique o resultado.
- Identidade, memória executiva, conversa, capacidades e estado de pesquisa entram no contexto, mas a decisão final de `plan_status` é determinada principalmente por contradições explícitas, decisão linguística, reconhecimento e quantidade de resultados de conhecimento.
- `include_experience_review` permanece opt-in e seu padrão é `False`; o recrutamento dinâmico e automático de capacidades ainda não é o comportamento padrão do runtime.
- `prepare_request()` declara que não persiste aprendizagem nem memória; isso deve continuar explícito até existir um contrato de persistência aprovado e idempotente.

Classificação: tecido de roteamento síncrono implementado no runtime de desenvolvimento; recorrência cognitiva com feedback causal ainda não demonstrada.

### 16.3 Governança de recursos — limites atuais

`AutonomyGovernor` utiliza parâmetros fixos no código: memória mínima/preferida de 1.024/2.048 MB, armazenamento mínimo/preferido de 1.024/2.048 MB, janelas de 5 segundos em foreground e 20 segundos em carregamento, com orçamentos máximos de 64/256 MB de RAM. Esses valores são políticas estáticas, não limites aprendidos a partir de histórico do Realme.

Próxima evolução recomendada:
- Separar limites rígidos de segurança/plataforma de estimativas operacionais adaptáveis.
- Aprender perfis por classe de tarefa usando medições reais de duração, pico de memória, pressão térmica, bateria e falhas.
- Registrar tamanho da amostra, dispersão, confiança e validade temporal; abster-se quando a evidência for insuficiente.
- Permitir que o modelo aprendido reduza ou ajuste orçamentos dentro dos limites rígidos, nunca que os amplie silenciosamente acima das restrições externas.
- Validar com holdout temporal, cenários de carga e recuperação; não calibrar apenas com uma sessão ou valores simulados.

### 16.4 Próximas experiências integradas

1. Preservar a execução linear atual como baseline reproduzível.
2. Construir um harness isolado de recorrência: crítica metacognitiva estruturada → seleção executiva de um único ponto de revisão → nova avaliação do raciocínio, com limite de iterações, causalidade, idempotência e orçamento.
3. Comparar baseline, ciclo recorrente e ablações em holdout; medir qualidade, correções úteis, falsos positivos, latência, RAM e estabilidade. Nenhuma escrita no Store nem execução de ferramentas durante o experimento.
4. Evoluir recrutamento contextual para selecionar capacidades existentes automaticamente a partir da intenção, incerteza, evidência, dependências, risco e recursos. A aprovação humana continua exigida para efeitos externos e mudanças de alto risco.
5. Conectar conhecimento recuperado ao raciocínio somente por objetos tipados com fonte, trecho, confiança e estado epistêmico; nunca promover automaticamente uma recuperação lexical a fato confirmado.
6. Criar calibração de recursos por tarefa, mantendo tetos rígidos externos e rastreabilidade das medições.

### 16.5 Estado de validação e continuidade

- A branch privada de desenvolvimento permanece `work/termux-runtime-and-learning-hardening-20261120`; `main` continua sendo uma baseline separada e não foi alterada.
- PR #149 é o único candidato consolidado de backport para a branch ativa; permanece Draft.
- PR #143 permanece Draft na linha de pesquisa cognitiva; HEAD observado `9096474ff22c8d7488099884c179e739c77f6f6b`.
- Repositório privado `mahoraga-core` continua privado. O snapshot público continua público e não recebeu commits nesta etapa.
- Nenhuma alteração em Termux, Realme, SQLite local ou runtime de produção.
- O perfil `device` de `scripts/validate_project.py` continua executando o mesmo plano de oito estágios com timeouts maiores; não realiza, por si só, probes Android/Termux. Não classificar esse perfil como validação real de dispositivo.
- Maturidade das mudanças recentes: correção de allowlist estática aplicada e teste escrito; execução pendente; integração não validada; dispositivo não validado.


### 16.6 Portfólio de pesquisa — frentes paralelas, sem promoção

| PR | Frente | Contribuição experimental | Limite e decisão |
|---|---|---|---|
| #56 | CNS recorrente | Neurônios LIF, sinapses com atraso, limites e atomicidade de passo | Runtime neural isolado; não substitui CognitiveFabric/NeuralCore; testes não executados |
| #59 | Estado integrado | Snapshots imutáveis, hashes, watermarks por origem e rejeição de replay | Não prova captura temporal coerente; referências de origem não são autenticação; testes não executados |
| #61 | Recrutamento contextual | Política explicável para selecionar processos, fontes e habilidades conforme contexto/risco/recursos | Plano hipotético, fixtures sintéticas; não chama componentes nem autoriza execução; manifesto real desabilitado; testes não executados |
| #65/#66 | Recorrência causal | Harness com componentes reais, feedback reasoning→executive→reasoning, ablação e hardening de limites | Não é o caminho normal de `prepare_request()`; despacho não é transacional e sinais duplicados não são deduplicados; testes não executados |
| #67 | Feedback metacognitivo | Outcome linguístico aprovado, vínculo ciclo/preditor, atestado e idempotência | Branch empilhada em outra linha; provider de evidência de produção não validado; não grava outcomes automaticamente; testes não executados |
| #69/#71/#74 | Modelo de mundo | Previsão condicionada por ação, shift de distribuição, incerteza e observação parcial/adaptação online | Simuladores sintéticos; sem sensores reais, política de ação ou integração executiva; testes não executados |
| #70/#73/#75 | Utilidade e interferência da memória | Compara sem memória, recuperação global/família/tarefa, staleness, contaminação e atribuição de feedback | Harnesses sintéticos, não benchmark direto do AdaptiveLearning; nenhum ganho numérico comprovado |
| #72 | Know/act/hold | Benchmark de decidir entre agir, pesquisar, perguntar ou adiar | Oito casos sintéticos são smoke test, não benchmark estatístico nem agente metacognitivo |

Todas essas PRs estão Draft e sem merge no estado consultado. A ausência de execução impede declarar aprovação dos testes ou ganho de desempenho.

**Ordem recomendada de pesquisa:** (1) restaurar validação executável e concluir a revisão de integridade do Core; (2) executar #65/#66 como teste causal da recorrência, sem integrar o harness; (3) avaliar #61 contra capacidades reais do manifesto e disponibilidade observada; (4) validar o contrato temporal de #59; (5) só então combinar world model e memória em experimentos de holdout. A CNS #56 permanece como comparação neural isolada, sem criar um segundo núcleo. #67 exige primeiro um provider de evidência confiável e revisão da linhagem da branch-base.

A PR #70 registra commits de escrita/reversão de dois arquivos na branch padrão por omissão do parâmetro `branch`; a descrição da PR afirma que os arquivos foram removidos e o estado atual verificado. Esse histórico exige inspeção explícita antes de qualquer promoção; não importar a branch inteira.



## 17. Consolidação da allowlist Shizuku — 22/11/2026

- A segunda revisão estática da PR #149 confirmou que `HardwareIntelligence._shizuku_diagnostics()` ainda possuía uma chamada direta a `subprocess.run()`, embora usasse um script literal fixo.
- O caminho foi consolidado no HEAD privado `dc414c52a2c66f21f2ae2bc0610b1a25876211e3`: o script Shizuku somente de leitura agora é uma constante; `_command()` aceita somente o caminho `rish -c` com o script exato; `_shizuku_diagnostics()` utiliza o helper central.
- Foram acrescentados testes para aceitar o script exato, rejeitar script alterado antes do subprocess e comprovar que o coletor usa o helper central.
- A correção anterior de `ro.product.name` e `ro.build.fingerprint` permanece coberta por teste positivo.
- CI #45055526593, para o HEAD acima: job Python 3.12 e probes ubuntu-latest/ubuntu-24.04 falharam sem runner/steps/logs. Nenhum teste executado.
- A observação de 16.1 sobre caminho Shizuku duplicado passa a ser **corrigida estaticamente**, mas permanece sem validação executada. A PR #149 continua Draft, sem merge.
- Maturidade: alterações estáticas revisadas; testes escritos; execução pendente; integração não validada; dispositivo não validado.



## 18. Fechamento estático dos pontos de execução Shizuku — 22/11/2026

- Uma varredura posterior encontrou uma segunda chamada direta a `subprocess.run()` em `HardwareIntelligence.runtime_context()`, usada para ler power/activity/thermal. O primeiro hardening havia consolidado `_shizuku_diagnostics()`, mas ainda não cobria esse segundo caminho.
- No HEAD da PR #149 `755f3240d3be608c2074b235b793b89c8900b657`, o script de runtime context também foi transformado em constante exata, incluída na allowlist central. `runtime_context()` agora usa `_command()` e preserva comportamento fail-closed quando a execução ou o formato falham.
- Testes adicionados para: aceitar o script exato, rejeitar script alterado e confirmar que `runtime_context()` delega ao helper.
- Varredura estática após a alteração: `agent/hardware_intelligence.py` possui uma única chamada `subprocess.run()`, dentro de `_command()`; `agent/deep_diagnostics.py` possui uma única chamada, dentro de `_run()`, que valida sua própria allowlist. Não há outros `Popen` ou `shell=` nesses dois módulos.
- CI #45055705152, associado ao HEAD acima: suite Python 3.12 e probes ubuntu-latest/ubuntu-24.04 falharam sem runner/steps/logs. Nenhum teste foi executado.
- Resultado: centralização estática dos pontos de execução de subprocess nos módulos de diagnóstico; **não** é validação de segurança dinâmica, execução em Android ou prova de ausência de vulnerabilidades.
- PR #149 continua Draft, sem merge. Código alterado permanece no branch isolado de backport.



## 19. Atualização sistêmica — Companion, engenharia procedural e lacunas de capacidade (22/11/2026)

### 19.1 Fundamentos fortes que devem ser preservados
- `IntegratedCore` compõe os mecanismos existentes; `KnowledgeStore` mantém o estado persistente compartilhado.
- `CognitiveFabric`, `CognitiveEngine`, `ExecutiveEngine`, memória conversacional, identidade operacional e introspecção fornecem uma fundação cognitiva integrada.
- `Dharma` e `AutonomyGovernor` separam autorização, risco e orçamento de execução.
- `ToolIntelligence` detecta ferramentas e registra níveis de competência sem executar comandos descobertos arbitrariamente.
- `CapabilityManifest` valida metadados e dependências; adaptadores governados fornecem um caminho de ligação controlada.
- `EngineeringWorkbenchV2` oferece staging, validação isolada por cópia, journaling transacional, backup, verificação de integridade, recuperação e rollback.
- `scripts/validate_project.py` oferece pipeline unificado com limites de saída e encerramento de árvore de processos.
- O snapshot público independente mantém evidências separadas da história privada.

### 19.2 Lacunas mensuradas no catálogo atual
- `config/capability_manifest.json`: 15 definições, 14 com maturidade declarada `implemented`, uma `in_development`, **zero habilitadas**.
- O catálogo inclui leitura de hardware/conhecimento/memória, revisão cognitiva, introspecção, estado de pesquisa, identidade, memória executiva e conversa; também declara geração local e geração procedural de imagem, mas as entradas continuam desabilitadas.
- `ReadOnlyCapabilityAdapters` liga apenas operações de leitura e revisão governada. Não há adaptador de engenharia que conecte intenção a geração, construção, execução e validação de sites/aplicativos.
- `ToolIntelligence.discover()` identifica comandos e pacotes instalados; presença não significa domínio. Os níveis de competência são registrados por evidência fornecida, mas ainda não formam um pacote procedural com pré-condições, passos, verificadores, custos, falhas e transferência.
- `IntegratedCore.prepare_request()` mantém o baseline cognitivo predominantemente linear. Revisão de experiência continua opt-in; recorrência causal e recrutamento dinâmico não são o comportamento padrão.
- O workbench prepara e valida alterações, mas não constitui sandbox de sistema operacional nem fábrica geral de software. Execução arbitrária continua fora do escopo de confiança.
- A geração de sites, APIs, aplicativos Android e ferramentas próprias ainda não foi comprovada ponta a ponta.

### 19.3 Companion — hardening incremental
- Branch privada de trabalho: `hardening/worker-fencing-and-recovery-20261123`, baseada em `implementation/android-workmanager-bridge-20261122`; PR #159 Draft, sem merge.
- Worker Python recebe `worker_id` UUID por invocação, evitando que processos diferentes compartilhem a mesma identidade de lease.
- Bridge usa `startForegroundService()` em API 26+; abaixo disso usa `startService()`.
- Revisão do contrato: Termux upstream 0.118.0 declara targetSdk 28. A restrição Android 12+ para iniciar FGS cross-app exige ambos os apps target API 31+; portanto não é a restrição específica aplicável ao Termux enquanto target 28. O limite Android O para iniciar serviço em background pelo chamador target 26+ continua relevante e justifica usar a API de foreground service.
- O processo Python é encapsulado por Termux coreutils `timeout`: 30 s, SIGTERM e 2 s de grace period para SIGKILL. O bridge falha fechado se o executável não estiver disponível.
- Espera Android de 45 s deixa margem para o limite externo de 32 s.
- Backoff WorkManager de 120 s excede o lease Python de 90 s, evitando retry antes da janela de recuperação.
- Wake receiver exportado compara `getSentFromUid()` com o UID instalado de `com.termux` em Android API 34+; comparação por UID tolera pacotes Termux que compartilham UID. Versões anteriores mantêm ação explícita e rate limit sem autenticação forte de origem.
- O wake usa broadcast ordenado via `am broadcast`; o receiver retorna código 1 somente depois de `WorkManager.enqueueNext()` aceitar a inclusão. O adapter Python exige `Broadcast completed: result=1`; exit code 0 sem confirmação não é mais tratado como agendamento concluído.
- Bundle Termux valida `stdout_original_length` e `stderr_original_length`; limites de 48 KiB stdout, 16 KiB stderr e 64 KiB combinados rejeitam recibos potencialmente truncados.
- Activity consulta WorkInfo de execução única e polling e apresenta estado, tentativas, task_id, wake, erro, validade do recibo e snapshot da fila (queued/claimed/active/revision) quando disponíveis; é o último snapshot retornado pelo worker, não uma consulta live ao SQLite.
- Plano T0–T5 de validação controlada do Realme registrado em `docs/operations/REALME_COMPANION_DEVICE_VALIDATION_PLAN_20261122.md`.
- Evidência independente: Python #350 (3.12/3.14) e Android #28 passaram para worker fencing, API FGS, timeout, backoff, sender check e validação de truncamento. Android #31 passou para a Activity inicial, artefato #14780550013 (2.875.151 bytes; SHA-256 `35447e33437fe54578d2f350af0430f1c285c85e5a57d3ec5e4b7ad97e817e67`). A atualização de queue snapshot teve um teste inicialmente incompatível com o stub de `org.json` no runner Android; o helper foi refatorado para campos primitivos. Python #371 (`45089064459`) passou em Python 3.12/3.14; Android #49 (`45089064500`) passou com a Activity e o snapshot da fila, artefato #14779859902 (2.876.457 bytes; SHA-256 `4e4e64c2d6d3d08e9c268fa7585b76ea6b661537b7ab78c0eb95eb002b463ca2`). A validação estrita de estados/recibos do worker está em Android #52 (`45089345826`) e Python #374 (`45089345841`). O artefato #14779859902 antecede essa última validação estrita.
- Nenhuma instalação, permissão, configuração Termux ou configuração Android foi alterada. Dispositivo não validado.

### 19.4 Engenharia procedural e fábrica de software
- Especificação criada em `docs/architecture/PROCEDURAL_SKILLS_AND_SOFTWARE_FACTORY_20261122.md`.
- Habilidade deve ser procedimento versionado e verificável, não um agente ou personalidade independente.
- Contrato futuro: intenção suportada, exclusões, pré-condições, ambiente, dependências/licença, schemas de entrada/saída, etapas, checkpoints, riscos/permissões, verificadores, evidências, desempenho, recuperação e transferência.
- Primeiras famílias candidatas: `web.app_builder`, `web.api_builder`, `android.app_builder`, `mahoraga.internal_tool_builder` e `mahoraga.skill_authoring`.
- Pipeline pretendido: requisitos → especificação → design → escolha de stack → staging → implementação → análise/testes → execução controlada → QA visual → empacotamento reproduzível → entrega/preview → evidência e aprendizagem.
- Mahoraga deve possuir orquestração, contratos, templates, adaptadores, verificadores, memória e procedimentos; deve reutilizar compiladores, runtimes, motores e ferramentas maduras quando forem melhores.
- Essa capacidade permanece **planejada**. A especificação não cria um skill runtime, não ativa entradas do manifesto e não declara sites/apps gerados em uso real.

### 19.5 Direção priorizada
1. Fechar CI e revisão estática do PR #159; manter o snapshot público sincronizado e o manifesto de proveniência atualizado.
2. Validar o contrato Android/Termux no Realme em T0–T5, um passo por vez, sem antecipar permissões ou mudanças de configuração.
3. Reconciliar PRs empilhados #153–#159 e as branches de base; nenhum merge automático.
4. Consolidar o contrato de habilidade sobre Store/manifesto existentes, evitando banco e catálogo redundantes.
5. Construir a primeira habilidade web em staging e provar build, testes, execução e QA visual.
6. Reutilizar o mesmo pipeline para API e aplicativo Android; somente depois desenvolver recrutamento dinâmico de habilidades e aprendizagem procedural.
7. Evoluir a recorrência cognitiva e o feedback metacognitivo em harness isolado, comparado ao baseline linear.

### 19.6 Maturidade
- Companion: implementado e compilado; partes testadas em CI; Android/Termux/Realme ainda não testados no aparelho.
- Fencing, timeout, retry e validação de resultado: código revisado e CI público aprovado nos commits de referência; efeito operacional ainda não validado em dispositivo.
- WorkManager observability UI e snapshot de fila: implementados e testados em Android #49; contrato estrito de estado/queue/wake receipt está em CI #52.
- Fábrica de software e habilidades procedurais: especificadas, não implementadas.
- Cognição recorrente e recrutamento dinâmico: experimentais/planejados; não tratar como capacidade operacional.
- Identidade e introspecção: modelo operacional; não implicam consciência ou experiência subjetiva.


## 20. Reconciliação da cadeia de PRs 153–159 (22/11/2026)

### 20.1 Estado remoto confirmado
Todos os PRs #153–#159 permanecem abertos, Draft, não mergeados e marcados como mergeable no momento da consulta.

| PR | Base | Head | Relação |
|---|---|---|---|
| #153 | `research/physiology-evolution-sync-20261122` | `architecture/continuous-life-and-systemic-evolution-20261122` | proposta paralela |
| #154 | `research/physiology-evolution-sync-20261122` | `implementation/persistent-lifecycle-state-20261122` | início da cadeia de implementação |
| #155 | branch #154 | `implementation/persistent-background-queue-20261122` | empilhada sobre #154 |
| #156 | branch #155 | `implementation/autonomous-internal-inquiries-20261122` | empilhada sobre #155 |
| #157 | `implementation/background-companion-mode-20261122` | `fix/background-execution-receipts-20261122` | base é descendente de #156 |
| #158 | branch #157 | `implementation/android-workmanager-bridge-20261122` | empilhada sobre #157 |
| #159 | branch #158 | `hardening/worker-fencing-and-recovery-20261123` | hardening atual sobre #158 |

### 20.2 PR #153 versus PR #154
Os dois PRs partem do mesmo base SHA `7a06dfa8780d4dcd1e9e0185314eaf512a447b8c` e alteram:
- `.github/workflows/physics-tests.yml`;
- `docs/architecture/CONTINUOUS_DIGITAL_LIFE_AND_SYSTEMIC_EVOLUTION.md`.

A versão do documento na branch #153 e na branch #154 possui o mesmo blob SHA `f9a93f2b808e771b0ce910294ef207782baa5b9d`. A alteração de workflow de #154 inclui `architecture/**` e amplia os padrões para branches `implementation/**`, portanto contém a expansão feita por #153 e ainda acrescenta os padrões necessários à implementação.

Conclusão: o conteúdo de #153 está **subsumido** pela árvore de #154; #153 é uma proposta paralela redundante para a consolidação atual. Não fechar nem mergear automaticamente. Na reconciliação final, revisar se #154 já preserva integralmente o propósito de #153 e então decidir se #153 será encerrada como supersedida.

### 20.3 Base intermediária não representada por PR próprio
A base de #157 é `implementation/background-companion-mode-20261122`, SHA `87aed75ca0b24ca358c969fcae2245cf4b6a84f8`. Essa base está **11 commits à frente** do head de #156 (`db1463ff166cd30052ed1e286dcfc62cc6bd0433`), com merge-base exatamente no head de #156.

O intervalo intermediário altera oito arquivos, incluindo:
- `agent/autonomy_governor.py`;
- `agent/background_work_queue.py`;
- `agent/research_orchestrator.py`;
- `docs/architecture/BACKGROUND_WORK_SCHEDULER_CONTRACT.md`;
- `docs/architecture/CONTINUOUS_DIGITAL_LIFE_AND_SYSTEMIC_EVOLUTION.md`;
- testes de Governor, fila e orquestrador.

A alteração de topo da base corrige a política para permitir Companion com tela ligada e outro app em primeiro plano, mas o intervalo completo contém 11 commits e não foi encontrado PR próprio com essa branch como head. Esses commits são ancestrais de #157 e entram na cadeia por meio da base; não devem ser ignorados apenas porque não aparecem no diff de #157.

**Pendência de reconciliação:** recuperar e revisar os 11 commits, seus autores/mensagens, testes e evidências, identificar se pertencem a trabalho anterior não listado e decidir como registrar sua revisão antes de qualquer consolidação.

### 20.4 Encadeamento posterior
- #157 head `16b1d844a0151c4076d5fc3c603f1ee7e9aab180` é o base SHA de #158.
- #158 head `6c87e5e8970f7e3490b559a23257ab38c4b12f40` é o base SHA de #159.
- #159 head atual no momento desta atualização: `fa1242de95c2ff50cd509f087630c1425b04d912`.

A cadeia #154→#155→#156→(11 commits intermediários)→#157→#158→#159 é ancestralmente coerente, mas a revisão dos 11 commits intermediários permanece pendente. Nenhum merge foi executado.


### 19.7 Refinamento do contrato de recibo
- O worker Android aceita apenas estados conhecidos e exige coerência entre estado, task_id, execução e recibo.
- Estados conhecidos inconsistentes retornam retry para permitir reconciliação; status desconhecido é rejeitado como erro de contrato.
- O campo JSON `delay_seconds: null` é normalizado por `JSONObject.isNull()` antes da validação de `not_needed`, evitando confundir `JSONObject.NULL` com um valor de delay presente.
- O snapshot de fila valida componente, versão, tipos, contadores não negativos e consistência entre `queue.pending` e o ACK do wake.
- A correção foi sincronizada ao snapshot público; CI Android #52 foi iniciado antes da normalização JSON-null. Android #56 (`45089467047`) passou compilação, testes unitários e APK para o contrato estrito, normalização JSON-null e classificação de retry; Python #378 (`45089467034`) passou em 3.12/3.14. Artefato #14780224117, SHA-256 `97dfef07b078d41e35baf6b95e1fe79af6c9d383ee804c1ccc312335229d9550`. Python #384 (`45089693314`) passou em 3.12/3.14 para a atualização de visibilidade dos pré-requisitos Termux; Android #62 (`45089693346`) está em validação.


## 21. Paridade do snapshot público — 23/11/2026
- Head privado do PR #159: `a4c14d9a2129c8294b029cfe02627ec3f1ac8131`.
- Head público do snapshot: `e2b412896700c9e35c7ef2e00ca52d1d78840311`.
- Foram comparados os Git blob SHAs de 21 arquivos centrais de Python, worker, Android, configuração e testes. **21/21 correspondem exatamente**.
- Isso confirma igualdade do conteúdo dos arquivos auditados, não igualdade integral das histórias Git ou árvores documentais dos dois repositórios.
- O snapshot público contém a atualização do painel de pré-requisitos; Android #62 ainda valida essa versão.


### 19.8 Candidata CI final — 23/11/2026
- Python #384 passou em Python 3.12 e 3.14.
- Android #62 passou compilação, testes unitários e assembleDebug.
- APK atual: artifact #14780523033, 2.877.678 bytes, SHA-256 `f98c583f7bc40a6b4d38ca3d8c1de6b7a098501e54d86d335aa94626d9d62ad5`, expira em 07/12/2026.
- Origem: snapshot público commit `5fd29a3e8458ac2ca6e54ca827735d2e8ff4632d`; paridade de 21 arquivos com o head privado #159 foi confirmada.
- Maturidade: **implementado, compilado e testado em CI**. Ainda **não instalado nem testado no Realme 14 5G**. Não classificar como funcional em background até completar T0–T5.


## 22. Contrato procedural de habilidades — 23/11/2026

- Workstream MAH-SKILL-FACTORY-001: primeiro registro procedural integrado ao IntegratedCore.
- Arquivos: agent/procedural_skills.py, config/procedural_skills.json, tests/test_procedural_skills.py e docs/architecture/PROCEDURAL_SKILL_CONTRACT_V1_20261123.md.
- O registry valida pacotes declarativos versionados, schemas de entrada/saída, orçamento, permissões locais, dependências, etapas, bindings de dados, referências e riscos das capacidades, proveniência e recuperação.
- Prontidão exige habilidade habilitada e operacional, capacidades declaradas/habilitadas e vínculos runtime presentes no ResearchOrchestrator. Ferramentas requeridas precisam constar no catálogo.
- O matcher atual é lexical/determinístico e serve somente como baseline. Não é recrutamento semântico.
- O plano não despacha etapas. Não há execução procedural automática, sandbox de SO, adaptador geral de geração de código nem fábrica de sites/apps.
- Primeiro pacote mahoraga.system_audit: planejado/desenhado, desabilitado; referencia hardware.snapshot, introspection.capability_audit e memory.history_read, todas desabilitadas no manifesto atual. Resultado esperado: blocked.
- Nenhuma das 15 capacidades existentes foi habilitada. Nenhuma permissão Android, rede ou instalação foi concedida.
- Maturidade desta entrega: implementação integrada e validada em CI independente. Snapshot público commit aa79cf2c2bdb758b63a6bc40a67b826a710f96d5, run #399: Python 3.12 e 3.14 com 941 passed, 1 skipped e 28 subtests passed; compileall passou. O teste ignorado depende do corpus local excluído do snapshot.

- O primeiro CI detectou três relações do novo registry ausentes no conectoma; todas foram mapeadas e cobertas por teste de integração. Uma rodada seguinte identificou um teste antigo que tentava registrar capacidade sem sincronizar o manifesto e a ausência de orchestrator_autonomy no relatório; contrato do teste e observabilidade foram corrigidos. A suíte completa voltou a passar no run #399.
- Maturidade operacional exige provedor local confiável com verify_local(reference); sem verificador injetado, o registry bloqueia habilidades operacionais. Nenhuma evidência textual autodeclarada libera execução.
- Android Runtime Contract run #77 ainda está em execução no snapshot; é validação da ponte já existente, não prova de execução no aparelho.
- Próximo incremento após CI: executor procedural checkpointable de uma etapa por invocação, reutilizando fila, lease, recibo, Governor e ResearchOrchestrator; depois verificadores independentes e primeiro web.app_builder em staging.


## 23. Gate do Companion por manifesto — 23/11/2026

- Workstream MAH-COMPANION-MANIFEST-GATE-001.
- Auditoria encontrou que InternalBackgroundCapabilities tentava registrar internal.adopt_next_inquiry sem declaração/habilitação no CapabilityManifest. Como o Orchestrator exige declaração, enablement e sincronização explícitos, o worker podia falhar antes de processar a fila.
- O manifesto agora declara a capacidade com risco local_compute, orçamento 8 s/64 MiB, checkpoint obrigatório e enabled=false. Total: 16 capacidades, 0 habilitadas.
- O registro falha fechado em manifesto ausente/inválido, capacidade ausente/desabilitada, risco/orçamento incompatível ou conflito do catálogo. Sincronização de catálogo é metadata-only; não habilita execução.
- O worker agora verifica o registro antes de enfileirar o poll task. Quando bloqueado, retorna deferred com correlation ID compatível com o contrato Android; não consulta hardware nem executa tarefas. Itens já pendentes são preservados e re-agendados quando possível.
- Testes cobrem gates, recursos, conflito do catálogo, recibo e preservação da fila. CI pendente.
- Nenhuma capacidade habilitada; nenhum teste em dispositivo foi executado.



## 18. Execução de habilidades procedurais — 23/11/2026

| Capacidade | Componentes | Maturidade atual | Limites |
|---|---|---|---|
| Contrato declarativo de skills | `procedural_skills.py`, `procedural_skills.json` | TESTED_INTEGRATION (PR #160 snapshot CI) | Plano declarativo; sem despacho até PR #162 |
| Binding de adaptadores read-only | `capability_adapters.py`, `ResearchOrchestrator` | IMPLEMENTED; tests added in PR #162 | Só IDs conhecidos e enabled explicitamente; não habilita capacidades |
| Execução procedural read-only | `procedural_skill_executor.py` | TESTED_INTEGRATION (snapshot CI) | Foreground apenas; uma etapa por chamada; sem rede, escrita no workspace ou efeitos externos |
| Checkpoint de adaptador | `ReadOnlyCapabilityAdapters._governed_binding` | IMPLEMENTED; tests added | Guarda hash/metadados do resultado; não é retomada completa da habilidade |
| Integração com núcleo e conectoma | `IntegratedCore`, `CognitiveFabric` | IMPLEMENTED; tests added | A CI da branch ainda precisa validar os novos vínculos |
| Fábrica web/app | skill `web.app_builder`, pipeline E2E/visual | PLANNED | Não implementada; requer staging, execução confiável isolada, build, testes, inspeção visual e empacotamento |

**Gate de produção:** `mahoraga.system_audit` permanece disabled e em maturidade designed. Todas as capacidades de produção permanecem disabled. Testes de execução usam manifesto, store e evidências temporários.

**Evidência:** PR #162 Draft, branch `implementation/procedural-skill-execution-20261123`. A execução privada de CI anterior ao PR terminou sem logs nem steps; isso não comprova falha de código nem aprovação. O snapshot público validou somente a correção do gate anterior (950 passed, 1 skipped, 28 subtests em Python 3.12/3.14; contrato Android aprovado). Snapshot CI no HEAD `2072ced10727b14c7b9d93142e40d22a201f72c1`: 962 passed, 1 skipped e 28 subtests em Python 3.12/3.14; compileall aprovado. Android Runtime Contract para o HEAD anterior `5792a2ab0ebaa9035bb64ef702b88d9468786707` passou compilação Java, unit tests e assembleDebug. A CI privada do HEAD desta PR ainda precisa ser observada. Nenhuma validação no Realme foi realizada.



## 19. Background Companion — auditoria da cadeia intermediária — 23/11/2026

- Branch intermediária `implementation/background-companion-mode-20261122`: 11 commits, 0 atrás do HEAD #156, 8 arquivos alterados; proveniência reconciliada, mesmo autor/committer, sem merges.
- Introduz dois modos distintos: `background_companion` (tela interativa, Mahoraga em segundo plano, até 8 s/64 MiB; 5 s/48 MiB em thermal light) e `background_idle` (tela apagada, até 20 s/128 MiB; 12 s/96 MiB em thermal light).
- Governor, Orchestrator e Scheduler mantêm checkpoint obrigatório, uma tarefa por invocação, sem loop contínuo e fail-closed em contexto desconhecido.
- Auditoria estática registrada em `docs/operations/BACKGROUND_COMPANION_11_COMMIT_AUDIT_20261123.md`; nenhum defeito funcional foi identificado na cadeia.
- Maturidade: TESTED_INTEGRATION em snapshot CI; VALIDATED_REAL permanece pendente. A execução no Realme não foi realizada e o pré-requisito Termux `allow-external-apps` continua não habilitado.
