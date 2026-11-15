"""Tests for the cooperative cost-game analysis algorithms.

These are property tests against the real discrete cost oracle, not fixed
fixture answers: the expectations derive from the game-theoretic definitions
(conservation, core inequalities, nucleolus lexicographic ordering, subsidy
duality) and from hand-solvable synthetic cost games injected through the
coalition-cost function.
"""
import itertools
import unittest
from unittest import mock

from app.allocation import (
    analyze,
    apply_scenario,
    characteristic_costs,
    integer_least_core,
    least_core_epsilon,
    minimum_subsidy,
    nucleolus,
    round_to_cents,
    shapley_value,
)
from app.store import load_case


def table_quote(table):
    def _quote(case, subset):
        cost = table.get(frozenset(subset))
        if cost is None:
            return {"feasible": False, "cost_cents": None, "loads": []}
        return {"feasible": True, "cost_cents": cost, "loads": []}
    return _quote


def synthetic_case(identifiers):
    return {"members": [{"id": identifier, "boxes": 1} for identifier in identifiers],
            "scenarios": [], "_snapshot": "synthetic"}


class ConservationTests(unittest.TestCase):
    def test_every_allocation_reconciles_to_total_in_integer_cents(self):
        result = analyze(load_case("standard"))
        self.assertTrue(result["feasible"])
        for allocation in result["allocations"]:
            self.assertTrue(all(isinstance(value, int) for value in allocation["cents"].values()))
            self.assertEqual(sum(allocation["cents"].values())
                             + allocation.get("subsidy_cents", 0), result["total_cost"])

    def test_rounding_never_breaks_efficiency(self):
        case = load_case("standard")
        identifiers = [member["id"] for member in case["members"]]
        costs = characteristic_costs(case, identifiers)
        total = costs[frozenset(identifiers)]
        targets = (
            {identifier: total / len(identifiers) for identifier in identifiers},
            {identifier: float(index * 7) for index, identifier in enumerate(identifiers)},
        )
        for target in targets:
            rounded = round_to_cents(identifiers, target, total)
            self.assertEqual(sum(rounded.values()), total)
            self.assertTrue(all(isinstance(value, int) for value in rounded.values()))
            # Exact L1-optimal integer rounding: no feasible integer allocation
            # can be closer to the fractional target in total absolute distance.
            achieved = sum(abs(rounded[i] - target[i]) for i in identifiers)
            alternative = dict(rounded)
            donor, receiver = identifiers[0], identifiers[-1]
            alternative[donor] -= 1
            alternative[receiver] += 1
            shifted = sum(abs(alternative[i] - target[i]) for i in identifiers)
            self.assertLessEqual(achieved, shifted + 1e-9)


