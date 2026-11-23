"""Bounded, provenance-aware sensing for the Mahoraga core.

This module samples only explicitly selected Android sensors through Termux:API.
It never opens the camera or microphone, never streams continuously, and never
assumes that a sensor exists or that its values have calibrated units.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any, Callable


class PerceptionError(ValueError):
    """Invalid or unsafe perception request."""


class PerceptionEngine:
    VERSION = "0.2.0"
    MAX_SENSORS_PER_BATCH = 4
    MAX_SENSOR_NAME = 160
    MIN_DELAY_MS = 250
    MAX_DELAY_MS = 5000
    COMMAND_TIMEOUT_SECONDS = 8
    MAX_OUTPUT_BYTES = 64_000

    def __init__(
        self,
        store,
        hardware,
        dharma,
        command_runner: Callable[[list[str], int], dict] | None = None,
    ):
        self.store = store
        self.hardware = hardware
        self.dharma = dharma
        self._command_runner = command_runner or self._run_command

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    def _authorize(self, action: str) -> None:
        decision = self.dharma.evaluate(action)
        if not decision.allowed:
            raise PermissionError(decision.reason)

    @classmethod
    def _validate_command_result(cls, result: Any) -> dict:
        if not isinstance(result, dict):
            raise PerceptionError("O executor de comando retornou uma estrutura inválida.")
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        if not isinstance(stdout, str) or not isinstance(stderr, str):
            raise PerceptionError("A saída do comando precisa ser texto.")
        available = result.get("available", False)
        returncode = result.get("returncode")
        if not isinstance(available, bool):
            raise PerceptionError("available precisa ser booleano.")
        if returncode is not None and (
            isinstance(returncode, bool) or not isinstance(returncode, int)
        ):
            raise PerceptionError("returncode precisa ser inteiro ou None.")
        status = result.get("status", "completed")
        if not isinstance(status, str):
            raise PerceptionError("status precisa ser texto.")
        return {
            "available": available,
            "returncode": returncode,
            "stdout": stdout[: cls.MAX_OUTPUT_BYTES],
            "stderr": stderr[: 4000],
            "status": status[:80],
        }

    @classmethod
    def _run_command(cls, argv: list[str], timeout: int) -> dict:
        """Run a fixed Termux:API command with shell=False and bounded output."""
        if not argv or argv[0] != "termux-sensor":
            return {
                "available": False,
                "status": "command_not_allowlisted",
                "stdout": "",
                "stderr": "",
            }
        executable = shutil.which("termux-sensor")
        if not executable:
            return {
                "available": False,
                "status": "termux_sensor_not_found",
                "stdout": "",
                "stderr": "",
            }
        try:
            result = subprocess.run(
                [executable, *argv[1:]],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "available": True,
                "status": "timeout",
                "returncode": None,
                "stdout": "",
                "stderr": "termux-sensor ultrapassou o tempo limite.",
            }
        except OSError as exc:
            return {
                "available": False,
                "status": f"os_error:{type(exc).__name__}",
                "returncode": None,
                "stdout": "",
                "stderr": str(exc)[:1000],
            }
        return {
            "available": True,
            "status": "completed" if result.returncode == 0 else "command_failed",
            "returncode": result.returncode,
            "stdout": result.stdout[: cls.MAX_OUTPUT_BYTES],
            "stderr": result.stderr[:4000],
        }

    @classmethod
    def _parse_sensor_list(cls, stdout: str) -> list[str]:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise PerceptionError("termux-sensor -l não retornou JSON válido.") from exc
        if isinstance(payload, dict):
            values = payload.get("sensors")
        else:
            values = payload
        if not isinstance(values, list):
            raise PerceptionError("A lista de sensores não contém uma coleção.")
        names = []
        seen = set()
        for item in values[:500]:
            if isinstance(item, str):
                name = item.strip()
            elif isinstance(item, dict) and isinstance(item.get("name"), str):
                name = item["name"].strip()
            else:
                continue
            if not name or len(name) > cls.MAX_SENSOR_NAME:
                continue
            key = name.casefold()
            if key not in seen:
                seen.add(key)
                names.append(name)
        return names

    def inventory(self) -> dict:
        """Return the sensor names exposed by this device right now."""
        self._authorize("inspect_hardware")
        result = self._validate_command_result(
            self._command_runner(["termux-sensor", "-l"], self.COMMAND_TIMEOUT_SECONDS)
        )
        if not result["available"] or result["returncode"] != 0:
            return {
                "component": "PerceptionEngine",
                "version": self.VERSION,
                "status": result["status"],
                "available": False,
                "sensors": [],
                "stderr": result["stderr"],
                "continuous_sampling": False,
            }
        try:
            names = self._parse_sensor_list(result["stdout"])
        except PerceptionError as exc:
            return {
                "component": "PerceptionEngine",
                "version": self.VERSION,
                "status": "invalid_sensor_inventory",
                "available": False,
                "sensors": [],
                "reason": str(exc),
                "continuous_sampling": False,
            }
        return {
            "component": "PerceptionEngine",
            "version": self.VERSION,
            "status": "available" if names else "no_sensors_reported",
            "available": bool(names),
            "sensors": names,
            "sensor_count": len(names),
            "source": "Termux:API termux-sensor -l",
            "captured_at": self._now(),
            "continuous_sampling": False,
            "limitations": [
                "A lista depende do hardware, Android, permissões e da versão instalada do Termux:API.",
                "Nomes não comprovam calibração, unidade física ou precisão.",
                "Câmera e microfone são interfaces de captura separadas e não são ativados por esta operação.",
            ],
        }

    @classmethod
    def _parse_sample(cls, stdout: str, requested_name: str) -> dict:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise PerceptionError("A amostra do sensor não é JSON válido.") from exc
        if not isinstance(payload, dict):
            raise PerceptionError("A amostra do sensor precisa ser um objeto JSON.")
        exact = [
            (key, value) for key, value in payload.items()
            if isinstance(key, str) and key.casefold() == requested_name.casefold()
        ]
        matches = exact or [
            (key, value) for key, value in payload.items()
            if isinstance(key, str) and requested_name.casefold() in key.casefold()
        ]
        if len(matches) != 1:
            raise PerceptionError(
                "A resposta não identifica exatamente um sensor; amostra rejeitada."
            )
        actual_name, reading = matches[0]
        if not isinstance(reading, dict):
            raise PerceptionError("A leitura do sensor possui formato inválido.")
        values = reading.get("values")
        if not isinstance(values, list) or not values or len(values) > 16:
            raise PerceptionError("O sensor não retornou um vetor de valores válido.")
        clean_values = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise PerceptionError("A leitura contém um valor não numérico.")
            try:
                number = float(value)
            except (OverflowError, TypeError, ValueError) as exc:
                raise PerceptionError("A leitura não é representável como número finito.") from exc
            if not math.isfinite(number):
                raise PerceptionError("A leitura contém NaN ou infinito.")
            clean_values.append(number)
        accuracy = reading.get("accuracy")
        if isinstance(accuracy, bool) or not isinstance(accuracy, (int, float)):
            accuracy = None
        else:
            try:
                accuracy_number = float(accuracy)
            except (OverflowError, TypeError, ValueError):
                accuracy_number = math.nan
            if not math.isfinite(accuracy_number):
                accuracy = None
            else:
                accuracy = int(accuracy_number)
        return {
            "sensor_name": actual_name[: cls.MAX_SENSOR_NAME],
            "values": clean_values,
            "accuracy": accuracy,
        }

    def sample_sensors(
        self,
        sensor_names: list[str],
        *,
        delay_ms: int = 1000,
    ) -> dict:
        """Take one bounded sample per explicitly selected sensor and persist it.

        The finite '-n 1' argument is mandatory: this API never starts a stream.
        Sensor names must appear in a fresh device inventory.
        """
        self._authorize("inspect_hardware")
        self._authorize("record_observation")
        if not isinstance(sensor_names, list) or not sensor_names:
            raise PerceptionError("Informe ao menos um sensor.")
        if len(sensor_names) > self.MAX_SENSORS_PER_BATCH:
            raise PerceptionError(
                f"Cada lote aceita no máximo {self.MAX_SENSORS_PER_BATCH} sensores."
            )
        if (
            isinstance(delay_ms, bool)
            or not isinstance(delay_ms, int)
            or not self.MIN_DELAY_MS <= delay_ms <= self.MAX_DELAY_MS
        ):
            raise PerceptionError(
                f"delay_ms deve estar entre {self.MIN_DELAY_MS} e {self.MAX_DELAY_MS}."
            )
        if any(
            not isinstance(name, str)
            or not name.strip()
            or len(name) > self.MAX_SENSOR_NAME
            for name in sensor_names
        ):
            raise PerceptionError("Nome de sensor inválido.")
        requested = [name.strip() for name in sensor_names]
        if len({name.casefold() for name in requested}) != len(requested):
            raise PerceptionError("A lista contém sensores repetidos.")

        inventory = self.inventory()
        if not inventory["available"]:
            return {
                "component": "PerceptionEngine",
                "status": "unavailable",
                "sampled": [],
                "failures": [{"reason": inventory.get("reason") or inventory["status"]}],
                "continuous_sampling": False,
            }
        available = {name.casefold(): name for name in inventory["sensors"]}
        unknown = [name for name in requested if name.casefold() not in available]
        if unknown:
            raise PerceptionError(
                "Sensores não encontrados no inventário atual: " + ", ".join(unknown)
            )
        # Termux:API accepts partial sensor names and may choose the shortest
        # match. Reject collisions instead of silently sampling the wrong sensor.
        ambiguous = {}
        for requested_name in requested:
            matches = [
                name for name in inventory["sensors"]
                if requested_name.casefold() in name.casefold()
            ]
            if len(matches) > 1:
                ambiguous[requested_name] = matches
        if ambiguous:
            raise PerceptionError(
                "Nome parcial corresponde a mais de um sensor; escolha um nome que identifique somente um: "
                + "; ".join(
                    f"{requested_name}: {', '.join(matches)}"
                    for requested_name, matches in ambiguous.items()
                )
            )

        sampled = []
        failures = []
        for requested_name in requested:
            actual_requested = available[requested_name.casefold()]
            command = [
                "termux-sensor",
                "-s", actual_requested,
                "-d", str(delay_ms),
                "-n", "1",
            ]
            result = self._validate_command_result(
                self._command_runner(command, self.COMMAND_TIMEOUT_SECONDS)
            )
            if not result["available"] or result["returncode"] != 0:
                failures.append({
                    "sensor_name": actual_requested,
                    "status": result["status"],
                    "stderr": result["stderr"],
                })
                continue
            try:
                reading = self._parse_sample(result["stdout"], actual_requested)
            except PerceptionError as exc:
                failures.append({
                    "sensor_name": actual_requested,
                    "status": "invalid_sample",
                    "reason": str(exc),
                })
                continue

            captured_at = self._now()
            limitations = [
                "Valores são reportados pelo sensor do aparelho e não foram calibrados independentemente.",
                "A unidade é preservada como desconhecida quando não informada pelo sistema.",
                "A leitura é pontual; nenhuma transmissão contínua foi iniciada.",
            ]
            observation_data = {
                **reading,
                "captured_at": captured_at,
                "sampling": {
                    "source": "Termux:API termux-sensor",
                    "delay_ms": delay_ms,
                    "sample_count": 1,
                    "continuous": False,
                },
                "epistemic_state": "device_reported_not_independently_calibrated",
            }
            persisted = self.store.record_observation_and_event(
                category="sensor_sample",
                subject=reading["sensor_name"],
                data=observation_data,
                source="PerceptionEngine.TermuxAPI",
                event_type="perception.sensor_sampled",
                event_payload={
                    "sensor_name": reading["sensor_name"],
                    "captured_at": captured_at,
                    "sample_count": 1,
                    "continuous": False,
                },
                limitations=limitations,
            )
            sampled.append({
                **observation_data,
                "observation_id": persisted["observation_id"],
                "event_id": persisted["event_id"],
            })

        return {
            "component": "PerceptionEngine",
            "status": (
                "completed" if sampled and not failures
                else "partial" if sampled
                else "failed"
            ),
            "sampled": sampled,
            "failures": failures,
            "sample_count": len(sampled),
            "continuous_sampling": False,
            "side_effects": {
                "sensor_stream_started": False,
                "camera_opened": False,
                "microphone_opened": False,
                "raw_audio_or_image_saved": False,
            },
        }

    def operational_state(self) -> dict:
        """Read the existing hardware self-model without enabling new sensors."""
        self._authorize("inspect_hardware")
        return {
            "component": "PerceptionEngine",
            "source": "HardwareIntelligence",
            "captured_at": self._now(),
            "battery": self.hardware.battery(),
            "memory": self.hardware.memory(),
            "storage": self.hardware.storage(),
            "thermal": self.hardware.thermal(),
            "cpu": self.hardware.cpu(),
            "limitations": [
                "Operational telemetry is an engineering self-state, not a subjective or biological sensation.",
                "Thermal-zone values remain raw/candidate values until the Android thermal service confirms their interpretation.",
            ],
        }

    def status(self) -> dict:
        return {
            "component": "PerceptionEngine",
            "version": self.VERSION,
            "capabilities": {
                "android_sensors": "bounded_single_sample",
                "battery_thermal_memory_cpu_storage": "read_only_via_HardwareIntelligence",
                "camera": "not_implemented_requires_foreground_capture_and_runtime_permission",
                "microphone": "not_implemented_requires_foreground_capture_and_runtime_permission",
                "speaker": "output_actuator_not_a_sensor",
            },
            "continuous_sampling": False,
            "shared_store": self.store is not None,
        }
