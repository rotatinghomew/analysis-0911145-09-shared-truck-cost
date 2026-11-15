"""Cooperative cost-game analysis built on the discrete transport cost oracle.

The transport layer (:mod:`app.coalitions`) answers one question: what is the
minimum cost of moving any given subset of cooperatives, respecting the
discrete fleet, full-truckload green toll waivers, lane separation and
incompatibility constraints?  This module turns those coalition costs into a
transferable-utility cost game and analyses which cost-sharing agreements can
actually survive members exercising their exit option.

Every monetary value produced for the consumer-facing payload is an integer
amount of cents.  Fractional solution concepts (Shapley value, nucleolus) are
kept as references and rounded by an exact mixed-integer programme so that the
books always reconcile to the total cost; the integer result is then checked
against every feasible coalition instead of assuming rounding is harmless.
"""

import copy
import itertools
import math

import numpy as np
from scipy.optimize import linprog

from app.coalitions import quote

SOLVER = "highs"
# Coalition constraints are integer-cent arithmetic; anything below this many
# fractional cents is treated as floating-point noise rather than a violation.
NUMERIC_TOLERANCE = 1e-7
CENT_TOLERANCE = 0.5  # integer allocations: below half a cent cannot be real


def characteristic_costs(case, identifiers):
    """Return ``{frozenset(member_ids): cost_cents | None}`` for every subset."""
    costs = {}
    for size in range(len(identifiers) + 1):
        for subset in itertools.combinations(identifiers, size):
            result = quote(case, list(subset))
            costs[frozenset(subset)] = result["cost_cents"] if result["feasible"] else None
    return costs


def apply_scenario(case, scenario_name):
    """Return a deep-copied case with the named demand/fleet scenario applied."""
    if scenario_name is None:
        return case
    names = {entry["name"]: entry for entry in case.get("scenarios", [])}
    if scenario_name not in names:
        raise ValueError("unknown scenario: " + str(scenario_name))
    scenario = names[scenario_name]
    work = copy.deepcopy(case)
    member_index = {member["id"]: member for member in work["members"]}
    for identifier, boxes in scenario.get("box_changes", {}).items():
        if identifier not in member_index:
            raise ValueError("unknown scenario member: " + str(identifier))
        member_index[identifier]["boxes"] = boxes
    fleet_index = {vehicle["id"]: vehicle for vehicle in work["fleet"]}
    for identifier, available in scenario.get("fleet_changes", {}).items():
        if identifier not in fleet_index:
            raise ValueError("unknown scenario vehicle: " + str(identifier))
        fleet_index[identifier]["available"] = available
    return work


def _constraint_matrix(identifiers, coalitions):
    """Build A_ub rows with one column per member."""
    position = {identifier: index for index, identifier in enumerate(identifiers)}
    rows = []
    rhs = []
    for coalition, cost in coalitions:
        row = np.zeros(len(identifiers))
        for identifier in coalition:
            row[position[identifier]] = 1.0
        rows.append(row)
        rhs.append(float(cost))
    return np.array(rows), np.array(rhs)


def least_core_epsilon(identifiers, costs):
    """Fractional least core: minimise epsilon with x(S) - epsilon <= c(S).

    A non-positive optimum means the (fractional) core is nonempty.
    """
    n = len(identifiers)
    coalitions = [(coalition, cost) for coalition, cost in costs.items()
                  if 0 < len(coalition) < n and cost is not None]
    base, rhs = _constraint_matrix(identifiers, coalitions)
    upper = np.column_stack([base, -np.ones(len(coalitions))])
    objective = np.zeros(n + 1)
    objective[n] = 1.0
    equality = np.zeros((1, n + 1))
    equality[0, :n] = 1.0
    result = linprog(objective, A_ub=upper, b_ub=rhs, A_eq=equality,
                     b_eq=np.array([float(costs[frozenset(identifiers)])]),
                     bounds=(None, None), method=SOLVER)
    if result.status != 0:
        raise RuntimeError("least core LP failed: " + result.message)
    return result.x[:n], float(result.x[n])


