"""Read-only Android/Termux hardware and operating-system intelligence.

Every measurement carries source/availability information. Missing or blocked
interfaces are reported as limitations, never replaced with invented values.
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


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class HardwareIntelligence:
    VERSION = "1.0"
    MAX_READ_BYTES = 256_000
    COMMAND_TIMEOUT = 5

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or Path(__file__).resolve().parent.parent)
        self._shizuku_cache = None

    def _read(self, path: str, limit: int = MAX_READ_BYTES) -> tuple[str | None, str]:
        try:
            with open(path, "rb") as handle:
                raw = handle.read(limit + 1)
            if len(raw) > limit:
                raw = raw[:limit]
            return raw.decode("utf-8", errors="replace").strip(), "readable"
        except PermissionError:
            return None, "permission_denied"
        except FileNotFoundError:
            return None, "not_found"
        except OSError as exc:
            return None, f"os_error:{type(exc).__name__}"

    def _command(self, argv: list[str], timeout: int | None = None) -> dict:
        if not argv or not shutil.which(argv[0]):
            return {"available": False, "status": "command_not_found"}
        try:
            result = subprocess.run(argv, capture_output=True, text=True,
                timeout=timeout or self.COMMAND_TIMEOUT, check=False,
                env={**os.environ, "LC_ALL": "C"})
            return {"available": result.returncode == 0, "returncode": result.returncode,
                    "stdout": result.stdout[:self.MAX_READ_BYTES].strip(),
                    "stderr": result.stderr[:4000].strip()}
        except subprocess.TimeoutExpired:
            return {"available": False, "status": "timeout"}
        except OSError as exc:
            return {"available": False, "status": f"os_error:{type(exc).__name__}"}

    def _getprop(self, key: str) -> str | None:
        result = self._command(["getprop", key], 2)
        return result.get("stdout") if result.get("available") else None

    def android(self) -> dict:
        return {
            "manufacturer": self._getprop("ro.product.manufacturer"),
            "model": self._getprop("ro.product.model"),
            "device": self._getprop("ro.product.device"),
            "product": self._getprop("ro.product.name"),
            "android_release": self._getprop("ro.build.version.release"),
            "api_level": self._getprop("ro.build.version.sdk"),
            "build_fingerprint": self._getprop("ro.build.fingerprint"),
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "termux_prefix": os.environ.get("PREFIX"),
            "runtime": platform.python_version(),
        }

    def cpu(self) -> dict:
        raw, status = self._read("/proc/cpuinfo")
        processors = []
        model_fields = {}
        if raw:
            blocks = re.split(r"\n\s*\n", raw)
            for block in blocks:
                item = {}
                for line in block.splitlines():
                    if ":" in line:
                        key, value = line.split(":", 1)
                        item[key.strip()] = value.strip()
                if item:
                    processors.append(item)
            if processors:
                for key in ("Hardware", "model name", "Processor", "CPU implementer", "CPU part"):
                    values = list(dict.fromkeys(p[key] for p in processors if p.get(key)))
                    if values:
                        model_fields[key] = values[:8]
        policies = []
        for policy in sorted(glob.glob("/sys/devices/system/cpu/cpufreq/policy*")):
            entry = {"policy": Path(policy).name}
            for field in ("related_cpus", "scaling_governor", "scaling_cur_freq",
                          "scaling_min_freq", "scaling_max_freq", "cpuinfo_max_freq"):
                value, state = self._read(str(Path(policy) / field), 2048)
                entry[field] = value if value is not None else state
            policies.append(entry)
        return {"logical_cpu_count": os.cpu_count(), "cpuinfo_status": status,
                "model_fields": model_fields, "processor_records": len(processors),
                "frequency_policies": policies,
                "limitations": [] if policies else ["cpufreq_sysfs_unavailable_or_restricted"]}

    def memory(self) -> dict:
        raw, status = self._read("/proc/meminfo")
        values = {}
        if raw:
            for line in raw.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                match = re.search(r"(\d+)", value)
                if match:
                    values[key] = int(match.group(1))  # Linux meminfo values are kB.
        wanted = ("MemTotal", "MemAvailable", "MemFree", "Buffers", "Cached", "SwapTotal", "SwapFree")
        result = {key: {"kb": values[key], "mb": round(values[key] / 1024, 2)}
                  for key in wanted if key in values}
        zram_raw, zram_status = self._read("/sys/block/zram0/mm_stat", 4096)
        zram = {"status": zram_status}
        if zram_raw:
            parts = zram_raw.split()
            if len(parts) >= 3 and all(part.isdigit() for part in parts[:3]):
                zram = {"status": "readable", "original_bytes": int(parts[0]),
                        "compressed_bytes": int(parts[1]), "memory_used_bytes": int(parts[2])}
        return {"status": status, "values": result, "zram": zram}

    def storage(self) -> dict:
        paths = {"termux_home": str(Path.home()), "project": str(self.root),
                 "shared_storage": "/storage/emulated/0"}
        result = {}
        for name, path in paths.items():
            try:
                usage = shutil.disk_usage(path)
                result[name] = {"path": path, "total_bytes": usage.total,
                    "used_bytes": usage.used, "free_bytes": usage.free,
                    "free_gb": round(usage.free / 1024**3, 2)}
            except OSError as exc:
                result[name] = {"path": path, "available": False,
                                "reason": type(exc).__name__}
        return result

    def battery(self) -> dict:
        api_result = self._command(["termux-battery-status"], 6)
        api_data = None
        api_status = "unavailable"
        if api_result.get("available"):
            try:
                api_data = json.loads(api_result["stdout"])
                api_status = "available"
            except json.JSONDecodeError:
                api_status = "invalid_json"
        sysfs = {}
        battery_root = Path("/sys/class/power_supply/battery")
        for field in ("capacity", "status", "health", "technology", "temp", "voltage_now",
                      "current_now", "charge_counter", "charge_full", "charge_full_design", "cycle_count"):
            value, status = self._read(str(battery_root / field), 2048)
            sysfs[field] = value if value is not None else status
        sysfs_available = any(v not in ("not_found", "permission_denied", "os_error:PermissionError")
                              and not (isinstance(v, str) and v.startswith("os_error:")) for v in sysfs.values())
        return {"available": api_data is not None or sysfs_available,
                "termux_api": {"status": api_status, "data": api_data},
                "sysfs_read_only": sysfs,
                "limitations": ["Battery sysfs units depend on the driver; raw values are preserved without assuming units."]}

    def _shizuku_diagnostics(self) -> dict:
        if self._shizuku_cache is not None:
            return self._shizuku_cache
        rish = shutil.which("rish")
        if not rish:
            candidate = Path.home() / "bin" / "rish"
            if candidate.is_file() and os.access(candidate, os.X_OK):
                rish = str(candidate)
        if not rish:
            self._shizuku_cache = {"available": False, "status": "rish_not_found"}
            return self._shizuku_cache
        # Fixed read-only commands only; no user-controlled shell input.
        script = ("dumpsys thermalservice; printf '\n__MAHORAGA_GPU__\n'; dumpsys gpu; "
                  "printf '\n__MAHORAGA_ID__\n'; id; "
                  "printf '\n__MAHORAGA_SELINUX__\n'; getenforce")
        try:
            process = subprocess.run([rish, "-c", script], capture_output=True,
                text=True, timeout=12, check=False, env={**os.environ, "LC_ALL": "C"})
            if process.returncode != 0 and not process.stdout.strip():
                self._shizuku_cache = {"available": False, "status": "shizuku_command_failed",
                    "stderr": process.stderr[:2000].strip(), "returncode": process.returncode}
                return self._shizuku_cache
            output = process.stdout
            markers = ("__MAHORAGA_GPU__", "__MAHORAGA_ID__", "__MAHORAGA_SELINUX__")
            pieces = output.split(markers[0], 1)
            thermal_text = pieces[0].strip()
            gpu_text = ""
            identity = ""
            selinux = ""
            if len(pieces) > 1:
                pieces = pieces[1].split(markers[1], 1)
                gpu_text = pieces[0].strip()
                if len(pieces) > 1:
                    pieces = pieces[1].split(markers[2], 1)
                    identity = pieces[0].strip()
                    if len(pieces) > 1:
                        selinux = pieces[1].strip()
            self._shizuku_cache = {"available": True, "source": "Shizuku/rish shell UID",
                "thermalservice": thermal_text[:self.MAX_READ_BYTES], "gpu": gpu_text[:self.MAX_READ_BYTES],
                "identity": identity[:2000], "selinux_mode": selinux[:1000],
                "stderr": process.stderr[:2000].strip(), "returncode": process.returncode,
                "note": "Shizuku ADB shell normally uses UID 2000; it is not root."}
        except subprocess.TimeoutExpired:
            self._shizuku_cache = {"available": False, "status": "timeout"}
        except OSError as exc:
            self._shizuku_cache = {"available": False, "status": f"os_error:{type(exc).__name__}"}
        return self._shizuku_cache

    @staticmethod
    def parse_runtime_context(
        power_output: str,
        activities_output: str,
        thermal_output: str,
    ) -> dict:
        """Parse only explicit Android dumpsys fields; unknown fields stay unknown."""
        if not all(
            isinstance(value, str)
            for value in (power_output, activities_output, thermal_output)
        ):
            raise ValueError("dumpsys inputs precisam ser textos.")

        interactive_match = re.search(
            r"^\s*mInteractive=(true|false)\s*$",
            power_output,
            re.IGNORECASE | re.MULTILINE,
        )
        display_match = re.search(
            r"^\s*Display Power:\s*state=(ON|OFF|DOZE|DOZE_SUSPEND)\b.*$",
            power_output,
            re.IGNORECASE | re.MULTILINE,
        )
        interactive_state = (
            interactive_match.group(1).casefold() == "true"
            if interactive_match else None
        )
        display_state = display_match.group(1).upper() if display_match else None
        if interactive_state is False or display_state in {"OFF", "DOZE", "DOZE_SUSPEND"}:
            screen_interactive = False
        elif interactive_state is True and display_state == "ON":
            screen_interactive = True
        else:
            # PowerManager.isInteractive is not a guarantee that the physical
            # display is lit; require an explicit Display Power state as well.
            screen_interactive = None

        activity_lines = activities_output.splitlines()
        # Prefer topResumedActivity over legacy mResumedActivity when both
        # appear, so a stale compatibility field cannot override the top app.
        resumed_lines = [
            line for line in activity_lines
            if re.search(r"\btopResumedActivity\b", line)
        ]
        if not resumed_lines:
            resumed_lines = [
                line for line in activity_lines
                if re.search(r"\bmResumedActivity\b", line)
            ]
        foreground_package = None
        for line in resumed_lines:
            package_match = re.search(
                r"\b(?:u\d+\s+)?([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)/",
                line,
            )
            if package_match:
                foreground_package = package_match.group(1)
                break
        app_foreground = (
            foreground_package == "com.termux"
            if foreground_package is not None else None
        )

        thermal_match = re.search(
            r"^\s*(?:Thermal Status|Current thermal status)\s*[:=]\s*(\d+)\s*$",
            thermal_output,
            re.IGNORECASE | re.MULTILINE,
        )
        thermal_codes = {
            0: "normal",
            1: "light",
            2: "moderate",
            3: "severe",
            4: "critical",
            5: "emergency",
            6: "shutdown",
        }
        thermal_code = int(thermal_match.group(1)) if thermal_match else None
        thermal_status = thermal_codes.get(thermal_code, "unknown")

        return {
            "app_foreground": app_foreground,
            "foreground_package": foreground_package,
            "screen_interactive": screen_interactive,
            "power_manager_interactive": interactive_state,
            "display_state": display_state,
            "thermal_status": thermal_status,
            "thermal_status_code": thermal_code if thermal_code in thermal_codes else None,
            "source": "Shizuku/rish dumpsys power+activity+thermalservice",
            "read_only": True,
            "limitations": [
                "O primeiro plano é reconhecido somente quando topResumedActivity/mResumedActivity expõe o pacote.",
                "Para permitir trabalho, exige mInteractive=true e Display Power state=ON simultaneamente.",
                "A leitura térmica usa somente os códigos oficiais de ThermalStatus; formatos desconhecidos permanecem unknown.",
                "Este processo reconhece Termux (com.termux) como ambiente executável atual; outros apps não são tratados como ambiente Mahoraga.",
            ],
        }

    def runtime_context(self) -> dict:
        """Read screen/app/thermal context through fixed read-only Shizuku commands.

        Missing rish, denied dumpsys output, or unfamiliar Android output never
        becomes an affirmative permission to compute.
        """
        rish = shutil.which("rish")
        if not rish:
            candidate = Path.home() / "bin" / "rish"
            if candidate.is_file() and os.access(candidate, os.X_OK):
                rish = str(candidate)
        unavailable = {
            "app_foreground": None,
            "screen_interactive": None,
            "thermal_status": "unknown",
            "available": False,
            "read_only": True,
        }
        if not rish:
            return {
                **unavailable,
                "status": "rish_not_found",
                "limitations": ["Shizuku/rish não está disponível; autonomia deve pausar."],
            }

        # Keep Android diagnostics bounded before they cross into Python.
        # Toybox head is available on Android; if the output format/tool is
        # unfamiliar, the parser remains fail-closed rather than guessing.
        script = (
            "dumpsys power | head -c 65536; "
            "printf '\\n__MAHORAGA_ACTIVITIES__\\n'; "
            "dumpsys activity activities | head -c 65536; "
            "printf '\\n__MAHORAGA_THERMAL__\\n'; "
            "dumpsys thermalservice | head -c 16384"
        )
        try:
            process = subprocess.run(
                [rish, "-c", script],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                env={**os.environ, "LC_ALL": "C"},
            )
        except subprocess.TimeoutExpired:
            return {**unavailable, "status": "timeout"}
        except OSError as exc:
            return {
                **unavailable,
                "status": f"os_error:{type(exc).__name__}",
            }

        if len(process.stdout) > 160 * 1024:
            return {
                **unavailable,
                "status": "runtime_output_too_large",
                "returncode": process.returncode,
            }

        markers = ("__MAHORAGA_ACTIVITIES__", "__MAHORAGA_THERMAL__")
        parts = process.stdout.split(markers[0], 1)
        if len(parts) != 2:
            return {
                **unavailable,
                "status": "power_output_unrecognized",
                "returncode": process.returncode,
                "stderr": process.stderr[:2000].strip(),
            }
        power_output, remainder = parts
        parts = remainder.split(markers[1], 1)
        if len(parts) != 2:
            return {
                **unavailable,
                "status": "activity_output_unrecognized",
                "returncode": process.returncode,
                "stderr": process.stderr[:2000].strip(),
            }
        activities_output, thermal_output = parts
        parsed = self.parse_runtime_context(
            power_output,
            activities_output,
            thermal_output,
        )
        parsed.update({
            "available": process.returncode == 0,
            "status": "available" if process.returncode == 0 else "partial_or_denied",
            "returncode": process.returncode,
            "stderr": process.stderr[:2000].strip(),
            "captured_at": _utc(),
        })
        if process.returncode != 0:
            parsed["app_foreground"] = None
            parsed["screen_interactive"] = None
            parsed["thermal_status"] = "unknown"
        return parsed

    def _shizuku_dumpsys(self, service: str) -> dict:
        if service not in {"thermalservice", "gpu"}:
            return {"available": False, "status": "service_not_allowlisted"}
        data = self._shizuku_diagnostics()
        if not data.get("available"):
            return data
        return {"available": bool(data.get(service)), "source": data.get("source"),
                "stdout": data.get(service, ""), "stderr": data.get("stderr", "")}

    def shizuku_security_context(self) -> dict:
        data = self._shizuku_diagnostics()
        if not data.get("available"):
            return data
        return {"available": True, "source": data.get("source"), "read_only": True,
                "identity": data.get("identity"), "selinux_mode": data.get("selinux_mode"),
                "note": data.get("note")}

    def thermal(self) -> dict:
        zones = []
        blocked = 0
        for zone in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
            name, name_status = self._read(str(Path(zone) / "type"), 1024)
            raw, temp_status = self._read(str(Path(zone) / "temp"), 1024)
            if raw is None:
                blocked += 1
                zones.append({"zone": Path(zone).name, "name": name,
                              "status": temp_status, "classification": "unknown"})
                continue
            try:
                numeric = int(raw)
            except ValueError:
                zones.append({"zone": Path(zone).name, "name": name,
                              "status": "invalid_value", "classification": "unknown"})
                continue
            # Do not assume every thermal_zone is a Celsius sensor.
            plausible = 10_000 <= numeric <= 150_000
            zones.append({"zone": Path(zone).name, "name": name,
                "raw_value": numeric,
                "temperature_c_candidate": round(numeric / 1000, 2) if plausible else None,
                "classification": "candidate_not_verified" if plausible else "unknown_units"})
        android_service = self._shizuku_dumpsys("thermalservice")
        return {"zone_count": len(zones), "unreadable_count": blocked, "zones": zones,
                "android_thermal_service": android_service,
                "limitations": ["thermal_zone_values_are_candidates_until_cross_checked_with_Android_ThermalService",
                                "Shizuku diagnostics are optional and may be unavailable when its service is stopped"]}

    def gpu(self) -> dict:
        props = {key: self._getprop(key) for key in
                 ("ro.hardware.egl", "ro.hardware.vulkan", "ro.opengles.version", "ro.hardware" )}
        icd_paths = ["$PREFIX/share/vulkan/icd.d/freedreno_icd.aarch64.json",
                     "$PREFIX/share/vulkan/icd.d/lvp_icd.aarch64.json"]
        resolved = []
        prefix = os.environ.get("PREFIX", "")
        for candidate in icd_paths:
            path = candidate.replace("$PREFIX", prefix)
            resolved.append({"path": path, "exists": Path(path).is_file()})
        android_gpu_service = self._shizuku_dumpsys("gpu")
        gpu_paths = {
            "busy_percentage": "/sys/class/kgsl/kgsl-3d0/gpu_busy_percentage",
            "gpu_clock_hz": "/sys/class/kgsl/kgsl-3d0/gpuclk",
            "max_gpu_clock_hz": "/sys/class/kgsl/kgsl-3d0/max_gpuclk",
            "devfreq_current_hz": "/sys/class/kgsl/kgsl-3d0/devfreq/cur_freq",
            "devfreq_governor": "/sys/class/kgsl/kgsl-3d0/devfreq/governor",
            "devfreq_available_hz": "/sys/class/kgsl/kgsl-3d0/devfreq/available_frequencies",
        }
        gpu_sysfs = {}
        for key, path in gpu_paths.items():
            value, status = self._read(path, 4096)
            gpu_sysfs[key] = value if value is not None else {"status": status, "path": path}
        return {"android_driver_properties": props, "termux_vulkan_icds": resolved,
                "android_gpu_service": android_gpu_service, "sysfs_read_only": gpu_sysfs,
                "limitations": ["Termux Vulkan ICD selection does not change Android system/game drivers",
                                "A listed ICD does not prove that a workload is using it"]}

    def access_map(self) -> dict:
        paths = ("/proc/meminfo", "/proc/cpuinfo", "/proc/pressure/cpu",
                 "/proc/pressure/memory", "/proc/pressure/io",
                 "/sys/class/kgsl/kgsl-3d0", "/sys/class/kgsl/kgsl-3d0/gpu_busy_percentage",
                 "/sys/class/kgsl/kgsl-3d0/gpuclk", "/sys/class/kgsl/kgsl-3d0/max_gpuclk",
                 "/sys/class/kgsl/kgsl-3d0/devfreq/cur_freq",
                 "/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq",
                 "/sys/class/power_supply/battery/capacity", "/sys/class/thermal/thermal_zone0/temp")
        result = {}
        for path in paths:
            result[path] = {"exists": os.path.exists(path), "readable": os.access(path, os.R_OK)}
        rish_path = shutil.which("rish") or (str(Path.home() / "bin" / "rish")
            if (Path.home() / "bin" / "rish").is_file() else None)
        return {"uid": os.getuid(), "gid": os.getgid(), "rish_path": rish_path,
                "paths": result,
                "note": "Termux runs in its app sandbox; rish, when authorized, provides the Shizuku shell identity (normally UID 2000), not root. Readability checks are preliminary; SELinux and per-file policy may still deny access."}

    def available_tools(self) -> dict:
        names = ("python3", "git", "clang", "gcc", "make", "adb", "rish",
                 "termux-battery-status", "termux-sensor", "termux-camera-info",
                 "termux-camera-photo", "termux-microphone-record", "termux-audio-info",
                 "termux-tts-speak", "vulkaninfo", "trace_processor_shell",
                 "sqlite3", "curl", "wget", "pkg", "pip")
        return {name: shutil.which(name) for name in names}

    def snapshot(self) -> dict:
        return {"module": "MAHORAGA HARDWARE INTELLIGENCE", "version": self.VERSION,
            "captured_at": _utc(), "mode": "read_only", "android": self.android(),
            "cpu": self.cpu(), "memory": self.memory(), "storage": self.storage(),
            "battery": self.battery(), "thermal": self.thermal(), "gpu": self.gpu(),
            "access_map": self.access_map(), "shizuku_security_context": self.shizuku_security_context(),
            "available_tools": self.available_tools()}

    def save_snapshot(self, store=None) -> dict:
        report = self.snapshot()
        if store is not None:
            store.record_observation("hardware_snapshot", "android_device", report,
                source="HardwareIntelligence.snapshot", confidence=0.9,
                limitations=["Some kernel interfaces may be blocked or unavailable.",
                             "Thermal-zone units are not assumed without validation."])
            store.record_event("hardware.snapshot", {"model": report["android"].get("model"),
                                                       "captured_at": report["captured_at"]})
        return report
