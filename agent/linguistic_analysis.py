"""Análise linguística determinística compartilhada pelo núcleo de linguagem.

Esta camada trata sinais de controle, temporalidade, ambiguidade e domínio
antes de permitir que a classificação neural produza uma intenção acionável.
Não é um modelo de linguagem geral nem executa operações.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from agent.language_lexicon import (
    LEXICON_VERSION as LEXICAL_VERSION,
    TOKEN_ALIASES as LEXICAL_TOKEN_ALIASES,
)


class LinguisticAnalyzer:
    VERSION = "0.2.0"
    LEXICON_VERSION = LEXICAL_VERSION
    TOKEN_ALIASES = LEXICAL_TOKEN_ALIASES
    MAX_TEXT_LENGTH = 500

    # Termos explícitos são identificadores; palavras genéricas precisam de contexto.
    EXPLICIT_DOMAIN_ANCHORS = {
        "mahoraga", "blender", "viewport", "outliner",
    }

    STATUS_TARGET_ANCHORS = {
        "sistema", "sistemas", "plataforma", "núcleo", "nucleo",
        "núcleos", "nucleos", "serviço", "serviços", "servico",
        "servicos", "processo", "processos", "recurso", "recursos",
        "aplicação", "aplicacao", "aplicativo", "aplicativos",
        "software",
    }

    STATUS_STATE_ANCHORS = {
        "status", "estado", "estados", "situação", "situacao",
        "situaçao", "condição", "condicao", "condiçao", "saúde",
        "saude", "integridade", "funcionamento", "operacional",
        "operação", "operacao", "diagnóstico", "diagnostico",
        "indicador", "indicadores", "desempenho", "andamento",
        "estabilidade", "atualização", "atualizacao",
        "disponibilidade", "relatório", "relatorio", "erro", "erros",
        "falha", "falhas", "ativo", "ativa", "ativos", "ativas",
        "inativo", "inativa", "inativos", "indisponível",
        "indisponivel", "disponível", "disponivel", "funciona",
        "funcionando", "operando", "travando", "travado", "travada",
        "lento", "lenta", "instável", "instavel", "está", "esta",
        "panorama", "resumo", "quadro", "balanço", "balanco",
    }

    BLENDER_ENTITY_ANCHORS = {
        "cena", "cenas", "objeto", "objetos", "geometria", "malha",
        "malhas", "mesh", "meshes", "vértice", "vértices", "vertice",
        "vertices", "aresta", "arestas", "face", "faces", "polígono",
        "poligono", "polígonos", "poligonos", "render", "renderização",
        "renderizacao", "renderizar", "viewport", "outliner", "coleção",
        "colecao", "material", "textura", "câmera", "camera",
        "modelagem", "modelo",
    }

    BLENDER_CONTEXT_ANCHORS = {
        "composição", "composicao", "elemento", "elementos",
        "componente", "componentes", "projeto", "estrutura",
        "montagem", "gráfica", "grafica", "visual", "ambiente",
        "disposição", "disposicao", "organização", "organizacao",
        "visuais", "visualmente",
        "modelado", "cenário", "cenario", "conteúdo", "conteudo",
        "hierarquia", "editor", "edição", "edicao", "tridimensional",
        "layout", "layouts",
    }

    # Mantidos como nomes públicos por compatibilidade: somente identificadores
    # realmente explícitos ficam no grupo STRONG.
    STRONG_DOMAIN_ANCHORS = EXPLICIT_DOMAIN_ANCHORS
    WEAK_DOMAIN_ANCHORS = (
        STATUS_TARGET_ANCHORS
        | STATUS_STATE_ANCHORS
        | BLENDER_ENTITY_ANCHORS
        | BLENDER_CONTEXT_ANCHORS
    )
    DOMAIN_ANCHORS = STRONG_DOMAIN_ANCHORS | WEAK_DOMAIN_ANCHORS

    # Contextos externos conhecidos são usados como casos adversariais.
    # Um termo polissêmico não deve abrir o domínio por coincidência lexical.
    DOMAIN_EXCLUSION_TERMS = {
        "solar", "fotossíntese", "fotossintese", "naturais", "natural",
        "política", "politica", "político", "politico", "matemático",
        "matematico", "matemática", "matematica", "texto", "textos",
        "judicial", "econômico", "economico", "digestivo", "digestiva",
        "trânsito", "transito", "hídricos", "hidricos", "hídrico",
        "hidrico", "amazonas", "molecular", "meteorológica",
        "meteorologica", "meteorológico", "meteorologico", "química",
        "quimica", "social", "estatístico", "estatistico",
        "estatística", "estatistica", "aprendizagem", "humana",
        "humanas", "mineral", "minerais", "celular", "escolar",
        "pública", "publica", "jurídica", "juridica", "jurídico",
        "juridico", "empresa", "conservação", "conservacao", "prédio",
        "predio", "atômico", "atomico", "fabricação", "fabricacao",
        "hídrica", "hidrica", "respiratório", "respiratorio",
        "poema", "poemas", "poesia", "musical", "música", "musica",
        "canção", "cancao",
        "reciclagem", "negócio", "negocio", "loja", "evolução",
        "evolucao", "espécies", "especies", "climáticas", "climaticas",
        "internacional", "país", "pais",
    }

    INTENT_ANCHORS = {
        "status": STATUS_TARGET_ANCHORS | STATUS_STATE_ANCHORS | {"mahoraga"},
        "blender.inspect": (
            BLENDER_ENTITY_ANCHORS
            | BLENDER_CONTEXT_ANCHORS
            | {"blender", "viewport", "outliner"}
        ),
    }

    ACTION_WORDS = {
        "analise", "analisa", "analisei", "analisar", "analisado",
        "analisada", "analisando", "inspecione", "inspecionar",
        "inspecionei", "inspecionado", "inspecionada", "verifique",
        "verificar", "verifica", "verificado", "verificada", "confira",
        "conferir", "conferido", "examine", "examinar", "olhe", "olhar",
        "olhada", "veja", "cuidar", "cuide", "faça", "fazer", "faz",
        "inspeção", "observe", "observar", "revise", "revisar",
        "investigue", "investigar", "consulte", "consultar", "informe",
        "informar", "mostre", "mostrar", "execute", "executar", "inicie",
        "iniciar", "rode", "rodar", "crie", "criar", "cheque", "checar",
        "checa", "chequei", "checado", "conferir", "liste", "listar",
        "listem", "listei", "enumere", "enumerar", "aponte", "apontar",
        "identifique", "identificar", "identificou", "detecte", "detectar",
        "detecte", "mapeie", "mapear", "avalie", "avaliar", "diagnostique",
        "diagnosticar", "compare", "comparar", "exiba", "exibir",
        "apresente", "apresentar", "obtenha", "obter", "recupere",
        "recuperar", "atualize", "atualizar", "resuma", "resumir",
        "descreva", "descrever", "explique", "explicar", "visualize",
        "visualizar", "revele", "revelar", "solucione", "solucionar",
        "corrija", "corrigir", "conserte", "consertar", "repare",
        "reparar", "otimize", "otimizar", "configure", "configurar",
        "instale", "instalar", "desinstale", "desinstalar", "pause",
        "pausar", "retome", "retomar", "continue", "continuar", "gere",
        "gerar", "construa", "construir", "desenvolva", "desenvolver",
        "implemente", "implementar", "modifique", "modificar", "altere",
        "alterar", "remova", "remover", "adicione", "adicionar",
        "integre", "integrar", "sincronize", "sincronizar", "teste",
        "testar", "valide", "validar", "confirme", "confirmar", "prove",
        "provar", "demonstre", "demonstrar",
    }

    ACTION_STEMS = (
        "analis", "inspec", "verific", "confer", "examin", "olh",
        "cuid", "observ", "revis", "investig", "execut", "consult",
        "inform", "mostr", "inici", "rod", "cri", "chec", "list",
        "enumer", "identific", "detect", "mape", "avali", "diagnostic",
        "compar", "exib", "apresent", "obtenh", "recuper", "atualiz",
        "resum", "descrev", "explic", "visualiz", "revel", "solucion",
        "corrig", "consert", "repar", "otimiz", "configur", "instal",
        "desinstal", "paus", "retom", "continu", "ger", "constru",
        "desenvolv", "implement", "modific", "alter", "remov",
        "adicion", "integr", "sincroniz", "test", "valid", "confirm",
        "demonstr",
    )

    REQUEST_WORDS = {
        "quero", "preciso", "gostaria", "poderia", "solicito",
        "peço", "peco", "desejo", "pretendo", "necessito",
        "consegue", "conseguiria", "favor", "gostava",
    }

    NEGATION_SKIP = {"apenas", "só", "somente"}
    NEGATION_WORDS = {"não", "nunca", "jamais"}

    NEGATION_PHRASES = (
        "pare de ", "pare de",
        "deixe de ", "deixa de ",
        "sem executar", "sem fazer",
    )

    PAST_PHRASES = (
        "ontem",
        "mais cedo",
        "anteriormente",
        "na sessão passada",
        "na sessao passada",
        "na sessão anterior",
        "na sessao anterior",
        "na última sessão",
        "na ultima sessao",
        "na semana passada",
        "no ciclo anterior",
    )

    FUTURE_PHRASES = (
        "amanhã",
        "amanha",
        "depois que terminar",
        "na próxima sessão",
        "na proxima sessao",
        "mais tarde",
        "futuramente",
        "quando puder",
        "assim que terminar",
        "após terminar",
        "apos terminar",
        "depois de terminar",
        "na semana que vem",
        "na próxima semana",
        "na proxima semana",
        "no próximo ciclo",
        "no proximo ciclo",
        "depois da reunião",
        "depois da reuniao",
        "quando a atualização terminar",
        "quando a atualizacao terminar",
    )

    CONDITIONAL_PATTERNS = (
        r"\bse\s+(?:eu\s+)?(?:pedir|solicitar|autorizar)\b",
        r"\bcaso\s+(?:seja\s+necess[aá]rio|precise|necessite)\b",
        r"\bse\s+(?:for\s+)?necess[aá]rio\b",
        r"\bquando\s+(?:eu\s+)?(?:pedir|solicitar|autorizar)\b",
        r"\bse\s+houver\s+(?:autoriza[cç][aã]o|permiss[aã]o)\b",
        r"\bcaso\s+eu\s+confirme\b",
        r"\bse\s+for\s+permitido\b",
    )

    VAGUE_PHRASES = (
        "aquela coisa", "essa coisa", "alguma coisa",
        "o negócio", "o negocio", "aquela situação",
        "aquela situacao", "esse negócio", "esse negocio",
        "aquela parte", "essa parte", "aquele assunto",
        "essa questão", "essa questao",
    )

    VAGUE_WORDS = {"isso", "aquilo"}

    def __init__(self):
        self._anchors = tuple(sorted(self.DOMAIN_ANCHORS))

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.casefold().split())

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)

    @classmethod
    def _is_action(cls, token: str) -> bool:
        return (
            token in cls.ACTION_WORDS
            or any(token.startswith(stem) for stem in cls.ACTION_STEMS)
        )

    @classmethod
    def _has_action(cls, tokens: list[str]) -> bool:
        return any(cls._is_action(token) for token in tokens)

    def _canonical_anchor(self, token: str) -> str | None:
        if token in self.DOMAIN_ANCHORS:
            return token
        if len(token) < 5:
            return None

        candidates = []
        for anchor in self._anchors:
            if abs(len(anchor) - len(token)) > 2:
                continue
            score = SequenceMatcher(None, token, anchor).ratio()
            if score >= 0.82:
                candidates.append((score, anchor))

        if not candidates:
            return None

        candidates.sort(reverse=True)
        best_score, best_anchor = candidates[0]
        if len(candidates) > 1 and best_score - candidates[1][0] < 0.05:
            return None
        return best_anchor

    def project_token(self, token: str, vocabulary) -> str | None:
        """Mapeia sinônimos/erros inequívocos para uma feature já treinada."""
        if token in vocabulary:
            return token

        direct_alias = self.TOKEN_ALIASES.get(token)
        if direct_alias in vocabulary:
            return direct_alias

        canonical = self._canonical_anchor(token)
        if canonical is None:
            return None
        if canonical in vocabulary:
            return canonical

        alias = self.TOKEN_ALIASES.get(canonical)
        if alias in vocabulary:
            return alias
        return None

    def _domain_matches(self, text: str) -> tuple[bool, bool]:
        """Retorna evidência contextual para status e inspeção do Blender.

        A palavra-chave isolada não basta, exceto identificadores explícitos
        (Blender/viewport/outliner) e o comando curto "status".
        """
        if not isinstance(text, str):
            return False, False

        tokens = set()
        for token in self._tokens(text):
            canonical = self._canonical_anchor(token)
            if canonical is None:
                canonical = self.TOKEN_ALIASES.get(token, token)
            tokens.add(canonical)

        explicit_blender = bool(
            tokens & {"blender", "viewport", "outliner"}
        )
        if tokens & self.DOMAIN_EXCLUSION_TERMS and not explicit_blender:
            return False, False

        status_targets = tokens & self.STATUS_TARGET_ANCHORS
        status_states = tokens & self.STATUS_STATE_ANCHORS
        status_match = bool(status_targets and status_states)

        # Dois sinais de estado podem formar uma consulta operacional implícita.
        if len(status_states) >= 2:
            status_match = True

        # "Recursos do núcleo/sistema" é uma combinação contextual válida,
        # mas "recursos naturais" é bloqueado pelo filtro de tópico externo.
        if (
            tokens & {"recurso", "recursos"}
            and tokens & {"núcleo", "nucleo", "sistema", "plataforma", "mahoraga"}
        ):
            status_match = True

        if tokens == {"status"}:
            status_match = True
        if "mahoraga" in tokens:
            status_match = True

        blender_entities = tokens & self.BLENDER_ENTITY_ANCHORS
        blender_context = tokens & self.BLENDER_CONTEXT_ANCHORS
        blender_match = (
            explicit_blender
            or len(blender_entities) >= 2
            or bool(blender_entities and blender_context)
            or len(blender_context) >= 3
        )

        # "inspecionar/examinar/revisar a composição" é uma combinação
        # contextual conhecida do domínio visual; a palavra isolada não basta.
        inspection_verbs = {
            "inspecione", "inspecionar", "examine", "examinar",
            "revise", "revisar", "verifique", "verificar",
            "confira", "conferir", "observe", "observar",
        }
        if (
            tokens & {"composição", "composicao"}
            and tokens & inspection_verbs
        ):
            blender_match = True

        scene_actions = {
            "analise", "analisa", "analisar", "inspecione",
            "inspecionar", "examine", "examinar", "observe",
            "observar", "revise", "revisar", "renderize",
            "renderizar", "liste", "listar",
        }
        if tokens & {"cena", "cenas"} and tokens & scene_actions:
            blender_match = True

        # Um alvo genérico ("objetos") só pode receber hint Blender quando
        # houver intenção futura/condicional explícita; nunca libera execução.
        normalized = self._normalize(text)
        future_object_target = (
            self._has_future_reference(normalized)
            and bool(tokens & {"objeto", "objetos"})
            and self._has_action(list(tokens))
        )
        if future_object_target:
            blender_match = True
        return status_match, blender_match

    def infer_intent_hint(self, text: str) -> str | None:
        """Infere o alvo de uma intenção adiada sem autorizar execução."""
        status_match, inspect_match = self._domain_matches(text)
        if status_match and not inspect_match:
            return "status"
        if inspect_match and not status_match:
            return "blender.inspect"
        return None

    def has_domain_anchor(self, text: str) -> bool:
        status_match, inspect_match = self._domain_matches(text)
        return status_match or inspect_match

    @classmethod
    def _has_negation(cls, normalized: str, tokens: list[str]) -> bool:
        if any(phrase in normalized for phrase in cls.NEGATION_PHRASES):
            return cls._has_action(tokens)

        for index, token in enumerate(tokens):
            if token not in cls.NEGATION_WORDS:
                continue
            following = tokens[index + 1:index + 7]
            if not following:
                continue
            if token == "não" and following[0] in cls.NEGATION_SKIP:
                continue
            if cls._has_action(following):
                return True
        return False

    @classmethod
    def _has_past_reference(cls, normalized: str) -> bool:
        return any(phrase in normalized for phrase in cls.PAST_PHRASES)

    @classmethod
    def _has_future_reference(cls, normalized: str) -> bool:
        if any(phrase in normalized for phrase in cls.FUTURE_PHRASES):
            return True
        return any(
            re.search(pattern, normalized)
            for pattern in cls.CONDITIONAL_PATTERNS
        )

    @classmethod
    def _has_vague_reference(cls, normalized: str, tokens: list[str]) -> bool:
        return (
            any(phrase in normalized for phrase in cls.VAGUE_PHRASES)
            or any(token in cls.VAGUE_WORDS for token in tokens)
        )

    def analyze(self, text: str) -> dict:
        if not isinstance(text, str) or not text.strip():
            return {
                "decision": "abstain",
                "reason": "invalid_text",
                "signals": ["invalid_text"],
                "supported_domain": False,
            }

        normalized = self._normalize(text)
        if len(normalized) > self.MAX_TEXT_LENGTH:
            return {
                "decision": "abstain",
                "reason": "text_too_long",
                "signals": ["text_too_long"],
                "supported_domain": False,
            }

        tokens = self._tokens(normalized)
        if not tokens:
            return {
                "decision": "abstain",
                "reason": "no_tokens",
                "signals": ["no_tokens"],
                "supported_domain": False,
            }

        has_action = self._has_action(tokens)
        has_request = has_action or any(
            token in self.REQUEST_WORDS for token in tokens
        )
        supported_domain = self.has_domain_anchor(normalized)
        signals = []

        if self._has_negation(normalized, tokens) and has_action:
            return {
                "decision": "abstain",
                "reason": "negated_action",
                "signals": ["negation", "action"],
                "supported_domain": supported_domain,
            }

        if self._has_past_reference(normalized):
            return {
                "decision": "abstain",
                "reason": "past_reference",
                "signals": ["past_reference"],
                "supported_domain": supported_domain,
            }

        future = self._has_future_reference(normalized)
        if future:
            signals.append("future_or_conditional")

        vague = self._has_vague_reference(normalized, tokens)
        uncertain = "talvez" in tokens

        if has_action and (vague or uncertain):
            if vague:
                signals.append("vague_reference")
            if uncertain:
                signals.append("uncertainty")
            return {
                "decision": "clarify",
                "reason": "ambiguous_reference",
                "signals": signals or ["ambiguity"],
                "supported_domain": supported_domain,
            }

        if future and has_request:
            if supported_domain:
                return {
                    "decision": "defer",
                    "reason": "future_or_conditional_intention",
                    "signals": signals + ["action_or_request", "domain_anchor"],
                    "supported_domain": True,
                }
            return {
                "decision": "clarify",
                "reason": "future_request_without_specific_target",
                "signals": signals + ["action_or_request"],
                "supported_domain": False,
            }

        if not supported_domain:
            return {
                "decision": "abstain",
                "reason": "unsupported_domain",
                "signals": ["no_supported_domain_anchor"],
                "supported_domain": False,
            }

        return {
            "decision": "continue",
            "reason": "supported_domain",
            "signals": ["domain_anchor"],
            "supported_domain": True,
        }
