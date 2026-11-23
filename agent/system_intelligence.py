"""Compatibility facade; collection is centralized in HardwareIntelligence."""
from __future__ import annotations
from .hardware_intelligence import HardwareIntelligence


class SystemIntelligence(HardwareIntelligence):
    def get_android_info(self):
        return self.android()

    def get_memory_info(self):
        values = self.memory().get("values", {})
        return {"total": f"{values['MemTotal']['kb']} kB" if "MemTotal" in values else "Indisponível",
                "available": f"{values['MemAvailable']['kb']} kB" if "MemAvailable" in values else "Indisponível",
                "free": f"{values['MemFree']['kb']} kB" if "MemFree" in values else "Indisponível"}

    def get_storage_info(self):
        data = self.storage().get("termux_home", {})
        if not data.get("total_bytes"):
            return {"status": "Informação indisponível"}
        return {"total_bytes": data["total_bytes"], "used_bytes": data["used_bytes"],
                "free_bytes": data["free_bytes"]}

    def get_cpu_info(self):
        raw, status = self._read("/proc/cpuinfo", 4000)
        return {"processor_info": raw} if raw is not None else {"status": status}

    def get_battery_info(self):
        return self.battery()

    def get_thermal_info(self):
        return self.thermal()

    def collect_report(self):
        return self.snapshot()
