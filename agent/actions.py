import os
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
LOG_FILE = BASE_DIR / "logs" / "activity.log"

def inspect_project():
    print("\n--- ARQUIVOS DO MAHORAGA ---")

    for folder in ["agent", "memory", "experiments", "logs"]:
        path = os.path.join(BASE_DIR, folder)

        print(f"\n{folder}/")

        if os.path.isdir(path):
            for item in os.listdir(path):
                print("  -", item)

def register_activity(description):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    timestamp = datetime.now().isoformat()

    with open(LOG_FILE, "a", encoding="utf-8") as file:
        file.write(f"[{timestamp}] {description}\n")

    print("Atividade registrada.")

def run_action(action):
    actions = {
        "inspect_project": inspect_project,
        "register_activity": register_activity
    }

    if action not in actions:
        print("Acao nao autorizada.")
        return

    if action == "register_activity":
        description = input("Descreva a atividade: ").strip()

        if not description:
            print("Descricao vazia.")
            return

        actions[action](description)
    else:
        actions[action]()