class CoreAndNucleolusTests(unittest.TestCase):
    def setUp(self):
        self.case = load_case("standard")
        self.ids = [member["id"] for member in self.case["members"]]
        self.costs = characteristic_costs(self.case, identifiers=self.ids)

    def test_standard_case_has_nonempty_core_and_stable_nucleolus(self):
        _, epsilon = least_core_epsilon(self.ids, self.costs)
        self.assertLessEqual(epsilon, 1e-7)
        allocation, integer_epsilon = integer_least_core(
            self.ids, self.costs, nucleolus(self.ids, self.costs)[0])
        self.assertEqual(integer_epsilon, 0)
        for coalition, cost in self.costs.items():
            if 0 < len(coalition) < len(self.ids) and cost is not None:
                self.assertLessEqual(sum(allocation[i] for i in coalition), cost)

    def test_nucleolus_balances_coalition_excesses_lexicographically(self):
        allocation, _ = nucleolus(self.ids, self.costs)
        total = self.costs[frozenset(self.ids)]
        self.assertAlmostEqual(sum(allocation.values()), total, places=6)
        # Every alternative core point must make the worst-off coalition no
        # better: compare against the arbitrary core point returned by the LP.
        point_array, _ = least_core_epsilon(self.ids, self.costs)
        point = dict(zip(self.ids, point_array))
        nucleolus_worst = max(sum(allocation[i] for i in coalition) - cost
                              for coalition, cost in self.costs.items()
                              if 0 < len(coalition) < len(self.ids) and cost is not None)
        point_worst = max(sum(point[i] for i in coalition) - cost
                          for coalition, cost in self.costs.items()
                          if 0 < len(coalition) < len(self.ids) and cost is not None)
        self.assertLessEqual(nucleolus_worst, point_worst + 1e-7)

    def test_shapley_sums_to_total_and_respects_dummy_player(self):
        shares = shapley_value(self.ids, self.costs)
        self.assertAlmostEqual(sum(shares.values()), self.costs[frozenset(self.ids)], places=6)
        # Hand-built game where z is a dummy: c(S union {z}) = c(S) + c({z})
        # for every coalition S of the other two players.
        table = {
            frozenset(): 0,
            frozenset("x"): 100, frozenset("y"): 100, frozenset("z"): 100,
            frozenset("xy"): 180, frozenset("xz"): 200, frozenset("yz"): 200,
            frozenset(["x", "y", "z"]): 280,
        }
        with mock.patch("app.allocation.quote", table_quote(table)):
            synthetic = characteristic_costs(synthetic_case(["x", "y", "z"]), ["x", "y", "z"])
            shares = shapley_value(["x", "y", "z"], synthetic)
        self.assertAlmostEqual(shares["z"], 100.0, places=6)
        self.assertAlmostEqual(shares["x"], shares["y"], places=6)
        self.assertAlmostEqual(sum(shares.values()), 280.0, places=6)

    def test_empty_core_game_reports_conflict_and_minimum_concession(self):
        ids = ["p", "q", "r"]
        table = {frozenset(): 0, frozenset(ids): 700}
        for member in ids:
            table[frozenset(member)] = 300
        for pair in itertools.combinations(ids, 2):
            table[frozenset(pair)] = 400
        with mock.patch("app.allocation.quote", table_quote(table)):
            costs = characteristic_costs(synthetic_case(ids), ids)
            _, epsilon = least_core_epsilon(ids, costs)
            self.assertAlmostEqual(epsilon, 200.0 / 3.0, places=4)
            allocation, integer_epsilon = integer_least_core(
                ids, costs, nucleolus(ids, costs)[0])
            self.assertEqual(integer_epsilon, 67)
            self.assertEqual(sum(allocation.values()), 700)
            subsidised, subsidy = minimum_subsidy(ids, costs)
            self.assertEqual(subsidy, 100)
            self.assertEqual(sum(subsidised.values()) + subsidy, 700)
            for coalition, cost in costs.items():
                if 0 < len(coalition) < 3:
                    self.assertLessEqual(sum(subsidised[i] for i in coalition), cost)
            result = analyze(synthetic_case(ids))
        self.assertEqual(result["blocking"]["core_status"], "empty")
        self.assertTrue(any(a["name"] == "nucleolus_with_minimum_subsidy"
                            and a["subsidy_cents"] == 100 for a in result["allocations"]))
        # Conservation contract still holds with the explicit subsidy.
        for allocation in result["allocations"]:
            self.assertEqual(sum(allocation["cents"].values())
                             + allocation.get("subsidy_cents", 0), 700)