def nucleolus(identifiers, costs):
    """Sequential-LP nucleolus (fractional cents).

    Stage one minimises the maximum coalition excess ``x(S) - c(S)``.  Every
    coalition attaining that maximum then has its excess frozen by an equality
    and drops out of later stages (its excess can never rise again), while the
    remaining exit options are re-optimised.  The loop ends once no coalition
    is left to distinguish.
    """
    n = len(identifiers)
    total = float(costs[frozenset(identifiers)])
    open_coalitions = [(coalition, cost) for coalition, cost in costs.items()
                       if 0 < len(coalition) < n and cost is not None]
    frozen = []  # (incidence row, frozen excess value)
    allocation = None
    epsilon = None
    while open_coalitions:
        base, rhs = _constraint_matrix(identifiers, open_coalitions)
        upper = np.column_stack([base, -np.ones(len(open_coalitions))])
        equality_rows = [np.concatenate([np.ones(n), [0.0]])]
        equality_rhs = [total]
        for row, excess in frozen:
            equality_rows.append(np.concatenate([row, [0.0]]))
            equality_rhs.append(float(excess))
        objective = np.zeros(n + 1)
        objective[n] = 1.0
        result = linprog(objective, A_ub=upper, b_ub=rhs,
                         A_eq=np.array(equality_rows), b_eq=np.array(equality_rhs),
                         bounds=(None, None), method=SOLVER)
        if result.status != 0:
            raise RuntimeError("nucleolus LP failed: " + result.message)
        allocation = result.x[:n]
        epsilon = float(result.x[n])
        excesses = base @ allocation - rhs
        still_open = []
        for (coalition, cost), excess in zip(open_coalitions, excesses):
            if abs(excess - epsilon) <= max(NUMERIC_TOLERANCE, 1e-6 * max(1.0, abs(epsilon))):
                row = np.zeros(n)
                for index, identifier in enumerate(identifiers):
                    if identifier in coalition:
                        row[index] = 1.0
                frozen.append((row, float(cost + excess)))
            else:
                still_open.append((coalition, cost))
        if len(still_open) == len(open_coalitions):
            raise RuntimeError("nucleolus iteration made no progress")
        open_coalitions = still_open
    return {identifier: float(allocation[index]) for index, identifier in enumerate(identifiers)}, epsilon


def shapley_value(identifiers, costs):
    """Shapley cost share; ``None`` if any required coalition is infeasible."""
    if any(cost is None for cost in costs.values()):
        return None
    n = len(identifiers)
    factorial = math.factorial
    shares = {}
    for identifier in identifiers:
        others = [other for other in identifiers if other != identifier]
        total = 0.0
        for size in range(n):
            weight = factorial(size) * factorial(n - size - 1) / factorial(n)
            for subset in itertools.combinations(others, size):
                base = frozenset(subset)
                total += weight * (costs[base | frozenset((identifier,))] - costs[base])
        shares[identifier] = total
    return shares


def _integer_programme(objective, upper, upper_rhs, equality, equality_rhs,
                       integer_columns, variable_count):
    integrality = np.zeros(variable_count)
    for column in integer_columns:
        integrality[column] = 1
    result = linprog(objective, A_ub=upper, b_ub=upper_rhs, A_eq=equality,
                     b_eq=equality_rhs, bounds=(None, None), integrality=integrality,
                     method=SOLVER)
    if result.status != 0:
        raise RuntimeError("integer allocation programme failed: " + result.message)
    return result.x


def round_to_cents(identifiers, target, total):
    """Nearest integer-cent allocation to ``target`` that still sums to total.

    The L1 distance is minimised exactly (mixed-integer linear programme).
    """
    n = len(identifiers)
    target = np.array([target[identifier] for identifier in identifiers], dtype=float)
    # Variables: x_1..x_n (integer cents), u_1..u_n (nonnegative L1 slack).
    upper = np.zeros((2 * n, 2 * n))
    rhs = np.zeros(2 * n)
    for index in range(n):
        upper[index, index] = 1.0
        upper[index, n + index] = -1.0
        rhs[index] = target[index]
        upper[n + index, index] = -1.0
        upper[n + index, n + index] = -1.0
        rhs[n + index] = -target[index]
    equality = [np.concatenate([np.ones(n), np.zeros(n)])]
    equality_rhs = [float(total)]
    solution = _integer_programme(np.concatenate([np.zeros(n), np.ones(n)]), upper, rhs,
                                  np.array(equality), np.array(equality_rhs),
                                  range(n), 2 * n)
    return {identifier: int(round(solution[index])) for index, identifier in enumerate(identifiers)}


