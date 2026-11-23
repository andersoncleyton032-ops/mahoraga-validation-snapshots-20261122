"""Compatibility API for the experiment laboratory."""
from .memory import get_store


def save_experiment(hypothesis, method, result, conclusion):
    experiment_id = get_store().record_experiment(hypothesis, method, result, conclusion)
    print("Experimento registrado no banco de conhecimento.")
    return experiment_id


def load_experiments():
    return get_store().list_experiments(limit=1000)


def show_experiments():
    experiments = load_experiments()
    if not experiments:
        print("Nenhum experimento registrado.")
        return
    for number, item in enumerate(experiments, 1):
        print(f"\n--- EXPERIMENTO {number} ---")
        print("Hipótese:", item["hypothesis"])
        print("Método:", item["method"])
        print("Resultado:", item["result"])
        print("Conclusão:", item["conclusion"])