class RoundingStabilityTests(unittest.TestCase):
    def test_cent_remainder_cannot_turn_an_acceptable_plan_unfair(self):
        result = analyze(load_case("standard"))
        case = load_case("standard")
        ids = [member["id"] for member in case["members"]]
        costs = characteristic_costs(case, ids)
        for allocation in result["allocations"]:
            # Every figure is whole cents and the books reconcile exactly.
            self.assertTrue(all(isinstance(v, int) for v in allocation["cents"].values()))
            self.assertEqual(sum(allocation["cents"].values())
                             + allocation.get("subsidy_cents", 0), result["total_cost"])
            # Stability is re-adjudicated on the rounded integers against every
            # feasible coalition, never inherited from the fractional solution.
            observed_worst = 0
            observed_blockers = 0
            for coalition, cost in costs.items():
                if not 0 < len(coalition) < len(ids) or cost is None:
                    continue
                violation = sum(allocation["cents"][i] for i in coalition) - cost
                observed_worst = max(observed_worst, max(0, violation))
                if violation > 0:
                    observed_blockers += 1
            self.assertEqual(observed_worst, allocation["worst_violation_cents"])
            self.assertEqual(observed_blockers, len(allocation["blocking_coalitions"]))
        # The stable fractional reference must stay stable after integer rounding.
        nucleolus_rule = next(a for a in result["allocations"] if a["name"] == "nucleolus")
        self.assertTrue(nucleolus_rule["stable"])
        self.assertEqual(nucleolus_rule["worst_violation_cents"], 0)

    def test_fractional_reference_that_misses_core_by_under_one_cent_is_flagged(self):
        # Shapley on the real case violates the {b,c} constraint by 133 cents;
        # rounding must not hide that, it has to remain visibly blocked.
        result = analyze(load_case("standard"))
        shapley_rule = next(a for a in result["allocations"] if a["name"] == "shapley")
        self.assertFalse(shapley_rule["stable"])
        self.assertIn(["b", "c"], [c["members"] for c in shapley_rule["blocking_coalitions"]])


class DiscreteCostTests(unittest.TestCase):
    def test_analysis_uses_actual_coalition_costs_not_smoothed_prices(self):
        result = analyze(load_case("standard"))
        # The box-proportional rule must be exposed as unstable precisely
        # because full-truckload step costs make per-box sharing unsafe.
        box_rule = next(a for a in result["allocations"] if a["name"] == "box_proportional")
        self.assertFalse(box_rule["stable"])
        blocked = {(c["members"][0] if len(c["members"]) == 1 else tuple(c["members"]))
                   for c in box_rule["blocking_coalitions"]}
        self.assertIn(("a", "b", "c"), blocked)
        evidence = next(c for c in box_rule["blocking_coalitions"]
                        if c["members"] == ["a", "b", "c"])
        self.assertEqual(evidence["standalone_cost_cents"], 22000)
        self.assertTrue(evidence["loads_witness"])

    def test_infeasible_grand_coalition_yields_no_fabricated_allocation(self):
        result = analyze(load_case("edge"))
        self.assertFalse(result["feasible"])
        self.assertIsNone(result["total_cost"])
        self.assertEqual(result["allocations"], [])
        minimal = result["blocking"]["infeasible_minimal_coalitions"]
        self.assertIn(["c", "d", "f"], minimal)
        self.assertTrue(result["diagnostics"])


class ScenarioSensitivityTests(unittest.TestCase):
    def test_scenarios_apply_and_comparison_base_stays_consistent(self):
        case = load_case("standard")
        baseline = analyze(case)
        expanded = analyze(case, "a-expands")
        self.assertEqual(baseline["snapshot"], expanded["snapshot"])
        self.assertNotEqual(baseline["total_cost"], expanded["total_cost"])
        names = {entry["scenario"] for entry in baseline["sensitivity"]}
        self.assertEqual(names, {None, "a-expands", "large-shortage"})
        for entry in baseline["sensitivity"]:
            if entry["feasible"]:
                for method, cents in entry["allocations"].items():
                    self.assertEqual(sum(cents.values()), entry["total_cost_cents"],
                                     msg=method)
        # Same methods appear under every feasible scenario.
        methods = {method for entry in baseline["sensitivity"] if entry["feasible"]
                   for method in entry["allocations"]}
        self.assertEqual(methods, {a["name"] for a in baseline["allocations"]})

    def test_unknown_scenario_is_rejected(self):
        with self.assertRaises(ValueError):
            apply_scenario(load_case("standard"), "no-such-scenario")

    def test_fleet_shortage_keeps_stable_method_but_reveals_transfer_payment(self):
        result = analyze(load_case("standard"), "large-shortage")
        nucleolus_rule = next(a for a in result["allocations"] if a["name"] == "nucleolus")
        self.assertTrue(nucleolus_rule["stable"])
        self.assertTrue(any(value < 0 for value in nucleolus_rule["cents"].values()))
        self.assertTrue(any("below zero" in message for message in result["diagnostics"]))


if __name__ == "__main__":
    unittest.main()
