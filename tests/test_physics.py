import unittest
from agent.physics import PhysicsLab


class TestPhysicsLab(unittest.TestCase):

    def setUp(self):
        self.lab = PhysicsLab()

    def test_free_fall_position_after_one_second(self):
        results = self.lab.free_fall(10, duration=1)
        final = results[-1]
        self.assertAlmostEqual(final["position"], 5.095, places=3)
        self.assertAlmostEqual(final["velocity"], -9.81, places=2)
        self.assertFalse(final["impact"])

    def test_exact_impact_between_steps(self):
        results = self.lab.free_fall(1, duration=1, step=0.3)
        impact = results[-1]
        self.assertTrue(impact["impact"])
        self.assertAlmostEqual(impact["time"], 0.451524, places=5)
        self.assertEqual(impact["position"], 0)
        self.assertAlmostEqual(impact["velocity"], -4.429447, places=5)

    def test_exact_apex_between_steps(self):
        results = self.lab.free_fall(
            10,
            initial_velocity=20,
            duration=3,
            step=0.7
        )
        apex_events = [r for r in results if r.get("apex")]
        self.assertEqual(len(apex_events), 1)
        apex = apex_events[0]
        self.assertAlmostEqual(apex["time"], 20 / 9.81, places=6)
        self.assertAlmostEqual(
            apex["position"], 10 + 20**2 / (2 * 9.81), places=6
        )
        self.assertEqual(apex["velocity"], 0)

    def test_mechanical_energy_is_conserved(self):
        results = self.lab.free_fall(
            10, initial_velocity=20, duration=2, step=0.25
        )
        initial_energy = 0.5 * 20**2 + self.lab.gravity * 10

        for result in results:
            if result["impact"]:
                continue
            energy = (
                0.5 * result["velocity"]**2
                + self.lab.gravity * result["position"]
            )
            self.assertAlmostEqual(
                energy, initial_energy, delta=0.0001
            )

    def test_invalid_gravity_is_rejected(self):
        for gravity in (0, -9.81, float("inf"), float("nan")):
            with self.subTest(gravity=gravity):
                with self.assertRaises(ValueError):
                    PhysicsLab(gravity=gravity)

    def test_extreme_step_count_is_rejected_before_simulation(self):
        with self.assertRaisesRegex(ValueError, "limite maximo de passos"):
            self.lab.free_fall(10, duration=1_000_000, step=0.000001)

    def test_extreme_velocity_is_rejected_as_numeric_domain_error(self):
        with self.assertRaises(ValueError):
            self.lab.free_fall(10, initial_velocity=1e308, duration=1, step=0.1)

    def test_arbitrarily_large_integer_inputs_are_rejected_cleanly(self):
        with self.assertRaises(ValueError):
            self.lab.free_fall(10**1000)
        with self.assertRaises(ValueError):
            PhysicsLab(gravity=10**1000)

    def test_boolean_values_are_not_accepted_as_physical_parameters(self):
        with self.assertRaises(ValueError):
            self.lab.free_fall(True)
        with self.assertRaises(ValueError):
            PhysicsLab(gravity=True)

    def test_invalid_simulation_parameters_are_rejected(self):
        invalid_cases = (
            {"initial_height": -1},
            {"initial_height": 10, "step": 0},
            {"initial_height": 10, "duration": -1},
            {"initial_height": float("inf")},
            {"initial_height": 10, "step": float("nan")},
        )
        for parameters in invalid_cases:
            with self.subTest(parameters=parameters):
                with self.assertRaises(ValueError):
                    self.lab.free_fall(**parameters)


if __name__ == "__main__":
    unittest.main()
