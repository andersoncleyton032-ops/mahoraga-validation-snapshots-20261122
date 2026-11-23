"""Backward-compatible facade for unified hardware intelligence."""
from __future__ import annotations
from pathlib import Path
from .hardware_intelligence import HardwareIntelligence


class DeviceCore:
    def __init__(self, root: str | Path | None = None):
        self.collector = HardwareIntelligence(root)

    def read_file(self, path):
        value, status = self.collector._read(str(path))
        return value

    def hardware(self):
        data = self.collector.android()
        cpu = self.collector.cpu()
        return {"architecture": data["architecture"], "processor": cpu.get("model_fields", {}),
                "cpu_count": cpu.get("logical_cpu_count"), "manufacturer": data.get("manufacturer"),
                "model": data.get("model"), "android_version": data.get("android_release"),
                "android_sdk": data.get("api_level"), "device": data.get("device")}

    def memory(self):
        values = self.collector.memory().get("values", {})
        return {"total_mb": values.get("MemTotal", {}).get("mb", 0),
                "available_mb": values.get("MemAvailable", {}).get("mb", 0),
                "free_mb": values.get("MemFree", {}).get("mb", 0)}

    def storage(self):
        return self.collector.storage()

    def battery(self):
        return self.collector.battery()

    def available_tools(self):
        return self.collector.available_tools()

    def diagnose(self):
        report = self.collector.snapshot()
        report["core"] = "MAHORAGA DEVICE CORE"
        return report


if __name__ == "__main__":
    import json
    print(json.dumps(DeviceCore().diagnose(), indent=2, ensure_ascii=False))
