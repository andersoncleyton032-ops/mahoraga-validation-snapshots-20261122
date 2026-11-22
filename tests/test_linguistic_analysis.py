from agent.linguistic_analysis import LinguisticAnalyzer


def test_negation_blocks_action():
    result = LinguisticAnalyzer().analyze("Não quero que você inspecione o Blender.")
    assert result["decision"] == "abstain"
    assert result["reason"] == "negated_action"


def test_negation_scope_does_not_block_not_only_construction():
    result = LinguisticAnalyzer().analyze(
        "Não apenas consulte o relatório de integridade."
    )
    assert result["decision"] == "continue"


def test_past_reference_is_not_an_immediate_command():
    result = LinguisticAnalyzer().analyze(
        "O sistema foi verificado mais cedo."
    )
    assert result["decision"] == "abstain"
    assert result["reason"] == "past_reference"


def test_future_intention_is_deferred_when_target_is_supported():
    result = LinguisticAnalyzer().analyze(
        "Depois que terminar, verifique o Blender."
    )
    assert result["decision"] == "defer"


def test_conditional_intention_is_deferred():
    result = LinguisticAnalyzer().analyze(
        "Se eu pedir, analise a cena."
    )
    assert result["decision"] == "defer"


def test_future_request_without_target_requires_clarification():
    result = LinguisticAnalyzer().analyze(
        "Dá uma olhada quando puder."
    )
    assert result["decision"] == "clarify"


def test_vague_object_requires_clarification():
    result = LinguisticAnalyzer().analyze(
        "Você consegue cuidar daquela coisa?"
    )
    assert result["decision"] == "clarify"


def test_out_of_domain_text_is_rejected():
    analyzer = LinguisticAnalyzer()
    assert analyzer.analyze(
        "Qual é a previsão do tempo para amanhã?"
    )["decision"] == "abstain"
    assert analyzer.analyze(
        "Explique como funciona a fotossíntese."
    )["decision"] == "abstain"


def test_common_typographical_variants_keep_domain_signal():
    analyzer = LinguisticAnalyzer()
    assert analyzer.has_domain_anchor("Como está o sistemaa agora?")
    assert analyzer.has_domain_anchor("Qual é o estadu atual do Mahoraga?")
    assert analyzer.has_domain_anchor("Me mostra o statuz do sistema.")


def test_supported_positive_request_continues_to_classifier():
    result = LinguisticAnalyzer().analyze(
        "Confira os objetos presentes na cena do Blender."
    )
    assert result["decision"] == "continue"



def test_extended_future_markers_are_deferred():
    analyzer = LinguisticAnalyzer()
    phrases = [
        "Na semana que vem, consulte os relatórios do núcleo.",
        "Quando a atualização terminar, confira os serviços.",
        "No próximo ciclo, examine os elementos da cena.",
        "Depois da reunião, informe o estado do sistema.",
    ]
    assert all(analyzer.analyze(text)["decision"] == "defer" for text in phrases)


def test_extended_conditional_markers_are_deferred():
    analyzer = LinguisticAnalyzer()
    phrases = [
        "Se houver autorização, consulte o diagnóstico do sistema.",
        "Caso eu confirme, inspecione a composição visual da cena.",
        "Se for permitido, verifique os recursos do núcleo.",
        "Quando eu autorizar, revise a cena no Blender.",
    ]
    assert all(analyzer.analyze(text)["decision"] == "defer" for text in phrases)


def test_extended_past_markers_are_not_actionable():
    analyzer = LinguisticAnalyzer()
    phrases = [
        "Na última sessão, revisei a composição.",
        "A inspeção da cena foi concluída ontem.",
        "Eu consultei o relatório mais cedo.",
        "Ontem os objetos foram inspecionados.",
    ]
    assert all(analyzer.analyze(text)["decision"] == "abstain" for text in phrases)


def test_extended_vague_references_request_clarification():
    analyzer = LinguisticAnalyzer()
    phrases = [
        "Talvez seja melhor revisar isso depois.",
        "Você pode cuidar daquela parte?",
        "Dá para verificar aquilo?",
        "Acho que seria bom olhar o negócio.",
    ]
    assert all(analyzer.analyze(text)["decision"] == "clarify" for text in phrases)



def test_never_and_ever_negations_block_action():
    analyzer = LinguisticAnalyzer()
    assert analyzer.analyze(
        "Nunca examine a hierarquia dos modelos."
    )["reason"] == "negated_action"
    assert analyzer.analyze(
        "Jamais inspecione a cena."
    )["reason"] == "negated_action"


def test_domain_intent_hint_is_specific_and_refuses_mixed_domains():
    analyzer = LinguisticAnalyzer()
    assert analyzer.infer_intent_hint(
        "Quando a atualização terminar, confira os serviços."
    ) == "status"
    assert analyzer.infer_intent_hint(
        "No próximo ciclo, examine os elementos da cena."
    ) == "blender.inspect"
    assert analyzer.infer_intent_hint(
        "Verifique o estado do sistema e os objetos da cena."
    ) is None



