# Execução procedural governada — v1

**Workstream:** MAH-SKILL-FACTORY-001  
**Data:** 2026-11-23  
**Base:** PR #161 — gate do Companion por manifesto  
**Implementação:** PR #162 — execução procedural governada  
**Maturidade:** implementação adicionada; CI desta branch pendente

## Objetivo

Transformar o plano declarativo de uma habilidade em execução real e verificável, reutilizando o mesmo `IntegratedCore`, `CapabilityManifest`, `ReadOnlyCapabilityAdapters`, `ResearchOrchestrator`, `AutonomyGovernor`, `Dharma` e `KnowledgeStore`.

A habilidade não carrega código, não importa módulos e não executa comandos. Cada etapa referencia um identificador de capacidade já declarado e é despachada exclusivamente pelo `ResearchOrchestrator`.

## Fluxo

1. Validar o pacote procedural e o ID da habilidade.
2. Registrar somente adaptadores read-only cujo manifesto declare `enabled=true`.
3. Sincronizar metadados do manifesto e bloquear conflitos de catálogo.
4. Consultar a prontidão da habilidade, incluindo maturidade, evidência verificável, manifesto, bindings e ferramentas requeridas.
5. Validar entradas e resolver bindings `input.*` e `step.*.result`.
6. Executar uma etapa por chamada ao Orchestrator, com um único permit e contexto foreground.
7. Validar o recibo de conclusão e o checkpoint quando exigido.
8. Persistir eventos de início, etapa concluída, bloqueio, falha ou conclusão; os eventos guardam hashes e metadados, não duplicam o payload integral dos resultados.
9. Retornar relatório com resultados parciais em caso de falha, sem declarar conclusão indevida.

## Limites v1

- Apenas habilidades `read_only`.
- Apenas `foreground`; Companion/background exige agendamento e retomada por etapa e permanece fora do escopo.
- Cada capacidade precisa estar habilitada explicitamente no manifesto, ter risco read-only e orçamento válido.
- Cada etapa deve caber no orçamento total da habilidade.
- Sem rede, câmera, microfone, instalação, mudanças Android, efeitos externos, escrita no workspace ou alteração de projeto.
- O adaptador registra checkpoint compacto contendo ID da capacidade, SHA-256 do resultado, tamanho e tipo. O resultado não é copiado para o checkpoint.
- A execução não promove maturidade, não registra evidência operacional automaticamente e não habilita a própria habilidade.

## Produção permanece bloqueada

A configuração de produção mantém:

- `mahoraga.system_audit.enabled=false`;
- maturidade `designed`;
- todas as capacidades do `CapabilityManifest` desabilitadas por padrão.

Os testes podem habilitar capacidades e habilidades apenas em fixtures temporárias, com store isolado. O teste de produção confirma que uma chamada ao executor resulta em `blocked`, sem registrar bindings executáveis no catálogo e sem executar etapas.

## Evidência e limites

A implementação inclui testes para:
- execução ordenada e resolução de inputs;
- validação de recibos;
- preservação de etapas concluídas após falha;
- bloqueio por orçamento;
- recusa do modo background;
- checkpoint compacto de adaptadores;
- registro apenas de capacidades habilitadas;
- integração do executor no conectoma e no relatório do IntegratedCore;
- bloqueio por padrão da habilidade de produção.

A aprovação da CI desta branch ainda precisa ser observada. CI não comprova execução no Realme. O executor procedural não é ainda uma fábrica de sites ou aplicativos: a habilidade `web.app_builder` e a integração com staging/validação visual continuam futuras.