def integer_least_core(identifiers, costs, fractional_target):
    """Best integer-cent least-core point, tie-broken toward ``fractional_target``."""
    n = len(identifiers)
    total = costs[frozenset(identifiers)]
    coalitions = [(coalition, cost) for coalition, cost in costs.items()
                  if 0 < len(coalition) < n and cost is not None]
    base, rhs = _constraint_matrix(identifiers, coalitions)

    # Stage 1: minimise the integer maximum excess epsilon.
    upper = np.column_stack([base, -np.ones(len(coalitions)), np.zeros((len(coalitions), n))])
    objective = np.zeros(2 * n + 1)
    objective[n] = 1.0
    equality = [np.concatenate([np.ones(n), [0.0], np.zeros(n)])]
    first = _integer_programme(objective, upper, rhs, np.array(equality),
                               np.array([float(total)]), range(n + 1), 2 * n + 1)
    epsilon = int(round(first[n]))

    # Stage 2: pin epsilon and minimise L1 distance to the fractional nucleolus.
    target = np.array([fractional_target[identifier] for identifier in identifiers], dtype=float)
    upper_rows = [np.column_stack([base, np.zeros((len(coalitions), n + 1))])]
    upper_rhs = [rhs + epsilon]
    pin = np.zeros(2 * n + 1)
    pin[n] = 1.0
    upper_rows.append(pin.reshape(1, -1))
    upper_rhs.append(np.array([float(epsilon)]))
    for index in range(n):  # x_i - u_i <= t_i and t_i - x_i <= u_i
        row = np.zeros(2 * n + 1)
        row[index] = 1.0
        row[n + 1 + index] = -1.0
        upper_rows.append(row.reshape(1, -1))
        upper_rhs.append(np.array([target[index]]))
        row = np.zeros(2 * n + 1)
        row[index] = -1.0
        row[n + 1 + index] = -1.0
        upper_rows.append(row.reshape(1, -1))
        upper_rhs.append(np.array([-target[index]]))
    objective = np.zeros(2 * n + 1)
    objective[n + 1:] = 1.0
    second = _integer_programme(objective, np.vstack(upper_rows), np.concatenate(upper_rhs),
                                np.array(equality), np.array([float(total)]),
                                range(n + 1), 2 * n + 1)
    allocation = {identifier: int(round(second[index])) for index, identifier in enumerate(identifiers)}
    return allocation, epsilon


def minimum_subsidy(identifiers, costs):
    """Smallest external subsidy (integer cents) that makes a stable core nonempty."""
    n = len(identifiers)
    total = costs[frozenset(identifiers)]
    coalitions = [(coalition, cost) for coalition, cost in costs.items()
                  if 0 < len(coalition) < n and cost is not None]
    base, rhs = _constraint_matrix(identifiers, coalitions)
    # Variables x_1..x_n (integer), s (integer subsidy): x(S) <= c(S), sum x + s = total.
    upper = np.column_stack([base, np.zeros(len(coalitions))])
    equality = np.concatenate([np.ones(n), [1.0]]).reshape(1, -1)
    objective = np.zeros(n + 1)
    objective[n] = 1.0
    solution = _integer_programme(objective, upper, rhs, equality, np.array([float(total)]),
                                  range(n + 1), n + 1)
    allocation = {identifier: int(round(solution[index])) for index, identifier in enumerate(identifiers)}
    return allocation, int(round(solution[n]))


