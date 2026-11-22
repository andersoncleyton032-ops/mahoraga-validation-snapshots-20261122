"""Deterministic, bounded exact-arithmetic tools for foundational mathematics.

This module parses a deliberately small expression language into Python's AST.
It never evaluates user source as Python code, imports user-selected names, or
executes calls. Integers and rational values are represented with Fraction.
"""
from __future__ import annotations

import ast
import keyword
import math
from collections.abc import Mapping
from decimal import Decimal
from fractions import Fraction
from typing import Any


class MathematicsEngineError(ValueError):
    """Invalid, unsupported, or resource-exceeding mathematical input."""


class MathematicsEngine:
    VERSION = "0.1.0"

    MAX_EXPRESSION_LENGTH = 512
    MAX_EQUATION_LENGTH = 1025
    MAX_AST_NODES = 128
    MAX_AST_DEPTH = 32
    MAX_VARIABLES = 32
    MAX_NAME_LENGTH = 64
    MAX_EXPONENT = 12
    MAX_INTEGER_BITS = 4096
    MAX_SYSTEM_EQUATIONS = 12
    MAX_SYSTEM_VARIABLES = 8
    MAX_SYSTEM_TOTAL_LENGTH = 4096

    SUPPORTED_OPERATORS = ["+", "-", "*", "/", "** (expoente inteiro constante)"]
    LIMITATIONS = [
        "A gramática aceita multiplicação explícita; multiplicação implícita como 2x ainda não é aceita.",
        "O escopo algébrico cobre equações lineares e sistemas lineares limitados.",
        "Potências exigem expoente inteiro constante limitado; potências zero de expressões variáveis são rejeitadas no solver.",
        "Sistemas lineares aceitam até 12 equações e 8 variáveis.",
        "Não há suporte a funções, trigonometria, logaritmos, matrizes, cálculo ou unidades físicas.",
        "Resultados são exatos em inteiros e frações; aproximações decimais não são produzidas automaticamente.",
        "O módulo é determinístico e não representa compreensão geral de matemática em linguagem natural.",
    ]

    _ALLOWED_NODES = (
        ast.Expression, ast.Constant, ast.Name, ast.Load,
        ast.UnaryOp, ast.UAdd, ast.USub,
        ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow,
    )

    @classmethod
    def _check_name(cls, name: Any) -> str:
        if (
            not isinstance(name, str)
            or not name.isidentifier()
            or keyword.iskeyword(name)
            or len(name) > cls.MAX_NAME_LENGTH
            or name.startswith("__")
        ):
            raise MathematicsEngineError("Nome de variável inválido.")
        return name

    @classmethod
    def _checked_fraction(cls, value: Fraction) -> Fraction:
        if not isinstance(value, Fraction):
            value = Fraction(value)
        if (
            abs(value.numerator).bit_length() > cls.MAX_INTEGER_BITS
            or value.denominator.bit_length() > cls.MAX_INTEGER_BITS
        ):
            raise MathematicsEngineError(
                "Resultado excede o limite de tamanho para aritmética exata."
            )
        return value

    @classmethod
    def _coerce_number(cls, value: Any) -> Fraction:
        if isinstance(value, bool):
            raise MathematicsEngineError("Booleanos não são valores matemáticos aceitos.")
        if isinstance(value, Fraction):
            return cls._checked_fraction(value)
        if isinstance(value, int):
            if abs(value).bit_length() > cls.MAX_INTEGER_BITS:
                raise MathematicsEngineError("Inteiro de variável excede o limite de bits.")
            return cls._checked_fraction(Fraction(value))
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise MathematicsEngineError("O valor decimal precisa ser finito.")
            decimal_tuple = value.as_tuple()
            if (
                len(decimal_tuple.digits) + abs(decimal_tuple.exponent)
            ) * 4 > cls.MAX_INTEGER_BITS:
                raise MathematicsEngineError("Decimal de variável excede o orçamento de tamanho.")
            try:
                return cls._checked_fraction(Fraction(value))
            except (ValueError, OverflowError, ZeroDivisionError) as exc:
                raise MathematicsEngineError("Valor decimal inválido.") from exc
        if isinstance(value, float):
            if not math.isfinite(value):
                raise MathematicsEngineError("O valor decimal precisa ser finito.")
            return cls._checked_fraction(Fraction(str(value)))
        raise MathematicsEngineError(
            "Variáveis aceitam somente int, Fraction, Decimal ou float finito."
        )

    @classmethod
    def _parse_expression(cls, expression: Any) -> tuple[ast.Expression, str]:
        if not isinstance(expression, str):
            raise MathematicsEngineError("A expressão precisa ser texto.")
        if len(expression) > cls.MAX_EXPRESSION_LENGTH:
            raise MathematicsEngineError(
                f"A expressão precisa ter entre 1 e {cls.MAX_EXPRESSION_LENGTH} caracteres."
            )
        source = expression.strip()
        if not source:
            raise MathematicsEngineError(
                f"A expressão precisa ter entre 1 e {cls.MAX_EXPRESSION_LENGTH} caracteres."
            )
        try:
            root = ast.parse(source, mode="eval")
        except (SyntaxError, ValueError, TypeError, RecursionError) as exc:
            raise MathematicsEngineError("Expressão matemática inválida.") from exc

        count = 0
        stack = [(root, 1)]
        while stack:
            node, depth = stack.pop()
            count += 1
            if count > cls.MAX_AST_NODES:
                raise MathematicsEngineError("Expressão excede o limite de operações.")
            if depth > cls.MAX_AST_DEPTH:
                raise MathematicsEngineError("Expressão excede o limite de profundidade.")
            if not isinstance(node, cls._ALLOWED_NODES):
                raise MathematicsEngineError(
                    f"Construção não permitida na expressão: {type(node).__name__}."
                )
            if isinstance(node, ast.Name):
                cls._check_name(node.id)
            if isinstance(node, ast.Constant):
                if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                    raise MathematicsEngineError("Somente constantes numéricas são permitidas.")
            stack.extend(
                (child, depth + 1)
                for child in ast.iter_child_nodes(node)
            )
        return root, source

    @classmethod
    def _literal_fraction(cls, node: ast.Constant, source: str) -> Fraction:
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise MathematicsEngineError("Constante numérica não suportada.")
        if isinstance(node.value, int):
            return cls._checked_fraction(Fraction(node.value))
        segment = ast.get_source_segment(source, node)
        if not isinstance(segment, str):
            raise MathematicsEngineError("Não foi possível ler a constante numérica.")
        try:
            # Parsing the original decimal token avoids binary-float rounding.
            return cls._checked_fraction(Fraction(segment.replace("_", "")))
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            raise MathematicsEngineError("Constante decimal inválida.") from exc

    @classmethod
    def _pow_fraction(cls, base: Fraction, exponent: int) -> Fraction:
        if abs(exponent) > cls.MAX_EXPONENT:
            raise MathematicsEngineError(
                f"O expoente inteiro deve estar entre {-cls.MAX_EXPONENT} e {cls.MAX_EXPONENT}."
            )
        if exponent == 0:
            if base == 0:
                raise MathematicsEngineError("A expressão 0**0 não está definida.")
            return Fraction(1)
        base_bits = max(
            abs(base.numerator).bit_length(),
            base.denominator.bit_length(),
        )
        if base_bits * abs(exponent) > cls.MAX_INTEGER_BITS:
            raise MathematicsEngineError(
                "Potência excede o orçamento de tamanho da aritmética exata."
            )
        try:
            return cls._checked_fraction(base ** exponent)
        except ZeroDivisionError as exc:
            raise MathematicsEngineError("Zero não pode ter expoente negativo.") from exc

    @classmethod
    def _evaluate_node(
        cls,
        node: ast.AST,
        variables: Mapping[str, Fraction],
        source: str,
    ) -> Fraction:
        if isinstance(node, ast.Constant):
            return cls._literal_fraction(node, source)
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise MathematicsEngineError(
                    f"Variável '{node.id}' não foi fornecida."
                )
            return variables[node.id]
        if isinstance(node, ast.UnaryOp):
            value = cls._evaluate_node(node.operand, variables, source)
            if isinstance(node.op, ast.UAdd):
                return value
            if isinstance(node.op, ast.USub):
                return cls._checked_fraction(-value)
            raise MathematicsEngineError("Operador unário não permitido.")
        if isinstance(node, ast.BinOp):
            left = cls._evaluate_node(node.left, variables, source)
            if isinstance(node.op, ast.Pow):
                exponent_value = cls._evaluate_node(node.right, {}, source)
                if exponent_value.denominator != 1:
                    raise MathematicsEngineError("O expoente precisa ser inteiro.")
                return cls._pow_fraction(left, exponent_value.numerator)
            right = cls._evaluate_node(node.right, variables, source)
            try:
                if isinstance(node.op, ast.Add):
                    result = left + right
                elif isinstance(node.op, ast.Sub):
                    result = left - right
                elif isinstance(node.op, ast.Mult):
                    result = left * right
                elif isinstance(node.op, ast.Div):
                    if right == 0:
                        raise MathematicsEngineError("Divisão por zero.")
                    result = left / right
                else:
                    raise MathematicsEngineError("Operador matemático não permitido.")
            except ZeroDivisionError as exc:
                raise MathematicsEngineError("Divisão por zero.") from exc
            return cls._checked_fraction(result)
        raise MathematicsEngineError(
            f"Construção matemática não suportada: {type(node).__name__}."
        )

    @staticmethod
    def _format_fraction(value: Fraction) -> dict[str, Any]:
        exact = (
            str(value.numerator)
            if value.denominator == 1
            else f"{value.numerator}/{value.denominator}"
        )
        return {
            "numerator": value.numerator,
            "denominator": value.denominator,
            "exact": exact,
            "kind": "integer" if value.denominator == 1 else "rational",
        }

    @classmethod
    def _parse_variables(cls, variables: Any) -> dict[str, Fraction]:
        if variables is None:
            return {}
        if not isinstance(variables, Mapping) or len(variables) > cls.MAX_VARIABLES:
            raise MathematicsEngineError(
                f"variables precisa ser um mapeamento com até {cls.MAX_VARIABLES} entradas."
            )
        parsed = {}
        for name, value in variables.items():
            valid_name = cls._check_name(name)
            parsed[valid_name] = cls._coerce_number(value)
        return parsed

    def evaluate_expression(
        self,
        expression: str,
        variables: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        root, source = self._parse_expression(expression)
        parsed_variables = self._parse_variables(variables)
        value = self._evaluate_node(root.body, parsed_variables, source)
        used_variables = sorted({
            node.id for node in ast.walk(root) if isinstance(node, ast.Name)
        })
        return {
            "engine": "MathematicsEngine",
            "version": self.VERSION,
            "status": "evaluated",
            "expression": source,
            "value": self._format_fraction(value),
            "variables": used_variables,
            "arithmetic": "exact_fraction",
            "code_execution": False,
        }

    def _linear_form(
        self,
        node: ast.AST,
        variable: str | None,
        source: str,
    ) -> tuple[Fraction, Fraction]:
        """Return (coefficient, constant) for an affine expression a*x+b."""
        if isinstance(node, ast.Constant):
            return Fraction(0), self._literal_fraction(node, source)
        if isinstance(node, ast.Name):
            if variable is None or node.id != variable:
                raise MathematicsEngineError(
                    "A equação contém mais de uma variável ou variável não selecionada."
                )
            return Fraction(1), Fraction(0)
        if isinstance(node, ast.UnaryOp):
            coefficient, constant = self._linear_form(node.operand, variable, source)
            if isinstance(node.op, ast.UAdd):
                return coefficient, constant
            if isinstance(node.op, ast.USub):
                return (
                    self._checked_fraction(-coefficient),
                    self._checked_fraction(-constant),
                )
            raise MathematicsEngineError("Operador unário não permitido na equação.")
        if isinstance(node, ast.BinOp):
            left_a, left_b = self._linear_form(node.left, variable, source)
            if isinstance(node.op, ast.Pow):
                exponent = self._evaluate_node(node.right, {}, source)
                if exponent.denominator != 1:
                    raise MathematicsEngineError("O expoente precisa ser inteiro.")
                power = exponent.numerator
                if power == 0:
                    if left_a != 0:
                        raise MathematicsEngineError(
                            "Expoente zero em expressão variável exige restrição de domínio não suportada."
                        )
                    if left_b == 0:
                        raise MathematicsEngineError("A expressão 0**0 não está definida.")
                    return Fraction(0), Fraction(1)
                if power == 1:
                    return left_a, left_b
                if left_a != 0:
                    raise MathematicsEngineError("A equação não é linear.")
                return Fraction(0), self._pow_fraction(left_b, power)

            right_a, right_b = self._linear_form(node.right, variable, source)
            if isinstance(node.op, ast.Add):
                return (
                    self._checked_fraction(left_a + right_a),
                    self._checked_fraction(left_b + right_b),
                )
            if isinstance(node.op, ast.Sub):
                return (
                    self._checked_fraction(left_a - right_a),
                    self._checked_fraction(left_b - right_b),
                )
            if isinstance(node.op, ast.Mult):
                if left_a != 0 and right_a != 0:
                    raise MathematicsEngineError("A equação não é linear.")
                coefficient = left_a * right_b + right_a * left_b
                constant = left_b * right_b
                return (
                    self._checked_fraction(coefficient),
                    self._checked_fraction(constant),
                )
            if isinstance(node.op, ast.Div):
                if right_a != 0:
                    raise MathematicsEngineError(
                        "Divisão por expressão que contém a variável não é linear."
                    )
                if right_b == 0:
                    raise MathematicsEngineError("Divisão por zero na equação.")
                return (
                    self._checked_fraction(left_a / right_b),
                    self._checked_fraction(left_b / right_b),
                )
            raise MathematicsEngineError("Operador não permitido na equação.")
        raise MathematicsEngineError("Construção não suportada na equação.")

    def solve_linear_equation(
        self,
        equation: str,
        variable: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(equation, str):
            raise MathematicsEngineError("A equação precisa ser texto.")
        if len(equation) > self.MAX_EQUATION_LENGTH:
            raise MathematicsEngineError(
                f"A equação excede {self.MAX_EQUATION_LENGTH} caracteres."
            )
        source = equation.strip()
        if not source or source.count("=") != 1:
            raise MathematicsEngineError(
                "Informe uma equação com exatamente um sinal de igualdade."
            )
        left_source, right_source = (part.strip() for part in source.split("=", 1))
        if not left_source or not right_source:
            raise MathematicsEngineError("Os dois lados da equação precisam estar preenchidos.")
        left_root, left_text = self._parse_expression(left_source)
        right_root, right_text = self._parse_expression(right_source)

        names = sorted({
            node.id
            for root in (left_root, right_root)
            for node in ast.walk(root)
            if isinstance(node, ast.Name)
        })
        if variable is not None:
            variable = self._check_name(variable)
            if any(name != variable for name in names):
                raise MathematicsEngineError(
                    "A equação contém uma variável diferente da variável selecionada."
                )
        elif len(names) > 1:
            raise MathematicsEngineError(
                "A equação contém múltiplas variáveis; informe uma equação com uma variável."
            )
        else:
            variable = names[0] if names else None

        left_a, left_b = self._linear_form(left_root.body, variable, left_text)
        right_a, right_b = self._linear_form(right_root.body, variable, right_text)
        coefficient = self._checked_fraction(left_a - right_a)
        constant = self._checked_fraction(right_b - left_b)

        base_result = {
            "engine": "MathematicsEngine",
            "version": self.VERSION,
            "equation": source,
            "variable": variable,
            "method": "exact_affine_reduction",
            "code_execution": False,
        }

        if coefficient == 0:
            if constant == 0:
                return {
                    **base_result,
                    "status": "infinitely_many_solutions",
                    "solution": None,
                    "verified": None,
                }
            return {
                **base_result,
                "status": "no_solution",
                "solution": None,
                "verified": None,
            }

        if variable is None:
            raise MathematicsEngineError("Não foi possível identificar a variável.")
        solution = self._checked_fraction(constant / coefficient)
        substitutions = {variable: solution}
        left_value = self._evaluate_node(left_root.body, substitutions, left_text)
        right_value = self._evaluate_node(right_root.body, substitutions, right_text)
        verified = left_value == right_value
        return {
            **base_result,
            "status": "solved" if verified else "verification_failed",
            "solution": {
                "variable": variable,
                **self._format_fraction(solution),
            },
            "verification": {
                "performed": True,
                "left": self._format_fraction(left_value),
                "right": self._format_fraction(right_value),
                "equal": verified,
            },
            "verified": verified,
        }

    def _linear_form_many(
        self,
        node: ast.AST,
        variables: set[str],
        source: str,
    ) -> tuple[dict[str, Fraction], Fraction]:
        """Return sparse coefficients and constant for an affine expression."""
        if isinstance(node, ast.Constant):
            return {}, self._literal_fraction(node, source)
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise MathematicsEngineError(
                    f"Variável '{node.id}' não pertence ao sistema selecionado."
                )
            return {node.id: Fraction(1)}, Fraction(0)
        if isinstance(node, ast.UnaryOp):
            coefficients, constant = self._linear_form_many(
                node.operand, variables, source
            )
            if isinstance(node.op, ast.UAdd):
                return coefficients, constant
            if isinstance(node.op, ast.USub):
                return (
                    {
                        name: self._checked_fraction(-value)
                        for name, value in coefficients.items()
                    },
                    self._checked_fraction(-constant),
                )
            raise MathematicsEngineError("Operador unário não permitido no sistema.")

        if not isinstance(node, ast.BinOp):
            raise MathematicsEngineError("Construção não suportada no sistema.")

        left_coefficients, left_constant = self._linear_form_many(
            node.left, variables, source
        )
        if isinstance(node.op, ast.Pow):
            exponent = self._evaluate_node(node.right, {}, source)
            if exponent.denominator != 1:
                raise MathematicsEngineError("O expoente precisa ser inteiro.")
            power = exponent.numerator
            if power == 0:
                if left_coefficients:
                    raise MathematicsEngineError(
                        "Expoente zero em expressão variável exige restrição de domínio não suportada."
                    )
                if left_constant == 0:
                    raise MathematicsEngineError("A expressão 0**0 não está definida.")
                return {}, Fraction(1)
            if power == 1:
                return left_coefficients, left_constant
            if left_coefficients:
                raise MathematicsEngineError("O sistema contém termo não linear.")
            return {}, self._pow_fraction(left_constant, power)

        right_coefficients, right_constant = self._linear_form_many(
            node.right, variables, source
        )
        if isinstance(node.op, ast.Add):
            result = dict(left_coefficients)
            for name, value in right_coefficients.items():
                result[name] = self._checked_fraction(
                    result.get(name, Fraction(0)) + value
                )
            return (
                {name: value for name, value in result.items() if value != 0},
                self._checked_fraction(left_constant + right_constant),
            )
        if isinstance(node.op, ast.Sub):
            result = dict(left_coefficients)
            for name, value in right_coefficients.items():
                result[name] = self._checked_fraction(
                    result.get(name, Fraction(0)) - value
                )
            return (
                {name: value for name, value in result.items() if value != 0},
                self._checked_fraction(left_constant - right_constant),
            )
        if isinstance(node.op, ast.Mult):
            if left_coefficients and right_coefficients:
                raise MathematicsEngineError("O sistema contém produto entre variáveis.")
            if left_coefficients:
                scale = right_constant
                coefficients = {
                    name: self._checked_fraction(value * scale)
                    for name, value in left_coefficients.items()
                }
                constant = self._checked_fraction(left_constant * right_constant)
            elif right_coefficients:
                scale = left_constant
                coefficients = {
                    name: self._checked_fraction(value * scale)
                    for name, value in right_coefficients.items()
                }
                constant = self._checked_fraction(left_constant * right_constant)
            else:
                coefficients = {}
                constant = self._checked_fraction(left_constant * right_constant)
            return (
                {name: value for name, value in coefficients.items() if value != 0},
                constant,
            )
        if isinstance(node.op, ast.Div):
            if right_coefficients:
                raise MathematicsEngineError(
                    "Divisão por expressão com variável não é linear."
                )
            if right_constant == 0:
                raise MathematicsEngineError("Divisão por zero no sistema.")
            return (
                {
                    name: self._checked_fraction(value / right_constant)
                    for name, value in left_coefficients.items()
                },
                self._checked_fraction(left_constant / right_constant),
            )
        raise MathematicsEngineError("Operador não permitido no sistema.")

    def solve_linear_system(
        self,
        equations: list[str],
        variables: list[str] | None = None,
    ) -> dict[str, Any]:
        """Solve a bounded linear system by exact Gauss-Jordan elimination."""
        if (
            not isinstance(equations, list)
            or not equations
            or len(equations) > self.MAX_SYSTEM_EQUATIONS
        ):
            raise MathematicsEngineError(
                f"Informe de 1 a {self.MAX_SYSTEM_EQUATIONS} equações."
            )
        if any(not isinstance(item, str) for item in equations):
            raise MathematicsEngineError("Todas as equações precisam ser texto.")
        if sum(len(item) for item in equations) > self.MAX_SYSTEM_TOTAL_LENGTH:
            raise MathematicsEngineError("O sistema excede o limite total de caracteres.")

        parsed_equations = []
        names = set()
        for equation in equations:
            if not equation.strip() or equation.count("=") != 1:
                raise MathematicsEngineError(
                    "Cada equação precisa conter exatamente um sinal de igualdade."
                )
            left_source, right_source = (
                part.strip() for part in equation.split("=", 1)
            )
            if not left_source or not right_source:
                raise MathematicsEngineError("Os dois lados de cada equação são obrigatórios.")
            left_root, left_text = self._parse_expression(left_source)
            right_root, right_text = self._parse_expression(right_source)
            equation_names = {
                node.id
                for root in (left_root, right_root)
                for node in ast.walk(root)
                if isinstance(node, ast.Name)
            }
            names.update(equation_names)
            parsed_equations.append((
                equation.strip(), left_root, left_text, right_root, right_text
            ))

        if variables is None:
            variable_names = sorted(names)
        else:
            if (
                not isinstance(variables, list)
                or len(variables) > self.MAX_SYSTEM_VARIABLES
            ):
                raise MathematicsEngineError(
                    f"variables precisa ser uma lista com até {self.MAX_SYSTEM_VARIABLES} nomes."
                )
            variable_names = [self._check_name(item) for item in variables]
            if len(variable_names) != len(set(variable_names)):
                raise MathematicsEngineError("A lista de variáveis contém duplicatas.")
            if not names.issubset(set(variable_names)):
                raise MathematicsEngineError(
                    "A equação contém variável ausente da lista selecionada."
                )

        if len(variable_names) > self.MAX_SYSTEM_VARIABLES:
            raise MathematicsEngineError(
                f"O sistema aceita até {self.MAX_SYSTEM_VARIABLES} variáveis."
            )
        variable_set = set(variable_names)

        matrix = []
        for equation, left_root, left_text, right_root, right_text in parsed_equations:
            left_coefficients, left_constant = self._linear_form_many(
                left_root.body, variable_set, left_text
            )
            right_coefficients, right_constant = self._linear_form_many(
                right_root.body, variable_set, right_text
            )
            row = [
                self._checked_fraction(
                    left_coefficients.get(name, Fraction(0))
                    - right_coefficients.get(name, Fraction(0))
                )
                for name in variable_names
            ]
            row.append(self._checked_fraction(right_constant - left_constant))
            matrix.append(row)

        pivot_row = 0
        pivot_columns = []
        for column in range(len(variable_names)):
            pivot = next(
                (
                    index for index in range(pivot_row, len(matrix))
                    if matrix[index][column] != 0
                ),
                None,
            )
            if pivot is None:
                continue
            matrix[pivot_row], matrix[pivot] = matrix[pivot], matrix[pivot_row]
            divisor = matrix[pivot_row][column]
            matrix[pivot_row] = [
                self._checked_fraction(value / divisor)
                for value in matrix[pivot_row]
            ]
            for row_index in range(len(matrix)):
                if row_index == pivot_row:
                    continue
                factor = matrix[row_index][column]
                if factor == 0:
                    continue
                matrix[row_index] = [
                    self._checked_fraction(
                        matrix[row_index][index]
                        - factor * matrix[pivot_row][index]
                    )
                    for index in range(len(variable_names) + 1)
                ]
            pivot_columns.append(column)
            pivot_row += 1
            if pivot_row == len(matrix):
                break

        rank = len(pivot_columns)
        inconsistent = any(
            all(value == 0 for value in row[:-1]) and row[-1] != 0
            for row in matrix
        )
        base_result = {
            "engine": "MathematicsEngine",
            "version": self.VERSION,
            "equation_count": len(parsed_equations),
            "variables": list(variable_names),
            "rank": rank,
            "method": "exact_gauss_jordan",
            "code_execution": False,
        }
        if inconsistent:
            return {
                **base_result,
                "status": "no_solution",
                "solution": None,
                "verified": None,
            }

        free_columns = [
            index for index in range(len(variable_names))
            if index not in pivot_columns
        ]
        if free_columns:
            return {
                **base_result,
                "status": "underdetermined",
                "solution": None,
                "pivot_variables": [
                    variable_names[index] for index in pivot_columns
                ],
                "free_variables": [
                    variable_names[index] for index in free_columns
                ],
                "verified": None,
            }

        solution_values = {
            variable_names[column]: matrix[row_index][-1]
            for row_index, column in enumerate(pivot_columns)
        }
        verification = []
        for equation, left_root, left_text, right_root, right_text in parsed_equations:
            left_value = self._evaluate_node(
                left_root.body, solution_values, left_text
            )
            right_value = self._evaluate_node(
                right_root.body, solution_values, right_text
            )
            verification.append({
                "equation": equation,
                "left": self._format_fraction(left_value),
                "right": self._format_fraction(right_value),
                "equal": left_value == right_value,
            })
        verified = all(item["equal"] for item in verification)
        return {
            **base_result,
            "status": "solved" if verified else "verification_failed",
            "solution": {
                name: self._format_fraction(solution_values[name])
                for name in variable_names
            },
            "verification": verification,
            "verified": verified,
        }

    def status(self) -> dict[str, Any]:
        return {
            "component": "MathematicsEngine",
            "version": self.VERSION,
            "available": True,
            "arithmetic": "exact_fraction",
            "expression_parser": "bounded_python_ast_whitelist",
            "linear_equation_solver": True,
            "linear_system_solver": True,
            "max_system_equations": self.MAX_SYSTEM_EQUATIONS,
            "max_system_variables": self.MAX_SYSTEM_VARIABLES,
            "solution_substitution_verification": True,
            "supported_operators": list(self.SUPPORTED_OPERATORS),
            "external_dependencies": [],
            "code_execution": False,
            "autonomous_execution": False,
            "limitations": list(self.LIMITATIONS),
        }
