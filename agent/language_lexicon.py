"""Recursos lexicais versionados para expansão controlada do português brasileiro.

As famílias abaixo projetam variantes e sinônimos para features já existentes.
Elas ampliam cobertura lexical, mas NÃO comprovam por si só que um texto
pertença ao domínio do Mahoraga. A fronteira de domínio fica no analyzer.
"""

LEXICON_VERSION = "pt-BR-2026.11.15.1"

LEXICAL_FAMILIES = {
    "estado": (
        "status", "estado", "estados", "situação", "situacao", "situaçao",
        "saúde", "saude", "integridade", "disponibilidade",
        "availability", "health", "state",
    ),
    "condição": (
        "condicao", "condiçao", "condições", "condicoes", "condition",
        "conditions",
    ),
    "funcionamento": (
        "funciona", "funcionam", "funcionando", "funcionamento",
        "operando", "opera", "operam", "operacional", "operacionais",
        "estável", "estavel", "estabilidade", "instável", "instavel",
        "ativo", "ativa", "ativos", "ativas", "inativo", "inativa",
        "inativos", "inativas", "online", "offline", "disponível",
        "disponivel", "disponíveis", "disponiveis", "indisponível",
        "indisponivel", "lento", "lenta", "travando", "travado",
        "travada", "falhando", "falha", "falhas", "erro", "erros",
        "problema", "problemas", "saudável", "saudavel", "parado",
        "parada", "suspenso", "suspensa", "running", "working",
        "available", "unavailable", "stable", "unstable",
    ),
    "plataforma": (
        "sistema", "sistemas", "plataforma", "plataformas",
        "núcleo", "nucleo", "núcleos", "nucleos", "processo", "processos",
        "aplicação", "aplicacao", "aplicações", "aplicacoes",
        "aplicativo", "aplicativos", "app", "apps", "programa",
        "programas", "software", "system", "systems", "platform",
        "process", "application",
    ),
    "serviços": ("serviço", "servico", "servicos", "service", "services"),
    "relatório": (
        "relatorio", "relatórios", "relatorios", "diagnóstico",
        "diagnostico", "indicador", "indicadores", "métrica",
        "métricas", "metricas", "medição", "medicoes", "medição",
        "auditoria", "audit", "report", "reports", "diagnosis",
    ),
    "resumo": (
        "resumos", "panorama", "panoramas", "quadro", "balanço",
        "balanco", "balanços", "balancos", "síntese", "sintese",
        "sumário", "sumario", "overview", "summary",
    ),
    "cena": (
        "blender", "cena", "cenas", "cenário", "cenario",
        "cenários", "cenarios", "viewport", "viewports", "outliner",
        "editor", "edição", "edicao", "modelagem", "modelação",
        "modelacao", "render", "renderização", "renderizacao",
        "renderizar", "renderizada", "renderizado", "rendering",
        "scene", "scenes", "collection", "coleção", "colecao",
        "coleções", "colecoes", "workspace", "workspaces", "cne", "blnder",
    ),
    "objetos": (
        "objeto", "objetos", "item", "itens", "elemento", "elementos",
        "componente", "componentes", "entidade", "entidades",
        "malha", "malhas", "mesh", "meshes", "vértice", "vertices",
        "vértices", "vertice", "aresta", "arestas", "face", "faces",
        "polígono", "poligono", "polígonos", "poligonos", "peça",
        "peças", "peca", "pecas", "carregado", "carregada",
        "carregados", "carregadas", "loaded", "object", "objects", "vertex",
        "vertices", "edge", "edges", "polygon", "polygons", "part",
        "parts", "asset", "assets", "geometry", "objto", "objtos", "objeo",
    ),
    "composição": (
        "composicoes", "composicao", "montagem", "montagens",
        "estrutura", "estruturas", "hierarquia", "hierarquias",
        "disposição", "disposicao", "organização", "organizacao",
        "arranjo", "arranjos", "layout", "layouts", "composition",
        "assembly", "arrangement",
    ),
}

TOKEN_ALIASES = {}
for canonical, aliases in LEXICAL_FAMILIES.items():
    TOKEN_ALIASES[canonical] = canonical
    for alias in aliases:
        previous = TOKEN_ALIASES.get(alias)
        if previous is not None and previous != canonical:
            raise RuntimeError(
                f"Alias lexical ambíguo: {alias!r} -> {previous!r}/{canonical!r}"
            )
        TOKEN_ALIASES[alias] = canonical
