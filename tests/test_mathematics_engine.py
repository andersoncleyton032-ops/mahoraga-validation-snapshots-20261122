from decimal import Decimal
from fractions import Fraction
import random

import pytest

from agent.mathematics_engine import MathematicsEngine, MathematicsEngineError


@pytest.fixture
def engine():
    return MathematicsEngine()


def test_expression_uses_operator_precedence_and_parentheses(engine):
    result = engine.evaluate_expression("(2 + 3) * 4 - 6 / 3")
    assert result["status"] == "evaluated"
    assert result["value"] == {
        "numerator": 18,
        "denominator": 1,
        "exact": "18",
        "kind": "integer",
    }
    assert result["arithmetic"] == "exact_fraction"


def test_expression_preserves_exact_rational_arithmetic(engine):
    result = engine.evaluate_expression("1/3 + 1/6")
    assert result["value"]["exact"] == "1/2"
    assert result["value"]["numerator"] == 1
    assert result["value"]["denominator"] == 2


def test_decimal_literals_do_not_pass_through_binary_float(engine):
    result = engine.evaluate_expression("0.1 + 0.2")
    assert result["value"]["exact"] == "3/10"


def test_expression_supports_bounded_variables_and_decimal_inputs(engine):
    result = engine.evaluate_expression(
        "a / b + c",
        {"a": 3, "b": 2, "c": Decimal("0.25")},
    )
    assert result["variables"] == ["a", "b", "c"]
    assert result["value"]["exact"] == "7/4"


def test_expression_supports_integer_powers_with_exact_results(engine):
    result = engine.evaluate_expression("(3/2) ** -2")
    assert result["value"]["exact"] == "4/9"


@pytest.mark.parametrize("expression", [
    "1 / 0",
    "__import__('os').system('id')",
    "(1).__class__",
    "x[0]",
    "lambda: 1",
    "True + 1",
    "'texto'",
    "2 % 2",
    "2 // 2",
    "2 ** 13",
    "2 ** (1/2)",
])
def test_expression_rejects_unsafe_or_unsupported_constructs(engine, expression):
    with pytest.raises(MathematicsEngineError):
        engine.evaluate_expression(expression)


def test_expression_rejects_unknown_or_invalid_variables(engine):
    with pytest.raises(MathematicsEngineError, match="não foi fornecida"):
        engine.evaluate_expression("x + 1")
    with pytest.raises(MathematicsEngineError, match="Booleanos"):
        engine.evaluate_expression("x + 1", {"x": True})
    with pytest.raises(MathematicsEngineError, match="Nome de variável"):
        engine.evaluate_expression("x + 1", {"__class__": 1})


def test_expression_enforces_input_and_ast_budgets(engine):
    with pytest.raises(MathematicsEngineError, match="caracteres"):
        engine.evaluate_expression("1" * (engine.MAX_EXPRESSION_LENGTH + 1))
    with pytest.raises(MathematicsEngineError, match="caracteres"):
        engine.evaluate_expression(" " * (engine.MAX_EXPRESSION_LENGTH + 1))
    with pytest.raises(MathematicsEngineError, match="caracteres"):
        engine.solve_linear_equation(" " * (engine.MAX_EQUATION_LENGTH + 1))
    with pytest.raises(MathematicsEngineError, match="profundidade"):
        engine.evaluate_expression("-" * 40 + "1")
    def balanced_sum(values):
        if len(values) == 1:
            return values[0]
        middle = len(values) // 2
        return (
            "(" + balanced_sum(values[:middle])
            + " + " + balanced_sum(values[middle:]) + ")"
        )

    with pytest.raises(MathematicsEngineError, match="operações"):
        engine.evaluate_expression(balanced_sum(["1"] * 70))


@pytest.mark.parametrize(
    "equation,variable,expected",
    [
        ("2*x + 3 = 11", None, "4"),
        ("3*x/2 = 7/2", None, "7/3"),
        ("2*(x + 1) = x + 5", None, "3"),
        ("-x + 4 = 1", None, "3"),
        ("0.5*x = 1.25", None, "5/2"),
        ("2*y + 6 = 10", "y", "2"),
    ],
)
def test_linear_equation_solver_returns_exact_verified_solution(engine, equation, variable, expected):
    result = engine.solve_linear_equation(equation, variable)
    assert result["status"] == "solved"
    assert result["solution"]["exact"] == expected
    assert result["verified"] is True
    assert result["verification"]["performed"] is True
    assert result["verification"]["equal"] is True


def test_linear_solver_distinguishes_no_solution_and_infinite_solutions(engine):
    none = engine.solve_linear_equation("2*x + 2 = 2*x + 3")
    many = engine.solve_linear_equation("2*x + 2 = 2*(x + 1)")
    assert none["status"] == "no_solution"
    assert none["solution"] is None
    assert many["status"] == "infinitely_many_solutions"
    assert many["solution"] is None


