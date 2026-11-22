"""Deep, read-only diagnostics for Android/Termux hardware and access paths.

No tuning, writes to sysfs, root escalation, package installation, or arbitrary
shell input. Raw observations are retained separately from interpretations.
"""
from __future__ import annotations
import glob
import json
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class HardwareDeepDiagnostics:
    VERSION = "1.0.0"
    MAX_TEXT = 24_000

    def __init__(self, project_root: str | Path | None = None, timeout: int = 8, store=None):
        self.root = Path(project_root or Path(__file__).resolve().parent.parent).expanduser().resolve()
        self.timeout = max(2, min(int(timeout), 20))
        self.store = store
        self._rish_path = self._find_rish()

    @staticmethod
    def _utc() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _read(self, path: str, limit: int = 8192) -> dict[str, Any]:
        try:
            with open(path, "rb") as stream:
                raw = stream.read(limit + 1)
            truncated = len(raw) > limit
            raw = raw[:limit]
            return {"status": "readable", "value": raw.decode("utf-8", "replace").strip(),
                    "truncated": truncated}
        except PermissionError:
            return {"status": "permission_denied"}
        except FileNotFoundError:
            return {"status": "not_found"}
        except OSError as exc:
            return {"status": "os_error", "error": type(exc).__name__}

    def _run(self, argv: list[str], timeout: int | None = None) -> dict[str, Any]:
        allowed_getprop = {
            "ro.product.manufacturer", "ro.product.model", "ro.product.device",
            "ro.build.version.release", "ro.build.version.sdk", "ro.hardware",
            "ro.hardware.egl", "ro.hardware.vulkan", "ro.opengles.version",
            "ro.build.fingerprint",
        }
        allowed_rish = {
            "id", "getenforce", "dumpsys thermalservice", "dumpsys gpu",
            "service list", "getprop ro.hardware", "getprop ro.hardware.egl",
            "getprop ro.hardware.vulkan",
        }
        if not argv or not isinstance(argv[0], str):
            return {"status": "command_not_allowlisted"}
        rish_call = (
            self._rish_path is not None and argv[0] == self._rish_path
            and len(argv) == 3 and argv[1] == "-c" and argv[2] in allowed_rish
        )
        getprop_call = (
            argv[0] == "getprop" and len(argv) == 2 and argv[1] in allowed_getprop
        )
        if not (
            rish_call or getprop_call
            or argv == ["vulkaninfo", "--summary"]
            or argv == ["termux-battery-status"]
        ):
            return {"status": "command_not_allowlisted"}
        if not shutil.which(argv[0]):
            return {"status": "command_not_found", "command": argv[0]}
        try:
            result = subprocess.run(argv, capture_output=True, text=True,
                timeout=timeout or self.timeout, check=False,
                env={**os.environ, "LC_ALL": "C"})
            return {"status": "completed", "returncode": result.returncode,
                "ok": result.returncode == 0,
                "stdout": result.stdout[:self.MAX_TEXT].strip(),
                "stderr": result.stderr[:4000].strip()}
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "timeout_seconds": timeout or self.timeout}
        except OSError as exc:
            return {"status": "os_error", "error": type(exc).__name__}

    def _getprop(self, key: str) -> str | None:
        result = self._run(["getprop", key], 3)
        return result.get("stdout") if result.get("status") == "completed" and result.get("ok") else None

    @staticmethod
    def _find_rish() -> str | None:
        found = shutil.which("rish")
        if found:
            return found
        candidate = Path.home() / "bin" / "rish"
        return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None

    def android(self) -> dict[str, Any]:
        keys = ("ro.product.manufacturer", "ro.product.model", "ro.product.device",
                "ro.build.version.release", "ro.build.version.sdk", "ro.hardware",
                "ro.hardware.egl", "ro.hardware.vulkan", "ro.opengles.version",
                "ro.build.fingerprint")
        return {key: self._getprop(key) for key in keys} | {
            "kernel": platform.release(), "architecture": platform.machine(),
            "python": platform.python_version(), "termux_prefix": os.environ.get("PREFIX")}

    def cpu(self) -> dict[str, Any]:
        info = self._read("/proc/cpuinfo", 96_000)
        policies = []
        for directory in sorted(glob.glob("/sys/devices/system/cpu/cpufreq/policy*")):
            entry = {"policy": Path(directory).name}
            for field in ("related_cpus", "scaling_governor", "scaling_cur_freq",
                          "scaling_min_freq", "scaling_max_freq", "cpuinfo_max_freq"):
                entry[field] = self._read(str(Path(directory) / field), 2048)
            policies.append(entry)
        return {"logical_cpus": os.cpu_count(), "cpuinfo": info, "frequency_policies": policies}

    def memory(self) -> dict[str, Any]:
        meminfo = self._read("/proc/meminfo", 32_000)
        pressure = {name: self._read(f"/proc/pressure/{name}", 4096)
                    for name in ("cpu", "memory", "io")}
        zram = {"mm_stat": self._read("/sys/block/zram0/mm_stat", 4096),
                "disksize": self._read("/sys/block/zram0/disksize", 2048),
                "comp_algorithm": self._read("/sys/block/zram0/comp_algorithm", 2048)}
        return {"meminfo": meminfo, "pressure_stall_information": pressure, "zram": zram}

    def thermal(self) -> dict[str, Any]:
        zones = []
        for directory in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
            zone = Path(directory)
            kind = self._read(str(zone / "type"), 1024)
            temp = self._read(str(zone / "temp"), 1024)
            item = {"zone": zone.name, "type": kind, "temperature_raw": temp}
            value = temp.get("value") if temp.get("status") == "readable" else None
            if value is not None:
                try:
                    number = int(value)
                    # Heuristic only. No sensor is declared validated by units alone.
                    item["milli_celsius_candidate"] = round(number / 1000, 3) if 10_000 <= number <= 150_000 else None
                    item["interpretation"] = "candidate_only_cross_check_required" if item["milli_celsius_candidate"] is not None else "units_unknown_or_sentinel"
                except ValueError:
                    item["interpretation"] = "non_numeric"
            zones.append(item)
        return {"zone_count": len(zones), "zones": zones,
                "android_thermalservice": self._run_shizuku("dumpsys thermalservice", 12),
                "note": "Temperaturas de thermal_zone são candidatas. Compare com ThermalService e sensores nomeados; não trate toda zona como temperatura de CPU/GPU."}

    def _run_shizuku(self, command: str, timeout: int = 10) -> dict[str, Any]:
        # Caller can select only one of these fixed read-only commands.
        allowed = {"id", "getenforce", "dumpsys thermalservice", "dumpsys gpu",
                   "service list", "getprop ro.hardware", "getprop ro.hardware.egl",
                   "getprop ro.hardware.vulkan"}
        if command not in allowed:
            return {"status": "not_allowlisted"}
        if not self._rish_path:
            return {"status": "rish_not_found"}
        result = self._run([self._rish_path, "-c", command], timeout)
        result["transport"] = "Shizuku rish"
        result["identity_note"] = "A identidade normalmente é shell/UID 2000; Shizuku não equivale a root."
        return result

    def shizuku(self) -> dict[str, Any]:
        return {"rish_path": self._rish_path,
            "identity": self._run_shizuku("id", 5),
            "selinux": self._run_shizuku("getenforce", 5),
            "service_list": self._run_shizuku("service list", 8),
            "thermalservice": self._run_shizuku("dumpsys thermalservice", 12),
            "gpu_service": self._run_shizuku("dumpsys gpu", 12),
            "note": "Acesso é medido por comando e resultado; a existência do rish não prova acesso a todos os serviços."}

    def gpu(self) -> dict[str, Any]:
        paths = {
            "gpu_busy_percentage": "/sys/class/kgsl/kgsl-3d0/gpu_busy_percentage",
            "gpu_clock_hz": "/sys/class/kgsl/kgsl-3d0/gpuclk",
            "max_gpu_clock_hz": "/sys/class/kgsl/kgsl-3d0/max_gpuclk",
            "devfreq_current_hz": "/sys/class/kgsl/kgsl-3d0/devfreq/cur_freq",
            "devfreq_governor": "/sys/class/kgsl/kgsl-3d0/devfreq/governor",
            "devfreq_available_frequencies": "/sys/class/kgsl/kgsl-3d0/devfreq/available_frequencies",
            "kgsl_gpu_model": "/sys/class/kgsl/kgsl-3d0/gpu_model",
            "kgsl_gpu_device": "/dev/kgsl-3d0"}
        sysfs = {}
        for name, path in paths.items():
            if name == "kgsl_gpu_device":
                sysfs[name] = {"exists": os.path.exists(path), "readable": os.access(path, os.R_OK)}
            else:
                sysfs[name] = self._read(path, 4096)
        icd_candidates = []
        prefix = os.environ.get("PREFIX", "")
        for rel in ("share/vulkan/icd.d/freedreno_icd.aarch64.json",
                    "share/vulkan/icd.d/lvp_icd.aarch64.json"):
            path = Path(prefix) / rel if prefix else Path("/") / rel
            icd_candidates.append({"path": str(path), "exists": path.is_file(),
                                  "metadata": self._read(str(path), 8192) if path.is_file() else {"status": "not_found"}})
        vulkan = self._run(["vulkaninfo", "--summary"], 15)
        return {"android_driver_properties": {key: self._getprop(key) for key in
                    ("ro.hardware", "ro.hardware.egl", "ro.hardware.vulkan", "ro.opengles.version")},
                "kgsl_sysfs": sysfs, "vulkan_icd_candidates": icd_candidates,
                "vulkaninfo_summary": vulkan,
                "android_gpu_service": self._run_shizuku("dumpsys gpu", 12),
                "interpretation": ["ICD instalado/disponível não prova que um jogo o utiliza.",
                    "O ICD Turnip/Freedreno do Termux não substitui o driver Qualcomm do Android.",
                    "Não foi executado benchmark nem teste de carga."]}

    def battery(self) -> dict[str, Any]:
        api = self._run(["termux-battery-status"], 6)
        data = None
        if api.get("status") == "completed" and api.get("ok"):
            try:
                data = json.loads(api.get("stdout", ""))
            except json.JSONDecodeError:
                api["parse_status"] = "invalid_json"
        return {"termux_api": api, "parsed": data,
                "sysfs": {field: self._read(f"/sys/class/power_supply/battery/{field}", 2048)
                    for field in ("capacity", "status", "health", "temp", "voltage_now", "current_now", "cycle_count")}}

    def access(self) -> dict[str, Any]:
        paths = ("/proc/meminfo", "/proc/pressure/cpu", "/proc/pressure/memory",
            "/sys/class/kgsl/kgsl-3d0/gpu_busy_percentage", "/sys/class/kgsl/kgsl-3d0/gpuclk",
            "/sys/class/thermal/thermal_zone0/temp", "/sys/class/power_supply/battery/capacity",
            "/dev/kgsl-3d0", "/dev/dri", "/sys/block/zram0/mm_stat")
        checks = {}
        for path in paths:
            checks[path] = {"exists": os.path.exists(path), "readable_hint": os.access(path, os.R_OK)}
        return {"termux_uid": os.getuid(), "termux_gid": os.getgid(),
                "selinux_termux_context": self._read("/proc/self/attr/current", 2048),
                "paths": checks,
                "warning": "os.access é apenas uma indicação; a leitura real de cada arquivo é a evidência definitiva."}

    def storage(self) -> dict[str, Any]:
        result = {}
        for name, path in {"project": self.root, "termux_home": Path.home(),
                           "shared_storage": Path("/storage/emulated/0")}.items():
            try:
                usage = shutil.disk_usage(path)
                result[name] = {"path": str(path), "total_bytes": usage.total,
                    "free_bytes": usage.free, "free_gib": round(usage.free / 1024**3, 2)}
            except OSError as exc:
                result[name] = {"path": str(path), "status": type(exc).__name__}
        return result

    def run(self, save: bool = True) -> dict[str, Any]:
        report = {"schema": "mahoraga.hardware.deep.v1", "module_version": self.VERSION,
            "captured_at": self._utc(), "mode": "read_only", "device": self.android(),
            "cpu": self.cpu(), "memory": self.memory(), "thermal": self.thermal(),
            "gpu": self.gpu(), "shizuku": self.shizuku(), "battery": self.battery(),
            "access": self.access(), "storage": self.storage(),
            "local_persistence": {
                "requested": bool(save),
                "scope": "project_storage",
                "targets": ["json_report", "markdown_report", "knowledge_store"]
                    if save else [],
            },
            "safety": {
                "writes_performed": False,
                "device_writes_performed": False,
                "packages_installed": False,
                "root_attempted": False,
                "stress_test_performed": False,
            }}
        if save:
            folder = self.root / "reports" / "hardware"
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            json_path = folder / f"deep_diagnostics_{stamp}.json"
            md_path = folder / f"deep_diagnostics_{stamp}.md"
            report["saved_reports"] = {"json": str(json_path), "markdown": str(md_path)}
            try:
                store = self.store
                if store is None:
                    from .memory import get_store
                    store = get_store()
                limitations = ["Leituras sysfs podem estar bloqueadas.",
                    "Temperaturas candidatas requerem correlação com ThermalService.",
                    "Vulkaninfo não prova uso pelo jogo."]
                atomic_save = getattr(store, "record_observation_and_event", None)
                if callable(atomic_save):
                    atomic_save("deep_hardware_diagnostics", "android_device",
                        report, "HardwareDeepDiagnostics.run",
                        "hardware.deep_diagnostics",
                        {"captured_at": report["captured_at"],
                         "json_report": str(json_path)},
                        confidence=0.95, limitations=limitations)
                else:
                    store.record_observation("deep_hardware_diagnostics",
                        "android_device", report,
                        source="HardwareDeepDiagnostics.run",
                        confidence=0.95, limitations=limitations)
                    store.record_event("hardware.deep_diagnostics", {
                        "captured_at": report["captured_at"],
                        "json_report": str(json_path)})
            except Exception as exc:
                report["persistence_warning"] = type(exc).__name__
            temp_path = json_path.with_suffix(".json.tmp")
            temp_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp_path, json_path)
            lines = ["# Mahoraga — Diagnóstico profundo de hardware", "",
                f"- Capturado: {report['captured_at']}", "- Modo: somente leitura",
                f"- Modelo: {report['device'].get('ro.product.model')}",
                f"- Android: {report['device'].get('ro.build.version.release')} (API {report['device'].get('ro.build.version.sdk')})",
                f"- Zonas térmicas: {report['thermal']['zone_count']}",
                f"- rish: {report['shizuku'].get('rish_path') or 'não encontrado'}",
                f"- Vulkaninfo: {report['gpu']['vulkaninfo_summary'].get('status')}",
                f"- Persistência: {'aviso — ' + report['persistence_warning'] if 'persistence_warning' in report else 'registrada'}",
                "", "## Segurança", "Diagnóstico somente leitura; nenhum ajuste ou teste de estresse executado."]
            md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report
def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Diagnóstico profundo, somente leitura, do hardware Android.")
    parser.add_argument("--project", default=None)
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()
    result = HardwareDeepDiagnostics(args.project).run(save=not args.no_save)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
