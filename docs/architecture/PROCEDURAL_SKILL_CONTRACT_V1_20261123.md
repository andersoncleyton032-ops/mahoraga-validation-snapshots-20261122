# Contrato de habilidades procedurais — v1

**Workstream:** MAH-SKILL-FACTORY-001  
**Data:** 2026-11-23  
**Base:** PR #159 (hardening/worker-fencing-and-recovery-20261123)  
**Natureza:** primeiro incremento executável do registro procedural; não é uma fábrica de software completa.

## 1. Decisão de arquitetura

Uma habilidade é um procedimento declarativo, versionado e verificável que referencia capacidades já existentes. Ela não é um agente, personalidade, modelo neural ou subsistema cognitivo separado.

A composição permanece no IntegratedCore. O contrato reutiliza:

- CapabilityManifest para declarar operações, risco e maturidade;
- ResearchOrchestrator para os vínculos executáveis explicitamente confiáveis;
- KnowledgeStore para registrar decisões e resultados;
- Dharma e AutonomyGovernor para autorização e orçamento;
- EngineeringWorkbenchV2 para staging, validação e promoção de alterações de projeto.

O pacote procedural não importa módulos, não carrega callables e não executa comandos.

## 2. Implementação v1

Arquivos:

- agent/procedural_skills.py
- config/procedural_skills.json
- tests/test_procedural_skills.py
- integração em agent/integration_core.py

O registry:

1. carrega JSON versionado com limites de tamanho, campos estritos, chaves duplicadas rejeitadas e valores finitos;
2. rejeita campos executáveis aninhados, riscos não permitidos, permissões fora da allowlist e ambientes que declarem rede ou mutações externas;
3. valida orçamento por invocação (até 20 s, 256 MiB e 32 etapas);
4. valida IDs, referências às capacidades declaradas, compatibilidade de risco e fluxo de dados entre etapas;
5. calcula prontidão somente quando habilidade, maturidade, evidências verificadas por provedor local confiável, capacidades do manifesto, vínculos do Orchestrator e ferramentas requeridas estão disponíveis;
6. fornece correspondência lexical determinística de intenções como baseline, sem alegar recrutamento semântico;
7. produz um plano declarativo bloqueado ou elegível, sem despachar etapas;
8. pode registrar o plano como evento no KnowledgeStore, sem declarar execução.

O IntegratedCore instancia o registry com as mesmas instâncias compartilhadas de Store, Manifest e Orchestrator e inclui seu estado no relatório integrado.

## 3. Primeiro pacote

mahoraga.system_audit é uma habilidade de auditoria somente leitura que descreve três etapas:

- hardware.snapshot;
- introspection.capability_audit;
- memory.history_read.

Ela está enabled=false e maturity_state=designed. As três capacidades referenciadas também estão desabilitadas no manifesto atual. Portanto, o resultado esperado é blocked, sem execução. Isso é intencional: o pacote demonstra o contrato sem ativar capacidades do sistema.

## 4. Limites explícitos

Ainda não existe:

- execução automática de uma sequência de etapas;
- recrutamento semântico ou seleção cognitiva contextual;
- adaptador de geração de código conectado ao runtime;
- validação independente de artefatos produzidos por uma habilidade;
- sandbox de sistema operacional;
- pipeline completo de build, E2E, QA visual, empacotamento e deploy de sites/apps.

A correspondência lexical é apenas um baseline reproduzível. Maturidade operacional exige um provedor confiável injetado que implemente verify_local(reference); sem ele, a habilidade permanece bloqueada. Um plano elegível não é prova de execução. O staging do Workbench não é isolamento de código arbitrário.

## 5. Próxima sequência de desenvolvimento

1. Validar esta implementação em CI e corrigir regressões.
2. Criar um executor procedural que consuma no máximo uma etapa por invocação, reutilizando lease, checkpoint, recibo e ResearchOrchestrator.
3. Definir contratos de entrada/saída e verificadores independentes para resultados e artefatos.
4. Construir web.app_builder em staging, começando por um site pequeno, com build reproduzível, testes funcionais e QA visual.
5. Reutilizar o pipeline para API e Android; publicação, assinatura, instalação e deploy continuam exigindo autorização.

Nenhuma capacidade do manifesto existente é habilitada por esta mudança.