@pytest.mark.parametrize("equation", [
    "x*x = 4",
    "x**2 = 4",
    "1/x = 2",
    "x + y = 5",
    "2*x = 4 = 8",
    "= 2",
    "2 = ",
    "x + 1",
])
def test_linear_solver_rejects_unsupported_or_malformed_equations(engine, equation):
    with pytest.raises(MathematicsEngineError):
        engine.solve_linear_equation(equation)


def test_linear_solver_checks_selected_variable(engine):
    with pytest.raises(MathematicsEngineError, match="variável diferente"):
        engine.solve_linear_equation("x + y = 5", variable="x")
    with pytest.raises(MathematicsEngineError, match="Nome de variável"):
        engine.solve_linear_equation("x = 2", variable="class")


def test_linear_solver_handles_constant_equations(engine):
    assert engine.solve_linear_equation("2 + 2 = 4")["status"] == "infinitely_many_solutions"
    assert engine.solve_linear_equation("2 + 2 = 5")["status"] == "no_solution"


def test_math_engine_status_declares_scope_and_no_code_execution(engine):
    status = engine.status()
    assert status["available"] is True
    assert status["expression_parser"] == "bounded_python_ast_whitelist"
    assert status["linear_equation_solver"] is True
    assert status["external_dependencies"] == []
    assert status["code_execution"] is False
    assert status["limitations"]



def test_expression_enforces_exact_integer_bit_budget(engine):
    with pytest.raises(MathematicsEngineError, match="orçamento"):
        engine.evaluate_expression("(1e1000) ** 2")


def test_linear_solver_supports_zero_coefficients_and_constant_factors(engine):
    assert engine.solve_linear_equation("0*x = 0")["status"] == "infinitely_many_solutions"
    assert engine.solve_linear_equation("0*x = 1")["status"] == "no_solution"
    result = engine.solve_linear_equation("3*(x - 2) = 0")
    assert result["solution"]["exact"] == "2"
    assert result["verified"] is True


def test_linear_system_solver_exactly_solves_two_and_three_variable_systems(engine):
    two = engine.solve_linear_system([
        "x + y = 5",
        "2*x - y = 1",
    ])
    assert two["status"] == "solved"
    assert two["solution"]["x"]["exact"] == "2"
    assert two["solution"]["y"]["exact"] == "3"
    assert two["verified"] is True
    assert all(item["equal"] for item in two["verification"])

    three = engine.solve_linear_system([
        "x + y + z = 6",
        "2*x - y + z = 3",
        "x + 2*y - z = 2",
    ])
    assert three["status"] == "solved"
    assert {
        name: value["exact"] for name, value in three["solution"].items()
    } == {"x": "1", "y": "2", "z": "3"}
    assert three["verified"] is True


def test_linear_system_solver_preserves_exact_fractional_solutions(engine):
    result = engine.solve_linear_system([
        "2*x + y = 1",
        "x - y = 0",
    ])
    assert result["status"] == "solved"
    assert result["solution"]["x"]["exact"] == "1/3"
    assert result["solution"]["y"]["exact"] == "1/3"
    assert result["verified"] is True


def test_linear_system_solver_distinguishes_inconsistent_and_underdetermined(engine):
    inconsistent = engine.solve_linear_system([
        "x + y = 1",
        "x + y = 2",
    ])
    underdetermined = engine.solve_linear_system([
        "x + y = 1",
    ])
    redundant = engine.solve_linear_system([
        "x + y = 3",
        "2*x + 2*y = 6",
        "3*x + 3*y = 9",
    ])
    assert inconsistent["status"] == "no_solution"
    assert underdetermined["status"] == "underdetermined"
    assert underdetermined["free_variables"] == ["y"]
    assert redundant["status"] == "underdetermined"
    assert redundant["rank"] == 1


def test_linear_system_solver_supports_overdetermined_unique_system(engine):
    result = engine.solve_linear_system([
        "x + y = 3",
        "x - y = 1",
        "2*x = 4",
    ])
    assert result["status"] == "solved"
    assert result["solution"]["x"]["exact"] == "2"
    assert result["solution"]["y"]["exact"] == "1"
    assert result["verified"] is True
    assert len(result["verification"]) == 3


@pytest.mark.parametrize("equations", [
    [],
    ["x + y = 1", "x + y = 1"] * 7,
    ["x + y = 1", "x*y = 2"],
    ["x + y = 1", "1/x = 2"],
    ["x + y = 1", "x**2 = 2"],
    ["x + y = 1", "x = "],
    ["x + y"],
])
def test_linear_system_solver_rejects_invalid_or_non_linear_systems(engine, equations):
    with pytest.raises(MathematicsEngineError):
        engine.solve_linear_system(equations)


