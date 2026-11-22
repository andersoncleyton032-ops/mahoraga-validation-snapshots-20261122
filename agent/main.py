import sys
import platform
from datetime import datetime
from .memory import save_memory, load_memory
from .actions import run_action

class Mahoraga:
    def __init__(self):
        self.name = "Mahoraga"
        self.version = "0.3"
        self.start_time = datetime.now()

    def status(self):
        print("=" * 35)
        print("       MAHORAGA - SISTEMA")
        print("=" * 35)
        print("Versao:", self.version)
        print("Python:", sys.version.split()[0])
        print("Sistema:", platform.system())
        print("Arquitetura:", platform.machine())
        print("Memoria: Ativa")
        print("Acoes: Ativas")
        print("=" * 35)

    def menu(self):
        while True:
            print("\n--- MAHORAGA ---")
            print("1 - Guardar informacao")
            print("2 - Consultar memorias")
            print("3 - Inspecionar arquivos")
            print("4 - Registrar atividade")
            print("5 - Sair")

            option = input("\nEscolha: ").strip()

            if option == "1":
                key = input("Nome da memoria: ").strip()
                value = input("Informacao: ").strip()

                if key and value:
                    save_memory(key, value)
                    print("Memoria salva!")
                else:
                    print("Preencha os campos.")

            elif option == "2":
                memories = load_memory()

                if not memories:
                    print("Nenhuma memoria encontrada.")
                else:
                    for key, item in memories.items():
                        print(f"\n{key}: {item['value']}")

            elif option == "3":
                run_action("inspect_project")

            elif option == "4":
                run_action("register_activity")

            elif option == "5":
                print("Encerrando Mahoraga.")
                break

            else:
                print("Opcao invalida.")

if __name__ == "__main__":
    agent = Mahoraga()
    agent.status()
    agent.menu()