def evaluate_stability(allocation, identifiers, costs, witnesses):
    """Check every feasible exit option against an integer-cent allocation."""
    blockers = []
    worst = 0
    for coalition, cost in costs.items():
        if not 0 < len(coalition) < len(identifiers) or cost is None:
            continue
        paid = sum(allocation[identifier] for identifier in coalition)
        violation = paid - cost
        if violation > CENT_TOLERANCE:
            blockers.append({
                "members": sorted(coalition),
                "allocated_cents": paid,
                "standalone_cost_cents": cost,
                "violation_cents": int(violation),
                "loads_witness": witnesses[frozenset(coalition)],
            })
            worst = max(worst, int(violation))
    blockers.sort(key=lambda entry: (-entry["violation_cents"], entry["members"]))
    return worst, blockers


def _witnesses(case, identifiers):
    """Cheapest feasible transport plan per coalition, used as blocking evidence."""
    witness = {}
    for size in range(1, len(identifiers) + 1):
        for subset in itertools.combinations(identifiers, size):
            witness[frozenset(subset)] = quote(case, list(subset))["loads"]
    return witness


def economies_of_scale(identifiers, costs, members):
    standalone = {identifier: costs[frozenset((identifier,))] for identifier in identifiers}
    total = costs[frozenset(identifiers)]
    standalone_total = sum(standalone.values())
    table = []
    for size in range(2, len(identifiers) + 1):
        for subset in itertools.combinations(identifiers, size):
            coalition = frozenset(subset)
            cost = costs[coalition]
            if cost is None:
                continue
            alone = sum(standalone[identifier] for identifier in subset)
            saving = alone - cost
            if saving > 0:
                table.append({"members": sorted(subset), "standalone_cents": alone,
                              "coalition_cost_cents": cost, "savings_cents": saving})
    table.sort(key=lambda entry: (-entry["savings_cents"], entry["members"]))
    marginal = {}
    for identifier in identifiers:
        rest = frozenset(other for other in identifiers if other != identifier)
        marginal[identifier] = total - costs[rest]
    boxes = {member["id"]: member["boxes"] for member in members}
    return {
        "standalone_total_cents": standalone_total,
        "grand_coalition_cost_cents": total,
        "total_savings_cents": standalone_total - total,
        "savings_ratio": round((standalone_total - total) / standalone_total, 6),
        "member_standalone_cents": standalone,
        "member_boxes": boxes,
        "marginal_contribution_cents": marginal,
        "coalition_savings": table,
    }


def _method_record(name, cents, fractional, stable, worst, blockers, subsidy_cents=None):
    record = {"name": name, "cents": cents, "fractional_cents": {
        identifier: round(value, 4) for identifier, value in fractional.items()},
        "stable": stable, "worst_violation_cents": worst, "blocking_coalitions": blockers}
    if subsidy_cents is not None:
        record["subsidy_cents"] = subsidy_cents
    return record