def test_generic_action_verbs_do_not_create_domain_support():
    analyzer = LinguisticAnalyzer()
    phrases = [
        "Verifique a temperatura do arroz.",
        "Analise a fotossíntese.",
        "Inspecione o equipamento do laboratório.",
    ]
    assert all(analyzer.analyze(text)["decision"] == "abstain" for text in phrases)



def test_generic_loaded_state_does_not_establish_mahoraga_domain():
    analyzer = LinguisticAnalyzer()
    assert analyzer.analyze(
        "Meu celular está carregado."
    )["decision"] == "abstain"
    assert analyzer.analyze(
        "Revise a estrutura do texto."
    )["decision"] == "abstain"


def test_two_weak_domain_signals_can_support_a_visual_target():
    analyzer = LinguisticAnalyzer()
    assert analyzer.analyze(
        "Observe os elementos visuais do cenário."
    )["decision"] == "continue"


def test_polysemous_words_do_not_establish_mahoraga_domain_alone():
    analyzer = LinguisticAnalyzer()
    phrases = [
        "Como está o sistema solar?",
        "Explique o processo de fotossíntese.",
        "Quais recursos naturais existem na Amazônia?",
        "Qual é a situação política do país?",
        "Explique o modelo matemático de crescimento.",
        "Analise a estrutura do texto.",
        "Verifique o processo judicial.",
        "Mostre o modelo econômico.",
        "Como funciona o sistema digestivo?",
        "Qual é a situação do trânsito agora?",
    ]
    assert all(not analyzer.has_domain_anchor(text) for text in phrases)
    assert all(analyzer.analyze(text)["decision"] == "abstain" for text in phrases)


def test_contextual_status_and_blender_combinations_remain_supported():
    analyzer = LinguisticAnalyzer()
    supported = [
        "Como está o sistemaa agora?",
        "Qual é o estado atual do núcleo?",
        "Confira a saúde dos serviços do Mahoraga.",
        "Observe os elementos visuais do cenário.",
        "Inspecione a malha e os vértices do Blender.",
        "Mostre a hierarquia visual do cenário.",
    ]
    assert all(analyzer.has_domain_anchor(text) for text in supported)


def test_past_reference_blocks_unknown_active_and_passive_verbs():
    analyzer = LinguisticAnalyzer()
    phrases = [
        "Ontem o sistema apresentou erro.",
        "O relatório foi concluído ontem.",
        "Mais cedo os serviços ficaram indisponíveis.",
        "Na sessão anterior o núcleo permaneceu estável.",
        "A cena foi renderizada ontem no Blender.",
        "Na semana passada os objetos mudaram de posição no Blender.",
        "Anteriormente o sistema registrou uma falha.",
        "O relatório técnico foi finalizado mais cedo.",
    ]
    for text in phrases:
        result = analyzer.analyze(text)
        assert result["decision"] == "abstain"
        assert result["reason"] == "past_reference"


def test_expanded_portuguese_and_technical_aliases_project_to_known_features():
    analyzer = LinguisticAnalyzer()
    vocabulary = {
        "estado", "funcionamento", "plataforma", "relatório",
        "resumo", "cena", "objetos", "composição",
    }
    examples = {
        "disponibilidade": "estado",
        "health": "estado",
        "operando": "funcionamento",
        "instável": "funcionamento",
        "system": "plataforma",
        "núcleos": "plataforma",
        "diagnostico": "relatório",
        "panorama": "resumo",
        "scene": "cena",
        "viewport": "cena",
        "mesh": "objetos",
        "vértices": "objetos",
        "renderização": "cena",
        "layout": "composição",
    }
    for token, expected in examples.items():
        assert analyzer.project_token(token, vocabulary) == expected


def test_lexicon_is_versioned_and_substantially_broader_than_the_old_alias_map():
    analyzer = LinguisticAnalyzer()
    assert analyzer.LEXICON_VERSION.startswith("pt-BR-")
    assert len(analyzer.TOKEN_ALIASES) >= 150


def test_extended_action_vocabulary_recognizes_common_request_verbs():
    analyzer = LinguisticAnalyzer()
    tokens = analyzer._tokens(
        "Cheque, liste, enumere, identifique, mapeie, avalie e diagnostique."
    )
    assert analyzer._has_action(tokens)
    assert analyzer.analyze("Amanhã avalie o status do sistema.")["decision"] == "defer"


def test_composition_inspection_accepts_generic_action_with_visual_target():
    analyzer = LinguisticAnalyzer()
    assert analyzer.analyze(
        "Pode verificar a composição atual?"
    )["decision"] == "continue"


def test_future_object_hint_is_deferred_but_immediate_generic_objects_are_ambiguous():
    analyzer = LinguisticAnalyzer()
    assert not analyzer.has_domain_anchor("Confira os objetos.")
    result = analyzer.analyze("Na próxima sessão, confira os objetos.")
    assert result["decision"] == "defer"
    assert result["reason"] == "future_or_conditional_intention"
