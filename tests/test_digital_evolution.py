import math

import pytest

from experiments.digital_evolution import (
    DigitalEvolutionEngine,
    DigitalEvolutionError,
    EvolutionConfig,
    Instruction,
)


def small_config(**overrides):
    values = {
        "population_size": 8,
        "generations": 3,
        "elite_count": 2,
        "tournament_size": 2,
        "max_genome_length": 12,
        "max_stack_depth": 16,
        "max_program_steps": 16,
        "mutation_rate": 0.8,
        "crossover_rate": 0.7,
        "seed": 123,
    }
    values.update(overrides)
    return EvolutionConfig(**values)


def simple_cases():
    train = [(-2.0, -3.0), (-1.0, -1.0), (0.0, 1.0), (1.0, 3.0), (2.0, 5.0)]
    validation = [(-1.5, -2.0), (-0.5, 0.0), (0.5, 2.0), (1.5, 4.0)]
    return train, validation


def test_virtual_machine_executes_a_small_genome_deterministically():
    genome = (
        Instruction("PUSH_X"),
        Instruction("PUSH_CONST", 2.0),
        Instruction("MUL"),
        Instruction("PUSH_CONST", 1.0),
        Instruction("ADD"),
    )
    assert DigitalEvolutionEngine.run_program(genome, 3.0) == 7.0
    assert DigitalEvolutionEngine.run_program(genome, -2.0) == -3.0


@pytest.mark.parametrize(
    ("instruction", "expected"),
    [
        (Instruction("PUSH_X"), {"op": "PUSH_X"}),
        (Instruction("ADD"), {"op": "ADD"}),
        (Instruction("PUSH_CONST", 2.0), {"op": "PUSH_CONST", "value": 2.0}),
    ],
)
def test_instruction_serialization_is_canonical(instruction, expected):
    assert instruction.to_dict() == expected


def test_virtual_machine_uses_protected_division():
    genome = (
        Instruction("PUSH_X"),
        Instruction("PUSH_CONST", 0.0),
        Instruction("PDIV"),
    )
    assert DigitalEvolutionEngine.run_program(genome, 5.0) == 0.0


@pytest.mark.parametrize(
    "genome",
    [
        ({"op": "IMPORT"},),
        ({"op": "PUSH_CONST", "value": float("nan")},),
        ({"op": "PUSH_CONST", "value": True},),
        ({"op": "PUSH_CONST", "value": 1.0, "path": "/tmp"},),
        ({"op": "ADD"},),
    ],
)
def test_vm_rejects_unsafe_invalid_or_underflowing_genomes(genome):
    if genome[0].get("op") == "ADD":
        with pytest.raises(DigitalEvolutionError):
            DigitalEvolutionEngine.run_program(genome, 0.0)
    else:
        with pytest.raises(DigitalEvolutionError):
            DigitalEvolutionEngine.normalize_genome(genome)


def test_extreme_integer_inputs_raise_domain_errors_not_overflow():
    huge = 10**1000
    with pytest.raises(DigitalEvolutionError):
        Instruction("PUSH_CONST", huge)
    with pytest.raises(DigitalEvolutionError):
        EvolutionConfig(mutation_rate=huge)
    with pytest.raises(DigitalEvolutionError):
        EvolutionConfig(complexity_penalty=huge)
    with pytest.raises(DigitalEvolutionError):
        DigitalEvolutionEngine._parse_cases([(huge, 1.0)], "train_cases")
    with pytest.raises(DigitalEvolutionError):
        DigitalEvolutionEngine.run_program((Instruction("PUSH_X"),), huge)


def test_vm_rejects_nonfinite_and_oversized_inputs():
    with pytest.raises(DigitalEvolutionError):
        DigitalEvolutionEngine.run_program((Instruction("PUSH_X"),), float("inf"))
    with pytest.raises(DigitalEvolutionError):
        DigitalEvolutionEngine.run_program((Instruction("PUSH_X"),), 1e20)


def test_vm_enforces_stack_limit():
    genome = (
        Instruction("PUSH_X"),
        Instruction("DUP"),
        Instruction("DUP"),
    )
    with pytest.raises(DigitalEvolutionError, match="profundidade"):
        DigitalEvolutionEngine.run_program(genome, 1.0, max_stack_depth=2)


def test_evolution_is_reproducible_and_tracks_lineage_and_diversity():
    train, validation = simple_cases()
    engine = DigitalEvolutionEngine(small_config())
    first = engine.evolve(train, validation, [(3.0, 7.0), (-3.0, -5.0)])
    second = DigitalEvolutionEngine(small_config()).evolve(
        train, validation, [(3.0, 7.0), (-3.0, -5.0)]
    )

    assert first["status"] == "completed"
    assert first["champion"]["genome_sha256"] == second["champion"]["genome_sha256"]
    assert first["champion"]["selection_score"] == second["champion"]["selection_score"]
    assert first["generations_completed"] == 3
    assert first["archive"]["capacity"] == 64
    assert 0 <= first["archive"]["filled_cells"] <= 64
    assert first["lineage"][0]["organism_id"] == first["champion"]["organism_id"]
    assert first["champion"]["test"]["used_for_selection"] is False
    assert first["safety"]["closed_virtual_machine"] is True
    assert first["safety"]["python_eval_or_exec_used"] is False


def test_heldout_test_data_cannot_change_selected_champion():
    train, validation = simple_cases()
    config = small_config(seed=777)
    normal = DigitalEvolutionEngine(config).evolve(train, validation, [(3.0, 7.0)])
    changed = DigitalEvolutionEngine(config).evolve(train, validation, [(3.0, -900.0)])

    assert normal["champion"]["genome_sha256"] == changed["champion"]["genome_sha256"]
    assert normal["champion"]["selection_score"] == changed["champion"]["selection_score"]
    assert normal["champion"]["test"]["mae"] != changed["champion"]["test"]["mae"]


def test_case_evaluation_accounting_includes_behavior_descriptor_probes():
    train, validation = simple_cases()
    result = DigitalEvolutionEngine(small_config()).evolve(train, validation)
    assert result["case_evaluations"] >= (
        result["organisms_evaluated"] * (len(train) + len(validation))
    )
    assert result["case_evaluations"] <= (
        result["organisms_evaluated"] * (len(train) + len(validation) + 2)
    )


def test_engine_preflights_case_evaluation_budget():
    train, validation = simple_cases()
    config = small_config(max_case_evaluations=10)
    with pytest.raises(DigitalEvolutionError, match="max_case_evaluations"):
        DigitalEvolutionEngine(config).evolve(train, validation, [(1.0, 3.0)])


def test_engine_rejects_bad_task_cases_before_population_creation():
    engine = DigitalEvolutionEngine(small_config())
    with pytest.raises(DigitalEvolutionError):
        engine.evolve([(0.0, float("nan"))], [(1.0, 2.0)])
    with pytest.raises(DigitalEvolutionError):
        engine.evolve([], [(1.0, 2.0)])


def test_evolution_config_rejects_boolean_limits_and_invalid_rates():
    with pytest.raises(DigitalEvolutionError):
        EvolutionConfig(population_size=True)
    with pytest.raises(DigitalEvolutionError):
        EvolutionConfig(mutation_rate=float("nan"))


def test_report_never_claims_self_originating_life_or_runtime_promotion():
    train, validation = simple_cases()
    result = DigitalEvolutionEngine(small_config()).evolve(train, validation)
    limits = " ".join(result["interpretation_limits"]).casefold()
    assert "not self-originating" in limits
    assert result["safety"]["automatic_promotion"] is False
    assert result["safety"]["self_replication_outside_simulator"] is False
