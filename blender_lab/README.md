# Laboratório Mahoraga × Blender

**Workstream:** BLENDER-LAB-001  
**Estado:** scripts adicionados; validação no Blender do aparelho pendente  
**Princípio:** primeiro observar, depois alterar uma fixture identificada, medir e reverter.

## Objetivo

Usar o Blender como primeiro ambiente físico-simulado para testar o ciclo de aprendizagem do Mahoraga. A sequência separa leitura da cena, alteração controlada e rollback. Nenhum script inicia renderização, salva o arquivo .blend ou executa código remoto.

## Preparação obrigatória

1. Abra o projeto de teste numa cópia do arquivo .blend. Não use o arquivo de trabalho original.
2. Guarde uma cópia intacta com outro nome, por exemplo `mahoraga_blender_baseline.blend`.
3. Abra a área **Scripting** e crie um Text Block. Copie o conteúdo do script indicado em cada etapa para o Text Block e execute-o pelo botão **Run Script**.
4. Guarde a saída entre os marcadores `MAHORAGA_..._BEGIN` e `MAHORAGA_..._END`. Ela é JSON de observação; não é, por si só, prova de que o Mahoraga compreendeu a cena.

## Sequência de ensaio

### 01 — Inspecionar a cena sem modificá-la

Arquivo: `01_readonly_scene_probe.py`

Executar antes de qualquer alteração. O script regista versão do Blender, cena, render engine, intervalo de frames, câmera ativa, objetos, tipos, posição, rotação, escala, dimensões, malha, modificadores, materiais e dados básicos de câmera/luz.

**Critério de aceitação:** o JSON é válido; os totais e nomes correspondem ao que aparece na cena; os campos `scene_modified`, `blend_saved` e `render_started` permanecem `false`.

### 02 — Criar fixture isolada

Arquivo: `02_create_reversible_fixture.py`

Cria a coleção `MAHORAGA_LAB_FIXTURE` com marcador `mahoraga-blender-fixture-v1`, contendo um cubo, uma câmera e uma luz de área. O script recusa criar a fixture se a coleção já existir. Não altera a câmera ativa, a configuração de render, o frame atual ou o arquivo salvo.

**Critério de aceitação:** a saída declara três objetos criados; a cena original continua presente; só aparece uma coleção nova com o marcador esperado. Não iniciar render nesta primeira etapa.

### 03 — Inspecionar novamente

Executar novamente `01_readonly_scene_probe.py`.

Comparar com a saída inicial. A diferença esperada é apenas a coleção e os três objetos identificados como fixture. Se houver diferenças adicionais, parar e inspecionar antes de prosseguir.

### 04 — Remover a fixture

Arquivo: `03_remove_reversible_fixture.py`

O script exige o marcador exato na coleção e em cada objeto. Só remove objetos da fixture que ainda contenham o marcador proprietário correto. Objetos sem o marcador não são removidos. A coleção só é eliminada quando fica vazia.

**Critério de aceitação:** três objetos removidos; nenhuma entidade externa removida; coleção vazia removida. Se o marcador não corresponder, a operação é recusada.

### 05 — Confirmar o rollback

Executar de novo `01_readonly_scene_probe.py` e comparar com o baseline.

**Critério de aceitação:** nomes, tipos e totais da cena regressam ao estado inicial. Diferenças residuais devem ser explicadas antes de considerar o ensaio aprovado. Fechar sem salvar e reabrir a cópia baseline para confirmar que o arquivo persistido não foi alterado.

## O que o Mahoraga deve aprender neste ensaio

O objetivo não é apenas identificar objetos. O experimento procura medir se o sistema consegue:

- construir um modelo estruturado da cena;
- distinguir observações de hipóteses e de ações executadas;
- prever o efeito de uma operação antes de a propor;
- escolher apenas a fixture pertencente ao ensaio;
- comparar estado esperado e observado;
- identificar desvios e explicar por que o resultado não correspondeu à previsão;
- conservar o procedimento validado como habilidade candidata, sem o promover automaticamente.

Um único ensaio bem-sucedido demonstra somente esse procedimento e essa versão do Blender. Não demonstra compreensão geral de 3D, física ou autonomia.

## Limites e segurança

- Estes scripts usam a API `bpy` dentro do próprio Blender. Ainda não existe integração automática testada entre o telefone e o Blender.
- Não executar código arbitrário recebido pela ponte Blender. O executor Python do Blender não é uma sandbox.
- Não habilitar uma porta de rede, bridge ou serviço residente para este ensaio.
- Não usar `02_create_reversible_fixture.py` numa cena que já tenha uma coleção com o mesmo nome; o script recusa esse caso.
- Não executar a limpeza se a coleção ou os marcadores tiverem sido alterados manualmente.
- Não salvar a cena durante o ensaio. O rollback é intencional e deve ser observado antes de qualquer persistência.
- Se o Blender móvel não expuser a área Scripting ou a execução de Text Blocks, o ensaio precisa ser adaptado à interface disponível; não instalar add-ons ou alterar permissões do Android para contornar isso.

## Artefatos

- `01_readonly_scene_probe.py` — inspeção read-only.
- `02_create_reversible_fixture.py` — criação limitada de fixture.
- `03_remove_reversible_fixture.py` — rollback por marcador de propriedade.
- `tests/test_blender_lab_scripts.py` — verificações estáticas de sintaxe, marcadores e ausência de operações proibidas no probe.

**Maturidade:** IMPLEMENTED / STATIC TESTS ADDED / BLENDER DEVICE RUN PENDING.

## Estado da ponte automatizada V2

A ponte automatizada V2 está temporariamente restrita a `scene.inspect`. Tarefas de criação/transformação, geração de cena, render, salvamento de projeto e execução Python não são aceitas pela fila remota. Isso evita que um pedido remoto altere a cena ou o arquivo sem uma autorização específica e verificável.

A execução Python permanece bloqueada: o fluxo atual usa um booleano `human_approved` em uma camada, mas o Dharma exige um atestado humano de uso único vinculado ao conteúdo; o servidor também não possui um recibo verificável de ponta a ponta para o add-on. `BlenderPythonExecutor` usa `exec` com builtins completos e não é sandbox. Não habilitar essa rota até integrar emissão/verificação do atestado, recibo ligado ao hash do código, aprovação explícita no painel Blender, cancelamento e testes de segurança.

O add-on V2 ainda não foi testado em uma instalação real do Blender. Os três scripts manuais deste laboratório são independentes da ponte e continuam sendo a única sequência de alteração reversível atualmente documentada.
