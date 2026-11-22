import json
from datetime import datetime
from pathlib import Path

MEMORY_FILE = Path(__file__).resolve().parents[1] / "memory" / "data.json"

def save_memory(key, value):
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)

    data = load_memory()
    data[key] = {
        "value": value,
        "updated_at": datetime.now().isoformat()
    }

    with open(MEMORY_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)

def load_memory():
    if not os.path.exists(MEMORY_FILE):
        return {}

    with open(MEMORY_FILE, "r", encoding="utf-8") as file:
        return json.load(file)