def feasible_analysis(case, identifiers, costs, scenario_label):
    witnesses = _witnesses(case, identifiers)
    _, least_core_frac = least_core_epsilon(identifiers, costs)
    fractional_nucleolus, terminal_excess = nucleolus(identifiers, costs)
    integer_nucleolus, epsilon_int = integer_least_core(identifiers, costs, fractional_nucleolus)
    shapley = shapley_value(identifiers, costs)
    total = costs[frozenset(identifiers)]
    members = case["members"]
    total_boxes = sum(member["boxes"] for member in members)
    box_target = {member["id"]: total * member["boxes"] / total_boxes for member in members}
    standalone_total = sum(costs[frozenset((identifier,))] for identifier in identifiers)
    equal_saving = (standalone_total - total) / len(identifiers)
    equal_target = {identifier: costs[frozenset((identifier,))] - equal_saving for identifier in identifiers}

    allocations = []
    worst, blockers = evaluate_stability(integer_nucleolus, identifiers, costs, witnesses)
    allocations.append(_method_record("nucleolus", integer_nucleolus, fractional_nucleolus,
                                      worst == 0, worst, blockers))
    if shapley is not None:
        integer_shapley = round_to_cents(identifiers, shapley, total)
        worst, blockers = evaluate_stability(integer_shapley, identifiers, costs, witnesses)
        allocations.append(_method_record("shapley", integer_shapley, shapley,
                                          worst == 0, worst, blockers))
    integer_box = round_to_cents(identifiers, box_target, total)
    worst, blockers = evaluate_stability(integer_box, identifiers, costs, witnesses)
    allocations.append(_method_record("box_proportional", integer_box, box_target,
                                      worst == 0, worst, blockers))
    integer_equal = round_to_cents(identifiers, equal_target, total)
    worst, blockers = evaluate_stability(integer_equal, identifiers, costs, witnesses)
    allocations.append(_method_record("equal_savings", integer_equal, equal_target,
                                      worst == 0, worst, blockers))

    core_empty = least_core_frac > NUMERIC_TOLERANCE
    diagnostics = [
        "scenario " + str(scenario_label) + ": grand coalition costs " + str(total)
        + " cents versus " + str(standalone_total) + " cents if everyone acts alone",
        "fractional least-core epsilon is " + str(round(least_core_frac, 4))
        + " cents; integer-cent least-core epsilon is " + str(epsilon_int)
        + " cents (a non-positive epsilon means every exit option is respected)",
        "the nucleolus terminates with least-favoured coalition excess "
        + str(round(terminal_excess, 4)) + " fractional cents",
    ]
    if core_empty:
        subsidised, subsidy = minimum_subsidy(identifiers, costs)
        worst, blockers = evaluate_stability(subsidised, identifiers, costs, witnesses)
        record = _method_record("nucleolus_with_minimum_subsidy", subsidised,
                                {identifier: float(value) for identifier, value in subsidised.items()},
                                worst == 0, worst, blockers, subsidy_cents=subsidy)
        record["subsidy_source"] = "external_subsidy_required: no funding source is configured in the case"
        allocations.append(record)
        diagnostics.append("the core is empty; no internally funded allocation can retain every coalition")
        diagnostics.append("minimum external subsidy restoring stability is " + str(subsidy)
                           + " cents; its source must be decided explicitly, it is never invented")
        tight = [sorted(coalition) for coalition, cost in costs.items()
                 if 0 < len(coalition) < len(identifiers) and cost is not None
                 and abs((sum(integer_nucleolus[i] for i in coalition) - cost) - epsilon_int) <= CENT_TOLERANCE]
        diagnostics.append("minimum-concession conflicts bind on coalitions " + str(tight))
    else:
        diagnostics.append("the core is nonempty; the nucleolus allocation retains every feasible coalition")
    for record in allocations:
        if not record["stable"] and record["name"] != "nucleolus_with_minimum_subsidy":
            top = record["blocking_coalitions"][0]
            diagnostics.append(record["name"] + " is unstable: coalition " + str(top["members"])
                               + " would pay " + str(top["violation_cents"])
                               + " cents more than its standalone option")
        negative = {identifier: value for identifier, value in record["cents"].items() if value < 0}
        if negative:
            diagnostics.append(record["name"] + " charges " + str(negative)
                               + " below zero: these are internal transfers paid by the other members,"
                                 + " required because stability constraints dominate the raw usage shares")

    blocking_summary = {
        "core_status": "empty" if core_empty else "nonempty",
        "fractional_epsilon_cents": round(least_core_frac, 4),
        "nucleolus_terminal_excess_cents": round(terminal_excess, 4),
        "integer_epsilon_cents": epsilon_int,
        "by_allocation": [{"name": record["name"], "stable": record["stable"],
                           "worst_violation_cents": record["worst_violation_cents"],
                           "coalitions": record["blocking_coalitions"]}
                          for record in allocations],
    }
    return allocations, blocking_summary, diagnostics, economies_of_scale(identifiers, costs, members)


def infeasibility_report(costs, identifiers):
    identifier_set = frozenset(identifiers)
    infeasible = [coalition for coalition, cost in costs.items() if cost is None and coalition]
    minimal = [sorted(coalition) for coalition in infeasible
               if all(costs.get(frozenset(coalition - {identifier})) is not None
                      for identifier in coalition)]
    maximal = [sorted(coalition) for coalition, cost in costs.items()
               if cost is not None and coalition
               and all(costs.get(frozenset(coalition | frozenset((identifier,)))) is None
                       for identifier in identifier_set - coalition)]
    return minimal, maximal


