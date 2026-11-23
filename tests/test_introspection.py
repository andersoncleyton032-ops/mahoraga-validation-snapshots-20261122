import tempfile
import unittest
from pathlib import Path
from agent.store import KnowledgeStore
from agent.introspection import IntrospectionEngine


class TestIntrospection(unittest.TestCase):
    def test_self_model_distinguishes_operational_state_from_consciousness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "agent").mkdir()
            store = KnowledgeStore(root / "memory" / "test.sqlite3")
            engine = IntrospectionEngine(root=root, store=store)
            model = engine.build_self_model()
            self.assertEqual(model["identity"]["name"], "Mahoraga")
            self.assertFalse(model["epistemic_status"]["subjective_consciousness_claim"])
            self.assertIsNotNone(store.latest_self_model())

    def test_self_model_includes_tool_registry_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = KnowledgeStore(root / "db.sqlite3")
            store.upsert_tool(
                "command:demo", "demo", "/bin/demo",
                source="test", competence="identified"
            )
            store.update_tool_competence(
                "command:demo", "studied", ["documentação estudada"]
            )

            engine = IntrospectionEngine(root=root, store=store)
            model = engine.build_self_model(persist=False)

            registry = model["capabilities"]["tool_registry"]
            self.assertEqual(registry["registered_count"], 1)
            self.assertEqual(registry["by_competence"]["studied"], 1)
            self.assertEqual(registry["items"][0]["competence"], "studied")
            self.assertEqual(
                registry["items"][0]["evidence"],
                ["documentação estudada"]
            )
            self.assertFalse(
                registry["discovery_performed_during_model_build"]
            )

    def test_audit_flags_insufficient_evidence_without_changing_competence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = KnowledgeStore(root / "db.sqlite3")
            store.upsert_tool(
                "command:demo", "demo", "/bin/demo",
                competence="operational",
                evidence=["execução registrada"],
            )
            engine = IntrospectionEngine(root=root, store=store)

            report = engine.audit_capabilities(persist=False)

            self.assertEqual(report["tool_count"], 1)
            self.assertEqual(report["evidence_insufficient_count"], 1)
            self.assertEqual(
                report["tools"][0]["status"],
                "insufficient_evidence",
            )
            self.assertEqual(
                store.list_tools()[0]["competence"],
                "operational",
            )
            self.assertIsNone(report["persistence"])

    def test_audit_persists_observation_and_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = KnowledgeStore(root / "db.sqlite3")
            store.upsert_tool(
                "command:demo", "demo", "/bin/demo",
                competence="specialized",
                evidence=["teste 1", "teste 2", "teste 3"],
            )
            store.record_experiment(
                "Hipótese de teste",
                "Método controlado",
                "Resultado observado",
                "Conclusão experimental",
            )
            engine = IntrospectionEngine(root=root, store=store)

            report = engine.audit_capabilities()

            self.assertEqual(report["evidence_sufficient_count"], 1)
            self.assertEqual(report["experiment_count"], 1)
            self.assertIsNotNone(report["persistence"])
            events = store.list_events(
                event_type="introspection.capability_audit"
            )
            self.assertEqual(len(events), 1)

    def test_audit_handles_empty_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = KnowledgeStore(root / "db.sqlite3")
            engine = IntrospectionEngine(root=root, store=store)

            report = engine.audit_capabilities(persist=False)

            self.assertEqual(report["tool_count"], 0)
            self.assertEqual(report["evidence_insufficient_count"], 0)
            self.assertEqual(report["recommendations"], [])

    def test_empty_question_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = KnowledgeStore(root / "db.sqlite3")
            engine = IntrospectionEngine(root=root, store=store)
            with self.assertRaises(ValueError):
                engine.record_question("   ")


    def test_audit_rejects_invalid_experiment_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = KnowledgeStore(root / "db.sqlite3")
            engine = IntrospectionEngine(root=root, store=store)
            for invalid in (0, -1, 1001, True, False, 1.5, "10", None):
                with self.subTest(limit=invalid):
                    with self.assertRaisesRegex(
                        ValueError, "limit_experiments deve ser um inteiro"
                    ):
                        engine.audit_capabilities(
                            limit_experiments=invalid, persist=False
                        )

    def test_audit_accepts_boundary_experiment_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = KnowledgeStore(root / "db.sqlite3")
            engine = IntrospectionEngine(root=root, store=store)
            for valid in (1, 1000):
                with self.subTest(limit=valid):
                    report = engine.audit_capabilities(
                        limit_experiments=valid, persist=False
                    )
                    self.assertEqual(report["status"], "completed")
                    self.assertEqual(report["experiment_count"], 0)




    def test_record_question_persists_open_question_without_conclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = KnowledgeStore(root / "db.sqlite3")
            engine = IntrospectionEngine(root=root, store=store)

            observation_id = engine.record_question(
                "Como avaliar a retomada após reinicialização?",
                {"area": "continuity", "phase": "research"},
            )

            observations = store.list_observations(
                limit=10, category="self_inquiry"
            )
            self.assertEqual(len(observations), 1)
            self.assertEqual(observations[0]["id"], observation_id)
            self.assertEqual(observations[0]["data"]["status"], "open_question")
            self.assertEqual(
                observations[0]["data"]["context"]["area"], "continuity"
            )

    def test_record_question_rejects_invalid_or_oversized_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = KnowledgeStore(root / "db.sqlite3")
            engine = IntrospectionEngine(root=root, store=store)

            for question in (None, 42, "", " " , "q" * 1001):
                with self.assertRaises(ValueError):
                    engine.record_question(question)
            with self.assertRaises(ValueError):
                engine.record_question("Pergunta válida", context=[])
            with self.assertRaises(ValueError):
                engine.record_question(
                    "Pergunta válida", context={"payload": "x" * 5000}
                )
            self.assertEqual(store.list_observations(category="self_inquiry"), [])


if __name__ == "__main__":
    unittest.main()