def test_linear_system_solver_reports_valid_underdetermined_system(engine):
    result = engine.solve_linear_system(["x + y = 1", "x + z = 3"])
    assert result["status"] == "underdetermined"
    assert result["solution"] is None
    assert result["verified"] is None


def test_linear_system_solver_validates_variable_contract_and_limits(engine):
    with pytest.raises(MathematicsEngineError, match="duplicatas"):
        engine.solve_linear_system(["x = 1"], variables=["x", "x"])
    with pytest.raises(MathematicsEngineError, match="ausente"):
        engine.solve_linear_system(["x + y = 1"], variables=["x"])
    with pytest.raises(MathematicsEngineError, match="até"):
        engine.solve_linear_system(
            ["x = 1"], variables=[f"x{index}" for index in range(9)]
        )
    with pytest.raises(MathematicsEngineError, match="caracteres"):
        engine.solve_linear_system([" " * (engine.MAX_SYSTEM_TOTAL_LENGTH + 1)])


def test_linear_solver_rejects_variable_power_zero_domain_ambiguity(engine):
    with pytest.raises(MathematicsEngineError, match="Expoente zero"):
        engine.solve_linear_equation("x**0 = 1")
    with pytest.raises(MathematicsEngineError, match="não está definida"):
        engine.solve_linear_equation("0**0 = 1")
    with pytest.raises(MathematicsEngineError, match="não está definida"):
        engine.evaluate_expression("0**0")


@pytest.mark.parametrize(
    "value",
    [
        1 << 5000,
        Decimal("1e2000"),
        Decimal("0." + "0" * 2000 + "1"),
    ],
)
def test_variable_numeric_inputs_respect_exact_size_budget(engine, value):
    with pytest.raises(MathematicsEngineError, match="limite|orçamento"):
        engine.evaluate_expression("x + 1", {"x": value})



def test_linear_equation_solver_deterministic_generated_exact_cases(engine):
    generator = random.Random(20261118)

    for _ in range(60):
        coefficient = generator.choice([value for value in range(-9, 10) if value])
        expected = Fraction(
            generator.randint(-20, 20),
            generator.randint(1, 9),
        )
        offset = Fraction(
            generator.randint(-20, 20),
            generator.randint(1, 9),
        )
        right = coefficient * expected + offset
        equation = (
            f"{coefficient}*x + ({offset.numerator}/{offset.denominator}) "
            f"= {right.numerator}/{right.denominator}"
        )

        result = engine.solve_linear_equation(equation)

        assert result["status"] == "solved", equation
        assert result["solution"]["exact"] == (
            str(expected.numerator)
            if expected.denominator == 1
            else f"{expected.numerator}/{expected.denominator}"
        ), equation
        assert result["verified"] is True, equation


def _format_linear_row(a, b, right):
    left_terms = []
    for coefficient, variable in ((a, "x"), (b, "y")):
        if coefficient == 0:
            continue
        magnitude = abs(coefficient)
        term = variable if magnitude == 1 else f"{magnitude}*{variable}"
        if not left_terms:
            left_terms.append(("-" if coefficient < 0 else "") + term)
        else:
            left_terms.append((" - " if coefficient < 0 else " + ") + term)
    left = "".join(left_terms) if left_terms else "0"
    right_text = (
        str(right.numerator)
        if right.denominator == 1
        else f"{right.numerator}/{right.denominator}"
    )
    return f"{left} = {right_text}"


def test_linear_system_solver_metamorphic_permutation_and_scaling(engine):
    generator = random.Random(20261119)

    for _ in range(40):
        while True:
            a, b, c, d = [generator.randint(-7, 7) for _ in range(4)]
            if a * d - b * c:
                break
        expected_x = Fraction(generator.randint(-9, 9), generator.randint(1, 5))
        expected_y = Fraction(generator.randint(-9, 9), generator.randint(1, 5))
        first_right = a * expected_x + b * expected_y
        second_right = c * expected_x + d * expected_y
        first = _format_linear_row(a, b, first_right)
        second = _format_linear_row(c, d, second_right)

        baseline = engine.solve_linear_system([first, second])
        scaled = engine.solve_linear_system([
            _format_linear_row(3 * a, 3 * b, 3 * first_right),
            _format_linear_row(-2 * c, -2 * d, -2 * second_right),
        ])
        permuted = engine.solve_linear_system([second, first])

        expected = {
            "x": (
                str(expected_x.numerator)
                if expected_x.denominator == 1
                else f"{expected_x.numerator}/{expected_x.denominator}"
            ),
            "y": (
                str(expected_y.numerator)
                if expected_y.denominator == 1
                else f"{expected_y.numerator}/{expected_y.denominator}"
            ),
        }
        for result in (baseline, scaled, permuted):
            assert result["status"] == "solved"
            assert {
                name: value["exact"] for name, value in result["solution"].items()
            } == expected
            assert result["verified"] is True
