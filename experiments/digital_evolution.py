"""Bounded evolutionary programming for research on digital organisms.

Genomes are data interpreted by a closed virtual machine. They are never
compiled, eval'd, exec'd, imported, or allowed to access the host operating
system. This is a human-seeded, breeder-mode experiment, not autonomous
self-replication or a production self-modifying system.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import random
from typing import Any, Iterable, Sequence


class DigitalEvolutionError(ValueError):
    """Invalid genome, task, or evolutionary resource budget."""


@dataclass(frozen=True)
class Instruction:
    op: str
    value: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.op, str) or self.op not in {
            "PUSH_X", "PUSH_CONST", "ADD", "SUB", "MUL", "PDIV",
            "NEG", "ABS", "MIN", "MAX", "SIN", "COS", "DUP", "SWAP",
        }:
            raise DigitalEvolutionError(f"Opcode não permitido: {self.op}")
        if self.op == "PUSH_CONST":
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise DigitalEvolutionError("PUSH_CONST exige constante numérica.")
            value = float(self.value)
            if not math.isfinite(value) or abs(value) > 1000.0:
                raise DigitalEvolutionError("Constante fora do limite permitido.")
            object.__setattr__(self, "value", value)
        elif self.value is not None:
            raise DigitalEvolutionError("Somente PUSH_CONST aceita valor.")


Genome = tuple[Instruction, ...]


@dataclass(frozen=True)
class DigitalOrganism:
    organism_id: str
    genome: Genome
    generation: int
    parent_ids: tuple[str, ...]
    birth_operator: str

    @property
    def genome_sha256(self) -> str:
        payload = json.dumps(
            [item.to_dict() for item in self.genome],
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "organism_id": self.organism_id,
            "genome_sha256": self.genome_sha256,
            "generation": self.generation,
            "parent_ids": list(self.parent_ids),
            "birth_operator": self.birth_operator,
            "genome": [item.to_dict() for item in self.genome],
        }


@dataclass(frozen=True)
class EvolutionConfig:
    population_size: int = 40
    generations: int = 30
    elite_count: int = 3
    tournament_size: int = 3
    max_genome_length: int = 32
    max_stack_depth: int = 32
    max_program_steps: int = 64
    mutation_rate: float = 0.70
    crossover_rate: float = 0.70
    complexity_penalty: float = 0.001
    max_case_evaluations: int = 200_000
    seed: int = 42

    def __post_init__(self) -> None:
        integer_limits = (
            ("population_size", self.population_size, 8, 128),
            ("generations", self.generations, 1, 200),
            ("elite_count", self.elite_count, 1, 32),
            ("tournament_size", self.tournament_size, 2, 16),
            ("max_genome_length", self.max_genome_length, 2, 64),
            ("max_stack_depth", self.max_stack_depth, 2, 64),
            ("max_program_steps", self.max_program_steps, 2, 64),
            ("max_case_evaluations", self.max_case_evaluations, 1, 1_000_000),
            ("seed", self.seed, 0, 2**32 - 1),
        )
        for name, value, lower, upper in integer_limits:
            if isinstance(value, bool) or not isinstance(value, int):
                raise DigitalEvolutionError(f"{name} deve ser inteiro.")
            if not lower <= value <= upper:
                raise DigitalEvolutionError(f"{name} fora do limite permitido.")
        if self.elite_count >= self.population_size:
            raise DigitalEvolutionError("elite_count precisa ser menor que population_size.")
        if self.max_genome_length > self.max_program_steps:
            raise DigitalEvolutionError(
                "max_genome_length não pode exceder max_program_steps."
            )
        for name, value in (
            ("mutation_rate", self.mutation_rate),
            ("crossover_rate", self.crossover_rate),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise DigitalEvolutionError(f"{name} deve estar entre 0 e 1.")
            if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
                raise DigitalEvolutionError(f"{name} deve estar entre 0 e 1.")
        if (isinstance(self.complexity_penalty, bool)
                or not isinstance(self.complexity_penalty, (int, float))
                or not math.isfinite(float(self.complexity_penalty))
                or not 0.0 <= float(self.complexity_penalty) <= 1.0):
            raise DigitalEvolutionError("complexity_penalty inválida.")


@dataclass(frozen=True)
class ProgramEvaluation:
    organism: DigitalOrganism
    train_mae: float
    validation_mae: float
    selection_score: float
    operation_count: int
    behavior_cell: tuple[int, int] | None
    valid: bool

    def summary(self) -> dict[str, Any]:
        return {
            "organism_id": self.organism.organism_id,
            "genome_sha256": self.organism.genome_sha256,
            "generation": self.organism.generation,
            "parent_ids": list(self.organism.parent_ids),
            "birth_operator": self.organism.birth_operator,
            "genome_length": len(self.organism.genome),
            "train_mae": self.train_mae if self.valid else None,
            "validation_mae": self.validation_mae if self.valid else None,
            "selection_score": self.selection_score,
            "operation_count": self.operation_count,
            "behavior_cell": list(self.behavior_cell) if self.behavior_cell else None,
            "valid": self.valid,
        }


class DigitalEvolutionEngine:
    """Evolve short mathematical programs inside a closed stack virtual machine.

    The experiment implements the three minimal Darwinian ingredients in a
    controlled breeder setting:
      * replication: the engine creates descendants from selected parents;
      * heredity with variation: genomes are copied, crossed over and mutated;
      * differential selection: task performance, validation and complexity
        determine which variants persist.

    MAP-Elites-style behavioral cells retain different solution behaviors so
    selection does not collapse immediately to one genotype. The archive is
    bounded by the fixed descriptor grid (8 x 8).
    """

    VERSION = "0.1.0"
    MAX_CASES_PER_SPLIT = 512
    MAX_ABS_INPUT = 1_000_000.0
    MAX_ABS_OUTPUT = 1_000_000_000_000.0
    MAX_GENOME_LENGTH_HARD = 64
    DESCRIPTOR_BINS = 8
    DESCRIPTOR_MIN = -10.0
    DESCRIPTOR_MAX = 10.0
    INVALID_ERROR = 1_000_000_000.0
    ALLOWED_OPCODES = frozenset({
        "PUSH_X", "PUSH_CONST", "ADD", "SUB", "MUL", "PDIV",
        "NEG", "ABS", "MIN", "MAX", "SIN", "COS", "DUP", "SWAP",
    })

    def __init__(self, config: EvolutionConfig | None = None):
        self.config = config or EvolutionConfig()

    @staticmethod
    def _parse_cases(cases: Iterable[Sequence[Any]], field: str) -> tuple[tuple[float, float], ...]:
        if not isinstance(cases, (list, tuple)) or not 1 <= len(cases) <= 512:
            raise DigitalEvolutionError(
                f"{field} deve conter de 1 a 512 pares entrada/saída."
            )
        parsed: list[tuple[float, float]] = []
        for index, pair in enumerate(cases):
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise DigitalEvolutionError(f"{field}[{index}] deve ser um par x/y.")
            values = []
            for item in pair:
                if isinstance(item, bool) or not isinstance(item, (int, float)):
                    raise DigitalEvolutionError(f"{field}[{index}] contém valor não numérico.")
                number = float(item)
                if not math.isfinite(number):
                    raise DigitalEvolutionError(f"{field}[{index}] contém valor não finito.")
                if abs(number) > DigitalEvolutionEngine.MAX_ABS_INPUT:
                    raise DigitalEvolutionError(f"{field}[{index}] excede o limite numérico.")
                values.append(number)
            parsed.append((values[0], values[1]))
        return tuple(parsed)

    @staticmethod
    def normalize_genome(raw: Sequence[Any], maximum: int = 64) -> Genome:
        if not isinstance(raw, (list, tuple)) or not 1 <= len(raw) <= maximum:
            raise DigitalEvolutionError("Genome vazio ou acima do limite.")
        instructions: list[Instruction] = []
        for index, item in enumerate(raw):
            if isinstance(item, Instruction):
                instruction = item
            elif isinstance(item, dict) and set(item).issubset({"op", "value"}) and "op" in item:
                instruction = Instruction(item["op"], item.get("value"))
            else:
                raise DigitalEvolutionError(f"Instrução {index} possui formato inválido.")
            instructions.append(instruction)
        return tuple(instructions)

    @staticmethod
    def run_program(
        genome: Sequence[Any], x: float, *,
        max_stack_depth: int = 32, max_program_steps: int = 64,
    ) -> float:
        """Interpret a genome without Python eval/exec, imports or host access."""
        if (isinstance(max_program_steps, bool)
                or not isinstance(max_program_steps, int)
                or not 1 <= max_program_steps <= DigitalEvolutionEngine.MAX_GENOME_LENGTH_HARD):
            raise DigitalEvolutionError("max_program_steps inválido.")
        program = DigitalEvolutionEngine.normalize_genome(
            genome, maximum=max_program_steps
        )
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise DigitalEvolutionError("Entrada x inválida.")
        x_value = float(x)
        if not math.isfinite(x_value) or abs(x_value) > DigitalEvolutionEngine.MAX_ABS_INPUT:
            raise DigitalEvolutionError("Entrada x fora do limite.")
        if (isinstance(max_stack_depth, bool) or not isinstance(max_stack_depth, int)
                or not 2 <= max_stack_depth <= 64):
            raise DigitalEvolutionError("max_stack_depth inválido.")

        stack: list[float] = []

        def pop_one() -> float:
            if not stack:
                raise DigitalEvolutionError("Pilha virtual vazia.")
            return stack.pop()

        for instruction in program:
            op = instruction.op
            if op == "PUSH_X":
                stack.append(x_value)
            elif op == "PUSH_CONST":
                stack.append(float(instruction.value))
            elif op in {"NEG", "ABS", "SIN", "COS", "DUP"}:
                if not stack:
                    raise DigitalEvolutionError("Pilha virtual vazia.")
                if op == "NEG":
                    stack[-1] = -stack[-1]
                elif op == "ABS":
                    stack[-1] = abs(stack[-1])
                elif op == "SIN":
                    stack[-1] = math.sin(stack[-1])
                elif op == "COS":
                    stack[-1] = math.cos(stack[-1])
                else:
                    stack.append(stack[-1])
            elif op == "SWAP":
                if len(stack) < 2:
                    raise DigitalEvolutionError("SWAP exige dois valores.")
                stack[-1], stack[-2] = stack[-2], stack[-1]
            else:
                right = pop_one()
                left = pop_one()
                if op == "ADD":
                    result = left + right
                elif op == "SUB":
                    result = left - right
                elif op == "MUL":
                    result = left * right
                elif op == "PDIV":
                    result = 0.0 if abs(right) <= 1e-12 else left / right
                elif op == "MIN":
                    result = min(left, right)
                elif op == "MAX":
                    result = max(left, right)
                else:
                    raise DigitalEvolutionError(f"Opcode não implementado: {op}")
                stack.append(result)

            if len(stack) > max_stack_depth:
                raise DigitalEvolutionError("Limite de profundidade da pilha excedido.")
            if any(not math.isfinite(value) or abs(value) > DigitalEvolutionEngine.MAX_ABS_OUTPUT
                   for value in stack):
                raise DigitalEvolutionError("Estado numérico da VM excedeu o limite.")

        if not stack:
            raise DigitalEvolutionError("Genome terminou sem produzir saída.")
        return stack[-1]

    @staticmethod
    def _random_instruction(rng: random.Random) -> Instruction:
        opcode = rng.choice(tuple(sorted(DigitalEvolutionEngine.ALLOWED_OPCODES)))
        if opcode == "PUSH_CONST":
            return Instruction(opcode, round(rng.uniform(-3.0, 3.0), 2))
        return Instruction(opcode)

    def _random_genome(self, rng: random.Random) -> Genome:
        genome: list[Instruction] = [Instruction("PUSH_X")]
        depth = 1
        desired = rng.randint(2, min(self.config.max_genome_length, 12))
        for _ in range(desired - 1):
            choices = ["PUSH_X", "PUSH_CONST", "DUP"]
            if depth >= 1:
                choices += ["NEG", "ABS", "SIN", "COS"]
            if depth >= 2:
                choices += ["ADD", "SUB", "MUL", "PDIV", "MIN", "MAX", "SWAP"]
            op = rng.choice(choices)
            if op in {"PUSH_X", "PUSH_CONST"}:
                genome.append(
                    Instruction("PUSH_CONST", round(rng.uniform(-3.0, 3.0), 2))
                    if op == "PUSH_CONST" else Instruction("PUSH_X")
                )
                depth += 1
            elif op == "DUP":
                genome.append(Instruction(op))
                depth += 1
            elif op in {"ADD", "SUB", "MUL", "PDIV", "MIN", "MAX"}:
                genome.append(Instruction(op))
                depth -= 1
            else:
                genome.append(Instruction(op))
            depth = min(depth, self.config.max_stack_depth)
        return tuple(genome[:self.config.max_genome_length])

    @staticmethod
    def _genome_payload(genome: Genome) -> list[dict[str, Any]]:
        return [item.to_dict() for item in genome]

    @staticmethod
    def _organism_id(
        genome: Genome, generation: int, slot: int,
        parents: tuple[str, ...], birth_operator: str,
    ) -> str:
        payload = {
            "genome": DigitalEvolutionEngine._genome_payload(genome),
            "generation": generation,
            "slot": slot,
            "parents": list(parents),
            "birth_operator": birth_operator,
        }
        raw = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:24]

    def _organism(
        self, genome: Genome, generation: int, slot: int,
        parents: tuple[str, ...], birth_operator: str,
    ) -> DigitalOrganism:
        return DigitalOrganism(
            organism_id=self._organism_id(genome, generation, slot, parents, birth_operator),
            genome=genome,
            generation=generation,
            parent_ids=parents,
            birth_operator=birth_operator,
        )

    @staticmethod
    def _error(
        genome: Genome, cases: tuple[tuple[float, float], ...],
        stack_limit: int, program_steps: int = 64,
    ) -> float:
        total = 0.0
        for x_value, expected in cases:
            try:
                actual = DigitalEvolutionEngine.run_program(
                    genome, x_value, max_stack_depth=stack_limit,
                    max_program_steps=program_steps,
                )
            except (DigitalEvolutionError, OverflowError, ValueError):
                return DigitalEvolutionEngine.INVALID_ERROR
            difference = abs(actual - expected)
            if not math.isfinite(difference):
                return DigitalEvolutionEngine.INVALID_ERROR
            total += min(difference, DigitalEvolutionEngine.INVALID_ERROR)
        return total / len(cases)

    def _behavior_cell(
        self, genome: Genome, train_cases: tuple[tuple[float, float], ...]
    ) -> tuple[int, int] | None:
        x_values = [item[0] for item in train_cases]
        probes = (min(x_values), max(x_values))
        try:
            outputs = [
                self.run_program(
                    genome, x,
                    max_stack_depth=self.config.max_stack_depth,
                    max_program_steps=self.config.max_program_steps,
                )
                for x in probes
            ]
        except DigitalEvolutionError:
            return None
        bins = []
        for value in outputs:
            clipped = min(self.DESCRIPTOR_MAX, max(self.DESCRIPTOR_MIN, value))
            ratio = (clipped - self.DESCRIPTOR_MIN) / (
                self.DESCRIPTOR_MAX - self.DESCRIPTOR_MIN
            )
            bins.append(min(self.DESCRIPTOR_BINS - 1, int(ratio * self.DESCRIPTOR_BINS)))
        return bins[0], bins[1]

    def _evaluate(
        self,
        organism: DigitalOrganism,
        train_cases: tuple[tuple[float, float], ...],
        validation_cases: tuple[tuple[float, float], ...],
    ) -> ProgramEvaluation:
        train_mae = self._error(
            organism.genome, train_cases, self.config.max_stack_depth,
            self.config.max_program_steps,
        )
        validation_mae = self._error(
            organism.genome, validation_cases, self.config.max_stack_depth,
            self.config.max_program_steps,
        )
        valid = (
            train_mae < self.INVALID_ERROR
            and validation_mae < self.INVALID_ERROR
            and math.isfinite(train_mae)
            and math.isfinite(validation_mae)
        )
        if valid:
            penalty = self.config.complexity_penalty * len(organism.genome)
            score = 1.0 / (1.0 + validation_mae + penalty)
        else:
            score = 0.0
        descriptor = self._behavior_cell(organism.genome, train_cases) if valid else None
        return ProgramEvaluation(
            organism=organism,
            train_mae=train_mae,
            validation_mae=validation_mae,
            selection_score=round(score, 12),
            operation_count=len(organism.genome) * (
                len(train_cases) + len(validation_cases)
            ),
            behavior_cell=descriptor,
            valid=valid,
        )

    def _mutate(self, genome: Genome, rng: random.Random) -> tuple[Genome, str]:
        items = list(genome)
        operations = ["replace", "insert", "delete", "constant"]
        operation = rng.choice(operations)
        if operation == "replace":
            index = rng.randrange(len(items))
            items[index] = self._random_instruction(rng)
        elif operation == "insert" and len(items) < self.config.max_genome_length:
            index = rng.randrange(len(items) + 1)
            items.insert(index, self._random_instruction(rng))
        elif operation == "delete" and len(items) > 1:
            del items[rng.randrange(len(items))]
        elif operation == "constant":
            indices = [i for i, item in enumerate(items) if item.op == "PUSH_CONST"]
            if indices:
                index = rng.choice(indices)
                items[index] = Instruction("PUSH_CONST", round(
                    float(items[index].value) + rng.uniform(-1.0, 1.0), 2
                ))
            else:
                index = rng.randrange(len(items))
                items[index] = self._random_instruction(rng)
        if not items:
            items = [Instruction("PUSH_X")]
        return tuple(items[:self.config.max_genome_length]), operation

    def _crossover(
        self, left: Genome, right: Genome, rng: random.Random
    ) -> Genome:
        left_cut = rng.randrange(1, len(left) + 1)
        right_cut = rng.randrange(0, len(right))
        child = left[:left_cut] + right[right_cut:]
        if not child:
            child = (Instruction("PUSH_X"),)
        return tuple(child[:self.config.max_genome_length])

    def _initial_population(self, rng: random.Random) -> list[DigitalOrganism]:
        baseline_genomes: list[Genome] = [
            (Instruction("PUSH_X"),),
            (Instruction("PUSH_CONST", 0.0),),
        ]
        organisms = [
            self._organism(genome, 0, index, (), "seed")
            for index, genome in enumerate(baseline_genomes)
        ]
        for index in range(len(organisms), self.config.population_size):
            genome = self._random_genome(rng)
            organisms.append(self._organism(genome, 0, index, (), "random_seed"))
        return organisms

    @staticmethod
    def _rank_key(item: ProgramEvaluation) -> tuple[float, float, int, str]:
        return (
            item.selection_score,
            -item.validation_mae,
            -len(item.organism.genome),
            item.organism.organism_id,
        )

    def _tournament(
        self, pool: Sequence[ProgramEvaluation], rng: random.Random
    ) -> ProgramEvaluation:
        size = min(self.config.tournament_size, len(pool))
        chosen = rng.sample(list(pool), size)
        return max(chosen, key=self._rank_key)

    def evolve(
        self,
        train_cases: Iterable[Sequence[Any]],
        validation_cases: Iterable[Sequence[Any]],
        test_cases: Iterable[Sequence[Any]] | None = None,
    ) -> dict[str, Any]:
        """Evolve a population; held-out test cases are used only after selection."""
        train = self._parse_cases(train_cases, "train_cases")
        validation = self._parse_cases(validation_cases, "validation_cases")
        test = self._parse_cases(test_cases, "test_cases") if test_cases is not None else ()

        case_evaluation_budget = (
            self.config.population_size * (self.config.generations + 1)
            * (len(train) + len(validation))
            + len(test)
        )
        if case_evaluation_budget > self.config.max_case_evaluations:
            raise DigitalEvolutionError(
                "Experimento excede max_case_evaluations antes de iniciar."
            )

        rng = random.Random(self.config.seed)
        population = self._initial_population(rng)
        archive: dict[tuple[int, int], ProgramEvaluation] = {}
        lineage: dict[str, DigitalOrganism] = {}
        cache: dict[str, ProgramEvaluation] = {}
        evaluated_count = 0
        best_overall: ProgramEvaluation | None = None

        for generation in range(self.config.generations + 1):
            evaluated: list[ProgramEvaluation] = []
            for organism in population:
                lineage[organism.organism_id] = organism
                digest = organism.genome_sha256
                result = cache.get(digest)
                if result is None:
                    result = self._evaluate(organism, train, validation)
                    cache[digest] = result
                    evaluated_count += len(train) + len(validation)
                else:
                    # Preserve this organism's individual lineage while reusing
                    # the deterministic phenotype metrics for an identical genome.
                    result = ProgramEvaluation(
                        organism=organism,
                        train_mae=result.train_mae,
                        validation_mae=result.validation_mae,
                        selection_score=result.selection_score,
                        operation_count=result.operation_count,
                        behavior_cell=result.behavior_cell,
                        valid=result.valid,
                    )
                evaluated.append(result)
                if result.behavior_cell is not None:
                    old = archive.get(result.behavior_cell)
                    if old is None or self._rank_key(result) > self._rank_key(old):
                        archive[result.behavior_cell] = result
                if best_overall is None or self._rank_key(result) > self._rank_key(best_overall):
                    best_overall = result

            if generation == self.config.generations:
                population_evaluations = evaluated
                break

            ranked = sorted(evaluated, key=self._rank_key, reverse=True)
            next_population: list[DigitalOrganism] = []
            for slot, elite in enumerate(ranked[:self.config.elite_count]):
                child = self._organism(
                    elite.organism.genome, generation + 1, slot,
                    (elite.organism.organism_id,), "elite_copy",
                )
                next_population.append(child)

            parent_pool_by_id = {item.organism.organism_id: item for item in evaluated}
            parent_pool_by_id.update({
                item.organism.organism_id: item for item in archive.values()
            })
            parent_pool = list(parent_pool_by_id.values())

            while len(next_population) < self.config.population_size:
                first = self._tournament(parent_pool, rng)
                second = self._tournament(parent_pool, rng)
                child_genome = first.organism.genome
                parent_ids = (first.organism.organism_id,)
                birth_ops = ["clone"]
                if rng.random() < self.config.crossover_rate:
                    child_genome = self._crossover(
                        first.organism.genome, second.organism.genome, rng
                    )
                    parent_ids = (
                        first.organism.organism_id,
                        second.organism.organism_id,
                    )
                    birth_ops = ["crossover"]
                if rng.random() < self.config.mutation_rate:
                    child_genome, mutation = self._mutate(child_genome, rng)
                    birth_ops.append("mutation:" + mutation)
                operator = "+".join(birth_ops)
                slot = len(next_population)
                next_population.append(self._organism(
                    child_genome, generation + 1, slot, parent_ids, operator
                ))
            population = next_population

        if best_overall is None:
            raise DigitalEvolutionError("A população não produziu avaliação.")

        # The champion is selected using train/validation only. Test data is
        # touched exactly here, after the selected genome can no longer change.
        champion = best_overall
        heldout = None
        if test:
            test_mae = self._error(
                champion.organism.genome, test, self.config.max_stack_depth,
                self.config.max_program_steps,
            )
            heldout = {
                "status": "evaluated_after_selection",
                "mae": test_mae if test_mae < self.INVALID_ERROR else None,
                "case_count": len(test),
                "used_for_selection": False,
            }

        ancestry: list[dict[str, Any]] = []
        pending = [champion.organism.organism_id]
        seen: set[str] = set()
        while pending and len(ancestry) < 256:
            organism_id = pending.pop(0)
            if organism_id in seen:
                continue
            seen.add(organism_id)
            organism = lineage.get(organism_id)
            if organism is None:
                continue
            ancestry.append({
                "organism_id": organism.organism_id,
                "genome_sha256": organism.genome_sha256,
                "generation": organism.generation,
                "parent_ids": list(organism.parent_ids),
                "birth_operator": organism.birth_operator,
            })
            pending.extend(organism.parent_ids)

        archive_summaries = [
            item.summary()
            for _, item in sorted(archive.items(), key=lambda pair: pair[0])
        ]
        return {
            "schema": "mahoraga.digital_evolution_report",
            "schema_version": 1,
            "engine_version": self.VERSION,
            "mode": "bounded_breeder",
            "status": "completed",
            "generations_completed": self.config.generations,
            "population_size": self.config.population_size,
            "organisms_evaluated": len(cache),
            "case_evaluations": evaluated_count + len(test),
            "archive": {
                "algorithm": "bounded_map_elites_8x8",
                "filled_cells": len(archive),
                "capacity": self.DESCRIPTOR_BINS ** 2,
                "elites": archive_summaries,
            },
            "champion": {
                **champion.summary(),
                "genome": self._genome_payload(champion.organism.genome),
                "test": heldout,
            },
            "lineage": ancestry,
            "safety": {
                "closed_virtual_machine": True,
                "python_eval_or_exec_used": False,
                "host_filesystem_access": False,
                "network_access": False,
                "subprocess_access": False,
                "external_actions": False,
                "project_files_modified": False,
                "automatic_promotion": False,
                "self_replication_outside_simulator": False,
            },
            "interpretation_limits": [
                "This is a human-seeded breeder experiment, not self-originating artificial life.",
                "Genomes are interpreted data, not arbitrary Python source code.",
                "The engine evolves bounded scalar programs; it does not rewrite Mahoraga's production modules.",
                "The selection score is task-specific and is not a universal measure of intelligence or fitness.",
                "MAP-Elites descriptors use only the minimum and maximum training inputs; they preserve a small behavioral diversity proxy, not general competence.",
                "Held-out test cases are evaluated after selection and do not influence parent selection.",
                "A successful synthetic benchmark does not prove biological life, consciousness, general intelligence, or real-world competence.",
            ],
        }
