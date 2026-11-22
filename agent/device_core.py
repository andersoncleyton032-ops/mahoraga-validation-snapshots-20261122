import os
import sys
import json
import platform
import shutil
import subprocess
from datetime import datetime


class DeviceCore:

    def getprop(self, prop):
        try:
            result = subprocess.run(
                ["getprop", prop],
                capture_output=True,
                text=True,
                timeout=3
            )
            return result.stdout.strip()
        except Exception:
            return None

    def read_file(self, path):
        try:
            with open(path, "r") as file:
                return file.read().strip()
        except Exception:
            return None

    def hardware(self):
        return {
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
            "manufacturer": self.getprop("ro.product.manufacturer"),
            "model": self.getprop("ro.product.model"),
            "android_version": self.getprop("ro.build.version.release"),
            "android_sdk": self.getprop("ro.build.version.sdk"),
            "device": self.getprop("ro.product.device")
        }

    def memory(self):
        data = self.read_file("/proc/meminfo")

        if not data:
            return {"available": False}

        result = {}

        for line in data.splitlines():
            parts = line.split()

            if len(parts) >= 2:
                key = parts[0].replace(":", "")
                try:
                    result[key] = int(parts[1])
                except ValueError:
                    pass

        return {
            "total_mb": round(result.get("MemTotal", 0) / 1024),
            "available_mb": round(result.get("MemAvailable", 0) / 1024),
            "free_mb": round(result.get("MemFree", 0) / 1024)
        }

    def storage(self):
        result = {}

        paths = {
            "termux_home": os.path.expanduser("~"),
            "shared_storage": "/storage/emulated/0"
        }

        for name, path in paths.items():
            try:
                usage = shutil.disk_usage(path)

                result[name] = {
                    "total_gb": round(usage.total / (1024 ** 3), 2),
                    "used_gb": round(usage.used / (1024 ** 3), 2),
                    "free_gb": round(usage.free / (1024 ** 3), 2)
                }
            except Exception:
                result[name] = {"available": False}

        return result


    def battery(self):
        import json
        import subprocess

        try:
            result = subprocess.run(
                ["termux-battery-status"],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                return {"available": False, "error": result.stderr.strip()}

            data = json.loads(result.stdout)
            return {"available": True, **data}

        except Exception as e:
            return {"available": False, "error": str(e)}

    def available_tools(self):
        tools = [
            "python",
            "git",
            "clang",
            "gcc",
            "make",
            "adb",
            "termux-battery-status"
        ]

        return {
            tool: shutil.which(tool)
            for tool in tools
        }

    def diagnose(self):
        return {
            "core": "MAHORAGA DEVICE CORE",
            "version": "0.1",
            "mode": "read_only",
            "timestamp": datetime.now().isoformat(),
            "hardware": self.hardware(),
            "memory": self.memory(),
            "storage": self.storage(),
            "battery": self.battery(),
            "tools": self.available_tools()
        }


if __name__ == "__main__":
    device = DeviceCore()
    report = device.diagnose()

    print(json.dumps(
        report,
        indent=4,
        ensure_ascii=False
    ))
