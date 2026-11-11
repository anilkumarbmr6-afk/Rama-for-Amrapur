"""Illustrative campaign-channel allocation model for the fictional STC case.

Run with: py campaign_optimizer.py

The model maximizes expected vote movements, not a prediction of election results.
See the assumptions printed with the solution before using the allocation.
"""

from dataclasses import dataclass
from fractions import Fraction

from ortools.sat.python import cp_model


@dataclass(frozen=True)
class Channel:
    name: str
    cost_rupees: int
    reach_num: int
    reach_den: int
    rate_per_100: int
    max_units: int


TOTAL_BUDGET = 2_800_000
FIXED_COSTS = 600_000 + 2 * 268 * 750 + 10_000
VARIABLE_BUDGET = TOTAL_BUDGET - FIXED_COSTS
ELECTORS = 242_000
PERSUADABLE_POOL = 93_434
UNIQUE_REACH_FACTOR = Fraction(65, 100)
OBJECTIVE_SCALE = 1_000_000

# Door contacts are households; 121/39 is the case's 242,000 electors / 78,000
# households. Repeat visits are modeled at half the stated door-persuasion rate.
channels = [
    Channel("door_first_household", 6, 121, 39, 15, 78_000),
    Channel("door_repeat_household", 6, 121, 39, 15, 78_000),
    Channel("village_meeting", 6_000, 150, 1, 25, 354),
    Channel("shg_circle", 2_000, 35, 1, 30, 31_000 // 35),
    Channel("whatsapp_voter", 1, 1, 1, 3, ELECTORS * 52 // 100),
    Channel("pamphlet_household", 2, 121, 39, 1, 78_000),
    Channel("auto_day", 3_000, 2_000, 1, 1, 118),
]


def scaled_vote_value(
    channel: Channel,
    persuadable_pool: int = PERSUADABLE_POOL,
    unique_reach_factor: Fraction = UNIQUE_REACH_FACTOR,
    rate_multiplier: Fraction = Fraction(1),
) -> int:
    """Return millionths of modeled vote movements per decision unit."""
    value = (
        Fraction(channel.reach_num, channel.reach_den)
        * Fraction(persuadable_pool, ELECTORS)
        * unique_reach_factor
        * Fraction(channel.rate_per_100, 100)
        * rate_multiplier
    )
    return round(value * OBJECTIVE_SCALE)


def optimize_campaign(
    total_budget: int = TOTAL_BUDGET,
    persuadable_pool: int = PERSUADABLE_POOL,
    overlap_percent: int = 65,
    repeat_visit_percent: int = 50,
    max_solve_seconds: int = 10,
) -> dict:
    """Optimize activity units and return allocation and calculation details."""
    if not FIXED_COSTS <= total_budget <= 4_000_000:
        raise ValueError(
            f"Total budget must be between fixed costs "
            f"(INR {FIXED_COSTS:,}) and the INR 4,000,000 legal cap."
        )
    if not 0 <= persuadable_pool <= ELECTORS:
        raise ValueError(f"Persuadable pool must be between 0 and {ELECTORS:,}.")
    if not 1 <= overlap_percent <= 100:
        raise ValueError("Overlap percentage must be between 1 and 100.")
    if not 0 <= repeat_visit_percent <= 100:
        raise ValueError("Repeat-visit effect must be between 0 and 100.")

    variable_budget = total_budget - FIXED_COSTS
    unique_reach_factor = Fraction(overlap_percent, 100)
    repeat_visit_multiplier = Fraction(repeat_visit_percent, 100)
    model = cp_model.CpModel()
    units = {
        channel.name: model.NewIntVar(0, channel.max_units, channel.name)
        for channel in channels
    }

    model.Add(
        sum(channel.cost_rupees * units[channel.name] for channel in channels)
        <= variable_budget
    )
    model.Add(units["door_repeat_household"] <= units["door_first_household"])
    model.Add(
        units["door_first_household"] + units["door_repeat_household"] <= 160_000
    )
    model.Add(35 * units["shg_circle"] <= 31_000)

    # Cap effective persuadable reach at the selected survey-derived pool.
    # Reach is scaled by 39 to keep household-to-voter conversion integral.
    reach_exposures_39 = (
        121 * units["door_first_household"]
        + 121 * units["door_repeat_household"]
        + 150 * 39 * units["village_meeting"]
        + 35 * 39 * units["shg_circle"]
        + 39 * units["whatsapp_voter"]
        + 121 * units["pamphlet_household"]
        + 2_000 * 39 * units["auto_day"]
    )
    if persuadable_pool:
        model.Add(
            reach_exposures_39
            <= ELECTORS * 39 * 100 // overlap_percent
        )

    objective = []
    for channel in channels:
        multiplier = (
            repeat_visit_multiplier
            if channel.name == "door_repeat_household"
            else Fraction(1)
        )
        objective.append(
            scaled_vote_value(
                channel,
                persuadable_pool,
                unique_reach_factor,
                multiplier,
            )
            * units[channel.name]
        )
    model.Maximize(sum(objective))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_solve_seconds
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"OR-Tools did not find a solution: {solver.StatusName(status)}")

    allocation = []
    for channel in channels:
        count = solver.Value(units[channel.name])
        repeat_multiplier = (
            repeat_visit_multiplier
            if channel.name == "door_repeat_household"
            else Fraction(1)
        )
        expected_moves = (
            scaled_vote_value(
                channel,
                persuadable_pool,
                unique_reach_factor,
                repeat_multiplier,
            )
            * count
            / OBJECTIVE_SCALE
        )
        allocation.append(
            {
                "channel": channel.name,
                "units": count,
                "unit_cost": channel.cost_rupees,
                "spend": channel.cost_rupees * count,
                "reach_per_unit": channel.reach_num / channel.reach_den,
                "base_rate_percent": channel.rate_per_100,
                "rate_percent": channel.rate_per_100
                * float(repeat_multiplier),
                "expected_moves": expected_moves,
            }
        )

    spend = sum(row["spend"] for row in allocation)
    expected_moves = sum(row["expected_moves"] for row in allocation)
    return {
        "status": solver.StatusName(status),
        "total_budget": total_budget,
        "fixed_costs": FIXED_COSTS,
        "variable_budget": variable_budget,
        "activity_spend": spend,
        "unused_budget": variable_budget - spend,
        "expected_moves": expected_moves,
        "allocation": allocation,
        "persuadable_pool": persuadable_pool,
        "overlap_percent": overlap_percent,
        "repeat_visit_percent": repeat_visit_percent,
    }


def main() -> None:
    result = optimize_campaign()
    print(f"Solver status: {result['status']}")
    print(f"Fixed costs: INR {result['fixed_costs']:,.0f}")
    print(f"Optimized activity spend: INR {result['activity_spend']:,.0f}")
    print(f"Unused budget: INR {result['unused_budget']:,.0f}")
    print(f"Expected vote movements (model estimate): {result['expected_moves']:,.0f}")
    print("Allocation:")
    for row in result["allocation"]:
        if row["units"]:
            print(
                f"  {row['channel']}: {row['units']:,} units "
                f"(INR {row['spend']:,.0f})"
            )
    print(
        "\nAssumptions: 38.6% of contacted voters are in the survey-derived "
        "persuadable pool; 65% of gross reach is non-overlapping; repeat door "
        "visits have half the first-visit effect. Reels and paid social ads are "
        "excluded because the case gives views/impressions, not unique-voter reach."
    )


if __name__ == "__main__":
    main()
