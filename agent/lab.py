import json
from datetime import datetime
from pathlib import Path

LAB_FILE = Path(__file__).resolve().parents[1] / "experiments" / "experiments.json"

def load_experiments():
    if not os.path.exists(LAB_FILE):
        return []

    with open(LAB_FILE, "r", encoding="utf-8") as file:
        return json.load(file)

def save_experiment(hypothesis, method, result, conclusion):
    os.makedirs(os.path.dirname(LAB_FILE), exist_ok=True)

    experiments = load_experiments()

    experiment = {
        "date": datetime.now().isoformat(),
        "hypothesis": hypothesis,
        "method": method,
        "result": result,
        "conclusion": conclusion
    }

    experiments.append(experiment)

    with open(LAB_FILE, "w", encoding="utf-8") as file:
        json.dump(experiments, file, indent=4, ensure_ascii=False)

    print("Experimento registrado com sucesso!")

def show_experiments():
    experiments = load_experiments()

    if not experiments:
        print("Nenhum experimento registrado.")
        return

    for number, experiment in enumerate(experiments, 1):
        print(f"\n--- EXPERIMENTO {number} ---")
        print("Hipotese:", experiment["hypothesis"])
        print("Metodo:", experiment["method"])
        print("Resultado:", experiment["result"])
        print("Conclusao:", experiment["conclusion"])

