"""Mahoraga command-line control panel."""
from __future__ import annotations
import json
from . import __version__
from .memory import get_store, load_memory, save_memory
from .hardware_intelligence import HardwareIntelligence
from .introspection import IntrospectionEngine
from .tool_intelligence import ToolIntelligence
from .deep_diagnostics import HardwareDeepDiagnostics
from .cognitive_engine import CognitiveEngine
from .integration_core import IntegratedCore


class Mahoraga:
    def __init__(self):
        self.integration = IntegratedCore()
        self.store = self.integration.store
        self.hardware = self.integration.hardware
        self.introspection = self.integration.introspection
        self.tools = self.integration.tools
        self.cognitive = self.integration.cognitive

    def status(self):
        print("=" * 42)
        print(f"MAHORAGA {__version__} | NÚCLEO EXPERIMENTAL")
        print("Banco:", self.store.db_path)
        print("Integridade SQLite:", self.store.integrity_check())
        print("Registros:", json.dumps(self.store.counts(), ensure_ascii=False))
        print("=" * 42)

    def cognitive_menu(self):
        while True:
            print("\n--- MÓDULO COGNITIVO ---")
            print("1 - Estado cognitivo")
            print("2 - Registrar observação")
            print("3 - Registrar aprendizagem")
            print("4 - Propor hipótese")
            print("5 - Registrar experimento")
            print("6 - Revisar contexto e memória")
            print("7 - Preparar documento para estudo")
            print("0 - Voltar")

            choice = input("Escolha: ").strip()

            if choice == "0":
                return

            try:
                if choice == "1":
                    result = self.cognitive.status()

                elif choice == "2":
                    category = input("Categoria: ").strip()
                    subject = input("Assunto: ").strip()
                    data = input("Observação: ").strip()
                    origin = input("Origem: ").strip()
                    raw = input("Confiança de 0 a 1 (vazio = não informar): ").strip()
                    confidence = float(raw) if raw else None

                    if confidence is not None and not 0 <= confidence <= 1:
                        raise ValueError("Confiança deve estar entre 0 e 1.")

                    limitation = input("Limitação conhecida (vazio = nenhuma): ").strip()

                    result = self.cognitive.record_observation(
                        category=category,
                        subject=subject,
                        data=data,
                        source=origin,
                        confidence=confidence,
                        limitations=[limitation] if limitation else [],
                    )

                elif choice == "3":
                    key = input("Chave: ").strip()
                    learning = input("Aprendizagem: ").strip()
                    origin = input("Origem (vazio = internal): ").strip() or "internal"

                    result = self.cognitive.record_learning(
                        key=key,
                        learning=learning,
                        source=origin,
                    )

                elif choice == "4":
                    hypothesis = input("Hipótese: ").strip()
                    question = input("Pergunta de investigação: ").strip()

                    result = self.cognitive.propose_hypothesis(
                        hypothesis=hypothesis,
                        question=question,
                    )

                elif choice == "5":
                    hypothesis = input("Hipótese: ").strip()
                    method = input("Método: ").strip()
                    outcome = input("Resultado observado: ").strip()
                    conclusion = input("Conclusão: ").strip()
                    cycle = input("ID do ciclo (vazio = nenhum): ").strip() or None

                    result = self.cognitive.complete_experiment(
                        hypothesis=hypothesis,
                        method=method,
                        result=outcome,
                        conclusion=conclusion,
                        cycle_id=cycle,
                    )

                elif choice == "6":
                    topic = input("Assunto (vazio = todos): ").strip() or None
                    result = self.cognitive.review_context(topic=topic)

                elif choice == "7":
                    document_id = int(input("ID do documento: ").strip())
                    result = self.cognitive.prepare_document_learning(document_id)

                else:
                    print("Opção inválida.")
                    continue

                print(json.dumps(result, indent=2, ensure_ascii=False))

            except Exception as exc:
                print(f"Operação não concluída: {type(exc).__name__}: {exc}")

    def integration_menu(self):
        report = self.integration.build_report(persist=False)
        print(json.dumps(report, indent=2, ensure_ascii=False))

    def menu(self):
        options = {
            "1": "Guardar memória", "2": "Consultar memórias", "3": "Diagnóstico de hardware",
            "4": "Modelo de autocompreensão", "5": "Descobrir ferramentas", "6": "Histórico de eventos",
            "7": "Experimentos", "8": "Registro de instalações", "9": "Sair", "10": "Diagnóstico profundo de hardware"}
        options["11"] = "Módulo cognitivo"
        options["12"] = "Painel integrado do núcleo"
        while True:
            print("\n--- MAHORAGA ---")
            for key, label in options.items():
                print(f"{key} - {label}")
            choice = input("Escolha: ").strip()
            if choice == "1":
                key = input("Chave: ").strip()
                value = input("Informação: ").strip()
                if key and value:
                    save_memory(key, value)
                    print("Memória salva.")
            elif choice == "2":
                memories = load_memory()
                for key, item in memories.items():
                    print(f"\n{key}: {item['value']}")
                if not memories:
                    print("Nenhuma memória.")
            elif choice == "3":
                report = self.hardware.save_snapshot(self.store)
                print(json.dumps(report, indent=2, ensure_ascii=False))
            elif choice == "4":
                model = self.introspection.build_self_model()
                print(json.dumps(model, indent=2, ensure_ascii=False))
            elif choice == "5":
                report = self.tools.discover()
                print(f"Comandos: {len(report['commands'])}; pacotes Termux: {len(report.get('termux_packages', []))}; bibliotecas Python: {len(report['python_packages'])}")
            elif choice == "6":
                print(json.dumps(self.store.list_events(50), indent=2, ensure_ascii=False))
            elif choice == "7":
                print(json.dumps(self.store.list_experiments(100), indent=2, ensure_ascii=False))
            elif choice == "8":
                print(json.dumps(self.store.list_installations(), indent=2, ensure_ascii=False))
            elif choice == "10":
                report = HardwareDeepDiagnostics(self.integration.root, store=self.store).run(save=True)
                saved = report.get("saved_reports", {})
                print()
                print("DIAGNÓSTICO PROFUNDO CONCLUÍDO — SOMENTE LEITURA")
                print("CPU policies:", len(report.get("cpu", {}).get("frequency_policies", [])))
                print("Zonas térmicas:", report.get("thermal", {}).get("zone_count"))
                print("Shizuku/rish:", report.get("shizuku", {}).get("rish_path") or "não encontrado")
                print("Identidade Shizuku:", report.get("shizuku", {}).get("identity", {}).get("status"))
                print("SELinux:", report.get("shizuku", {}).get("selinux", {}).get("stdout") or report.get("shizuku", {}).get("selinux", {}).get("status"))
                print("GPU busy:", report.get("gpu", {}).get("kgsl_sysfs", {}).get("gpu_busy_percentage", {}).get("status"))
                print("GPU clock:", report.get("gpu", {}).get("kgsl_sysfs", {}).get("gpu_clock_hz", {}).get("status"))
                print("Vulkaninfo:", report.get("gpu", {}).get("vulkaninfo_summary", {}).get("status"))
                print("Bateria API:", report.get("battery", {}).get("termux_api", {}).get("status"))
                print("Relatório JSON:", saved.get("json", "não salvo"))
                print("Relatório Markdown:", saved.get("markdown", "não salvo"))
                print("Detalhes completos preservados no JSON e no SQLite.")
            elif choice == "11":
                self.cognitive_menu()
            elif choice == "12":
                try:
                    self.integration_menu()
                except Exception as exc:
                    print(f"Relatório não concluído: {type(exc).__name__}: {exc}")
            elif choice == "9":
                print("Encerrando Mahoraga.")
                break
            else:
                print("Opção inválida.")


if __name__ == "__main__":
    app = Mahoraga()
    app.status()
    app.menu()
