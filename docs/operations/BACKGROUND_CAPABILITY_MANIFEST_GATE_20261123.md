# Gate de capacidade do Companion — 23/11/2026

**Workstream:** MAH-COMPANION-MANIFEST-GATE-001  
**Base:** PR #160 (Draft)  
**Natureza:** correção de pré-condição e recibo; nenhuma capacidade é ativada.

## Problema confirmado

O worker chamava InternalBackgroundCapabilities.register() incondicionalmente. ResearchOrchestrator.register_capability() exige que a capacidade exista no CapabilityManifest, esteja habilitada, tenha risco compatível e tenha sido sincronizada para o catálogo persistente.

O manifesto anterior declarava 15 capacidades, todas desabilitadas, e não continha internal.adopt_next_inquiry. Assim, o worker podia falhar antes de examinar ou processar a fila. CI de módulos isolados não demonstrava esse caminho de inicialização.

## Correção

- O manifesto agora declara internal.adopt_next_inquiry como implementação existente, risco local_compute, orçamento de 8 s/64 MiB, checkpoint obrigatório e enabled=false.
- O manifesto contém 16 capacidades; 0 habilitadas.
- O registro verifica manifesto válido, declaração, habilitação, risco e orçamento exato antes de qualquer vínculo executável.
- A sincronização do catálogo é explícita e apenas de metadados. Conflitos persistentes bloqueiam o registro.
- Manifesto ausente, inválido, capacidade ausente/desabilitada ou incompatibilidade retorna blocked sem registrar callable.
- O worker verifica o resultado do registro antes de criar uma tarefa de polling. Se bloqueado, retorna deferred e não consulta hardware nem executa código.
- Se já houver trabalho pendente, a fila é preservada e o scheduler tenta agendar uma nova verificação; não descarta nem conclui itens.
- O recibo deferred usa identificador de correlação capability-gate:internal.adopt_next_inquiry, exigido pelo contrato Android. Não representa uma tarefa executada.

## Limites e segurança

- Nenhuma capacidade foi habilitada automaticamente.
- Nenhuma permissão Android, instalação, rede ou escrita no workspace foi autorizada.
- Um registro habilitado no futuro ainda precisará de validação do catálogo, Dharma, Governor, recibo, testes e autorização explícita.
- A mudança não comprova execução no Realme 14 5G.
- A ativação permanece fora do escopo desta PR.

## Testes adicionados

Cobrem registro permitido quando manifesto habilitado e sincronizado, bloqueio quando ausente/desabilitado, incompatibilidade de risco/orçamento, conflito do catálogo, recibo deferred e preservação/agendamento de fila pendente.