def analyze(case, scenario_name=None):
    """Full analysis payload for a case (optionally under a named scenario)."""
    identifiers = [member["id"] for member in case["members"]]
    work_case = apply_scenario(case, scenario_name)
    costs = characteristic_costs(work_case, identifiers)
    diagnostics = []
    if costs[frozenset(identifiers)] is None:
        minimal, maximal = infeasibility_report(costs, identifiers)
        diagnostics.append("grand coalition is infeasible under the current fleet; no allocation is produced")
        diagnostics.append("minimal infeasible member combinations pin down the conflict: " + str(minimal))
        diagnostics.append("largest feasible combinations are: " + str(maximal))
        lane_load = {}
        for member in work_case["members"]:
            lane_load.setdefault(member["lane"], {"boxes": 0, "kg": 0})
            lane_load[member["lane"]]["boxes"] += member["boxes"]
            lane_load[member["lane"]]["kg"] += member["kg"]
        diagnostics.append("demand by lane: " + str(lane_load))
        payload = {
            "snapshot": case["_snapshot"], "scenario": scenario_name, "feasible": False,
            "total_cost": None, "allocations": [],
            "blocking": {"core_status": "undefined_infeasible_grand_coalition",
                         "fractional_epsilon_cents": None,
                         "nucleolus_terminal_excess_cents": None,
                         "integer_epsilon_cents": None,
                         "infeasible_minimal_coalitions": minimal,
                         "infeasible_maximal_coalitions": maximal,
                         "by_allocation": []},
            "gains": None, "diagnostics": diagnostics,
        }
        if scenario_name is None:
            payload["sensitivity"] = _sensitivity(case, identifiers, work_case, costs, payload)
        return payload

    allocations, blocking, method_diagnostics, gains = feasible_analysis(
        work_case, identifiers, costs, scenario_name)
    diagnostics.extend(method_diagnostics)
    payload = {
        "snapshot": case["_snapshot"], "scenario": scenario_name, "feasible": True,
        "total_cost": costs[frozenset(identifiers)], "allocations": allocations,
        "blocking": blocking, "gains": gains, "diagnostics": diagnostics,
    }
    if scenario_name is None:
        payload["sensitivity"] = _sensitivity(case, identifiers, work_case, costs, payload)
    return payload


def _sensitivity_entry(work_case, identifiers, scenario_name):
    costs = characteristic_costs(work_case, identifiers)
    total = costs[frozenset(identifiers)]
    entry = {"scenario": scenario_name, "feasible": total is not None,
             "total_cost_cents": total, "allocations": {}, "core_status": None,
             "integer_epsilon_cents": None}
    if total is not None:
        allocations, blocking, _, _ = feasible_analysis(work_case, identifiers, costs, scenario_name)
        entry["allocations"] = {record["name"]: record["cents"] for record in allocations}
        entry["core_status"] = blocking["core_status"]
        entry["integer_epsilon_cents"] = blocking["integer_epsilon_cents"]
    return entry


def _sensitivity(case, identifiers, baseline_case, baseline_costs, baseline_payload=None):
    """Re-run the same methods under every declared demand/fleet scenario.

    The baseline entry is reused from the primary analysis so the same figures
    appear in both places without a second solve; alternative scenarios are
    solved independently but with identical methods.
    """
    entries = []
    if baseline_payload is not None:
        entries.append({
            "scenario": None, "feasible": baseline_payload["feasible"],
            "total_cost_cents": baseline_payload["total_cost"],
            "allocations": {record["name"]: record["cents"]
                            for record in baseline_payload["allocations"]},
            "core_status": baseline_payload["blocking"]["core_status"],
            "integer_epsilon_cents": baseline_payload["blocking"]["integer_epsilon_cents"],
        })
    else:
        entries.append(_sensitivity_entry(baseline_case, identifiers, None))
    for scenario_name in [entry["name"] for entry in case.get("scenarios", [])]:
        work_case = apply_scenario(case, scenario_name)
        entries.append(_sensitivity_entry(work_case, identifiers, scenario_name))
    return entries
