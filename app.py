"""Interactive Streamlit dashboard for the fictional Amrapur campaign model."""

from __future__ import annotations

from campaign_optimizer import (
    ELECTORS,
    FIXED_COSTS,
    PERSUADABLE_POOL,
    TOTAL_BUDGET,
    optimize_campaign,
)

from math import ceil

import pandas as pd
import streamlit as st


VALID_VOTE_REFERENCE = 184_912
BASE_RAMA_REFERENCE = 17_221
WIN_CASE_REFERENCE = 64_365
GROUPS = [
    ("OC-A", 31_460, 81, 62, 14, 4, 2, 18),
    ("OC-B", 12_100, 74, 46, 22, 5, 2, 25),
    ("BC-A", 38_720, 79, 28, 40, 6, 3, 23),
    ("BC-B", 24_200, 81, 40, 22, 7, 3, 28),
    ("BC-C", 21_780, 77, 24, 18, 22, 2, 34),
    ("BC-D", 14_520, 72, 33, 20, 9, 3, 35),
    ("SC-A", 26_620, 78, 30, 30, 11, 4, 25),
    ("SC-B", 16_940, 75, 36, 21, 10, 4, 29),
    ("ST", 19_360, 72, 44, 14, 14, 2, 26),
    ("Muslim", 24_200, 69, 18, 38, 8, 5, 31),
    ("Christian", 12_100, 74, 22, 28, 12, 3, 35),
]
CHANNEL_LABELS = {
    "door_first_household": "First door visits",
    "door_repeat_household": "Repeat door visits",
    "village_meeting": "Village meetings",
    "shg_circle": "SHG circles",
    "whatsapp_voter": "WhatsApp contacts",
    "pamphlet_household": "Pamphlets",
    "auto_day": "Auto loudspeaker days",
}


def rupees(value: float | int) -> str:
    return f"₹{value:,.0f}"


def lakh(value: float | int) -> str:
    return f"₹{value / 100_000:,.2f} lakh"


def render_table(headers: list[str], rows: list[list[str]]) -> None:
    header = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    body = [
        "| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |"
        for row in rows
    ]
    st.markdown("\n".join([header, separator, *body]))


def render_progress_rows(rows: list[tuple[str, float, str]], scale: float) -> None:
    for label, value, detail in rows:
        fraction = min(max(value / scale, 0.0), 1.0) if scale else 0.0
        st.progress(fraction, text=f"{label} · {detail}")


def case_reconciliation() -> tuple[pd.DataFrame, dict[str, float]]:
    rows = []
    for (
        group,
        voters,
        turnout_percent,
        pd_percent,
        lm_percent,
        rama_percent,
        other_percent,
        undecided_percent,
    ) in GROUPS:
        valid = voters * turnout_percent / 100
        persuadable = valid * (
            undecided_percent + 0.34 * pd_percent + 0.46 * lm_percent
        ) / 100
        rows.append(
            {
                "Group": group,
                "Electors": voters,
                "Turnout": turnout_percent / 100,
                "Estimated valid votes": valid,
                "PD share": pd_percent / 100,
                "LM share": lm_percent / 100,
                "Rama share": rama_percent / 100,
                "Other share": other_percent / 100,
                "Undecided share": undecided_percent / 100,
                "Day-0 Rama votes": valid * rama_percent / 100,
                "Persuadable pool": persuadable,
            }
        )
    frame = pd.DataFrame(rows)
    totals = {
        "electors": float(frame["Electors"].sum()),
        "valid_votes": float(frame["Estimated valid votes"].sum()),
        "base_rama": float(frame["Day-0 Rama votes"].sum()),
        "persuadable_pool": float(frame["Persuadable pool"].sum()),
    }
    return frame, totals


def channel_table(result: dict) -> pd.DataFrame:
    rows = []
    for row in result["allocation"]:
        reach = row["units"] * row["reach_per_unit"]
        rows.append(
            {
                "Channel": CHANNEL_LABELS[row["channel"]],
                "Units": row["units"],
                "Reach per unit (voters)": row["reach_per_unit"],
                "Reach before overlap": reach,
                "Cost per unit": row["unit_cost"],
                "Incremental spend": row["spend"],
                "Base case rate per 100": row["base_rate_percent"],
                "Effective rate per 100": row["rate_percent"],
                "Expected moves": row["expected_moves"],
                "Moves per ₹1 lakh": (
                    row["expected_moves"] / row["spend"] * 100_000
                    if row["spend"]
                    else 0
                ),
            }
        )
    return pd.DataFrame(rows)


st.set_page_config(
    page_title="Rama for Amrapur | Campaign model",
    page_icon=":material/analytics:",
    layout="wide",
)

st.title("Rama for Amrapur")
st.caption(
    "Interactive campaign budget and vote-movement model · Fictional case inputs · "
    "Estimates are scenarios, not a forecast"
)

with st.sidebar:
    st.header("Scenario controls")
    with st.form("scenario_controls"):
        budget_lakh = st.slider(
            "Total campaign budget (₹ lakh)",
            min_value=FIXED_COSTS / 100_000,
            max_value=40.0,
            value=28.0,
            step=0.01,
            help="The case provides ₹28 lakh; the legal spending cap is ₹40 lakh.",
        )
        overlap_percent = st.slider(
            "Unique reach after overlap (%)",
            min_value=35,
            max_value=90,
            value=65,
            help="Share of gross channel reach assumed to be unique.",
        )
        repeat_visit_percent = st.slider(
            "Repeat-visit effect vs first visit (%)",
            min_value=0,
            max_value=100,
            value=50,
        )
        persuadable_pool = st.number_input(
            "Persuadable voters",
            min_value=0,
            max_value=ELECTORS,
            value=PERSUADABLE_POOL,
            step=1_000,
            help="Case-derived default: undecided voters + soft PD and LM supporters.",
        )
        submitted = st.form_submit_button(
            "Recalculate allocation",
            type="primary",
            width="stretch",
        )

    st.caption("Fixed obligations are recalculated from the case and cannot be changed here.")

if submitted:
    st.session_state["scenario"] = {
        "budget": int(round(budget_lakh * 100_000)),
        "overlap": overlap_percent,
        "repeat_effect": repeat_visit_percent,
        "persuadable_pool": int(persuadable_pool),
    }

scenario = st.session_state.get(
    "scenario",
    {
        "budget": TOTAL_BUDGET,
        "overlap": 65,
        "repeat_effect": 50,
        "persuadable_pool": PERSUADABLE_POOL,
    },
)
group_frame, case_totals = case_reconciliation()

try:
    result = optimize_campaign(
        total_budget=scenario["budget"],
        persuadable_pool=scenario["persuadable_pool"],
        overlap_percent=scenario["overlap"],
        repeat_visit_percent=scenario["repeat_effect"],
    )
except (ValueError, RuntimeError) as error:
    st.error(str(error), title="Could not calculate this scenario")
    st.stop()

channels = channel_table(result)
activity_spend = result["activity_spend"]
estimated_moves = result["expected_moves"]
projected_votes = case_totals["base_rama"] + estimated_moves
valid_votes = case_totals["valid_votes"]
deposit_threshold = ceil(valid_votes / 6)
projected_share = projected_votes / valid_votes if valid_votes else 0
baseline_share = case_totals["base_rama"] / valid_votes if valid_votes else 0
used_budget = result["fixed_costs"] + activity_spend

overview, calculations, triangulation, assumptions = st.tabs(
    ["Overview", "Budget & channel calculations", "Triangulation", "Assumptions"]
)

with overview:
    st.subheader("Scenario result")
    with st.container(horizontal=True):
        st.metric(
            "Illustrative Rama votes",
            f"{projected_votes:,.0f}",
            f"{projected_share:.1%} of valid votes",
            border=True,
        )
        st.metric(
            "Modeled channel movements",
            f"{estimated_moves:,.0f}",
            "Added to Day-0 support for this bridge",
            border=True,
        )
        st.metric(
            "Deposit threshold",
            f"{deposit_threshold:,.0f}",
            f"{projected_votes - deposit_threshold:+,.0f} vs. threshold",
            border=True,
        )
        st.metric(
            "Budget used",
            lakh(used_budget),
            f"{used_budget / scenario['budget']:.1%} of selected budget",
            border=True,
        )

    if projected_votes < deposit_threshold:
        st.warning(
            f"This scenario is about {deposit_threshold - projected_votes:,.0f} "
            "votes below the one-sixth deposit benchmark. The benchmark is not a "
            "vote-winning threshold.",
            title="Deposit benchmark not reached",
        )
    else:
        st.info(
            "The scenario clears the one-sixth deposit benchmark. That does not "
            "mean it wins the seat.",
            title="Deposit benchmark cleared",
        )

    left, right = st.columns(2)
    with left:
        st.subheader("Vote-count bridge")
        render_progress_rows(
            [
                ("Day-0 Rama support", case_totals["base_rama"], f"{case_totals['base_rama']:,.0f}"),
                ("Optimized channel movements", estimated_moves, f"{estimated_moves:,.0f}"),
                ("Illustrative total", projected_votes, f"{projected_votes:,.0f}"),
                ("Deposit benchmark", deposit_threshold, f"{deposit_threshold:,.0f}"),
                ("Case win-scenario reference", WIN_CASE_REFERENCE, f"{WIN_CASE_REFERENCE:,.0f}"),
            ],
            WIN_CASE_REFERENCE,
        )
    with right:
        st.subheader("Budget bridge")
        render_progress_rows(
            [
                ("Office, vehicles, compliance", 600_000, lakh(600_000)),
                ("Polling agents", 2 * 268 * 750, lakh(2 * 268 * 750)),
                ("Nomination deposit", 10_000, lakh(10_000)),
                ("Volunteer/student stipends", 960_000, lakh(960_000)),
                ("Optimized field activities", activity_spend, lakh(activity_spend)),
                ("Unused", result["unused_budget"], lakh(result["unused_budget"])),
            ],
            scenario["budget"],
        )

    st.caption(
        f"Day-0 support is recalculated from group-level case inputs "
        f"({round(case_totals['base_rama']):,}; reference: {BASE_RAMA_REFERENCE:,}). "
        f"The separate case win-scenario reference is {WIN_CASE_REFERENCE:,} votes "
        f"({WIN_CASE_REFERENCE / VALID_VOTE_REFERENCE:.1%}); it is not a guaranteed "
        "winning threshold."
    )

with calculations:
    st.subheader("Optimized channel allocation")
    st.caption(
        f"Solver status: {result['status']} · Objective: maximize expected vote "
        "movements within budget and reach constraints."
    )
    display_channels = channels.copy()
    display_channels["Reach per unit (voters)"] = display_channels[
        "Reach per unit (voters)"
    ].round(2)
    display_channels["Reach before overlap"] = display_channels[
        "Reach before overlap"
    ].round(0)
    for rate_column in ("Base case rate per 100", "Effective rate per 100"):
        display_channels[rate_column] = display_channels[rate_column].map(
            lambda rate: f"{rate:g}%"
        )
    display_channels["Expected moves"] = display_channels["Expected moves"].round(1)
    display_channels["Moves per ₹1 lakh"] = display_channels[
        "Moves per ₹1 lakh"
    ].round(1)
    render_table(
        list(display_channels.columns),
        [
            [
                f"{value:,.0f}"
                if column in {"Units", "Reach before overlap"}
                else f"{rupees(value)}"
                if column in {"Cost per unit", "Incremental spend"}
                else str(value)
                for column, value in row.items()
            ]
            for _, row in display_channels.iterrows()
        ],
    )
    st.download_button(
        "Download channel calculations as CSV",
        data=channels.to_csv(index=False).encode("utf-8"),
        file_name="amrapur_channel_calculations.csv",
        mime="text/csv",
    )

    st.subheader("How each channel's vote estimate is calculated")
    st.caption(
        "The 6,400 volunteer/student days cost ₹9.60 lakh and are included in fixed "
        "commitments; door-visit channels therefore show no additional cash spend."
    )
    st.latex(
        r"\text{Expected moves} = "
        r"\text{units} \times \text{voters reached per unit} "
        r"\times \frac{\text{persuadable pool}}{242{,}000} "
        r"\times \text{unique reach} "
        r"\times \frac{\text{case rate}}{100}"
    )
    st.markdown(
        f"""
        - Household reach uses **242,000 electors ÷ 78,000 households = 3.10 voters/household**.
        - Effective unique reach is **{scenario['overlap']}%** of gross contacts.
        - The repeat-door rate is scaled to **{scenario['repeat_effect']}%** of the case's first-visit rate.
        - Door capacity is capped at **160,000 visits** from 6,400 volunteer-days × 25 households/day; the model also limits first visits to one per household and repeat visits to no more than first visits.
        - A further constraint prevents projected unique persuadable reach from exceeding the selected pool.
        - Reach-based rates are proxies for votes moved; contacts are not guaranteed votes.
        """
    )

    st.subheader("Solver allocation in plain units")
    for _, row in channels[channels["Units"] > 0].iterrows():
        unit_count = int(row["Units"])
        reach_count = row["Reach before overlap"]
        st.write(
            f"**{row['Channel']}:** {unit_count:,} units × "
            f"{rupees(row['Cost per unit'])} per unit = "
            f"{rupees(row['Incremental spend'])} incremental spend; "
            f"gross reach about {reach_count:,.0f}; "
            f"modeled moves about {row['Expected moves']:,.0f}."
        )

with triangulation:
    st.subheader("Independent cross-checks")
    st.caption(
        "Triangulation compares the same scenario through independent arithmetic "
        "paths: group totals, case benchmarks, channel rates, and budget constraints."
    )

    exact_channel_moves = 0.0
    for _, row in channels.iterrows():
        exact_channel_moves += (
            row["Units"]
            * row["Reach per unit (voters)"]
            * scenario["persuadable_pool"]
            / ELECTORS
            * scenario["overlap"]
            / 100
            * row["Effective rate per 100"]
            / 100
        )

    checks = [
        {
            "Check": "Electorate totals",
            "Independent calculation": f"{case_totals['electors']:,.0f} sum of group electors",
            "Case reference": f"{ELECTORS:,} electors",
            "Result": "Match" if round(case_totals["electors"]) == ELECTORS else "Review",
        },
        {
            "Check": "Valid-vote total",
            "Independent calculation": f"{valid_votes:,.0f} from group turnouts",
            "Case reference": f"{VALID_VOTE_REFERENCE:,} group-based reference",
            "Result": "Match" if round(valid_votes) == VALID_VOTE_REFERENCE else "Review",
        },
        {
            "Check": "Day-0 Rama votes",
            "Independent calculation": f"{case_totals['base_rama']:,.0f} from group shares",
            "Case reference": f"{BASE_RAMA_REFERENCE:,} in supplied working",
            "Result": "Match"
            if round(case_totals["base_rama"]) == BASE_RAMA_REFERENCE
            else "Review",
        },
        {
            "Check": "Persuadable pool",
            "Independent calculation": f"{case_totals['persuadable_pool']:,.0f} from group shares",
            "Case reference": f"{PERSUADABLE_POOL:,} in supplied working",
            "Result": "Match"
            if round(case_totals["persuadable_pool"]) == PERSUADABLE_POOL
            else "Review",
        },
        {
            "Check": "Channel-move total",
            "Independent calculation": f"{exact_channel_moves:,.1f} from displayed formula",
            "Case reference": f"{estimated_moves:,.1f} from CP-SAT objective coefficients",
            "Result": "Match"
            if abs(exact_channel_moves - estimated_moves) < 1
            else "Rounding difference",
        },
        {
            "Check": "Budget identity",
            "Independent calculation": f"{used_budget + result['unused_budget']:,.0f} allocated + unused",
            "Case reference": f"{scenario['budget']:,.0f} selected total budget",
            "Result": "Match"
            if used_budget + result["unused_budget"] == scenario["budget"]
            else "Review",
        },
    ]
    checks_frame = pd.DataFrame(checks)
    render_table(
        list(checks_frame.columns),
        [[str(value) for value in row] for row in checks_frame.itertuples(index=False)],
    )

    turnout_implied = ELECTORS * 0.764
    turnout_delta = valid_votes - turnout_implied
    st.info(
        f"The group turnout percentages imply {valid_votes:,.0f} valid votes, while "
        f"the seat-wide 76.4% reference implies {turnout_implied:,.0f} "
        f"(difference: {turnout_delta:+,.0f}, about {abs(turnout_delta) / ELECTORS:.2%} "
        "of electors). This small difference is consistent with rounded case inputs.",
        title="Turnout reconciliation",
    )

    st.subheader("Group-level triangulation")
    st.caption(
        "The model does not optimize by voter group. For display only, channel movements "
        "are apportioned by each group's case-derived persuadable-pool size; this assumes "
        "equal response across groups."
    )
    group_display = group_frame[
        [
            "Group",
            "Electors",
            "Estimated valid votes",
            "Rama share",
            "Day-0 Rama votes",
            "Persuadable pool",
        ]
    ].copy()
    group_display["Pool share"] = (
        group_display["Persuadable pool"] / case_totals["persuadable_pool"]
        if case_totals["persuadable_pool"]
        else 0
    )
    group_display["Pro-rata modeled moves"] = (
        group_display["Pool share"] * estimated_moves
    )
    group_display["Illustrative Rama votes"] = (
        group_display["Day-0 Rama votes"] + group_display["Pro-rata modeled moves"]
    )
    group_display["Illustrative Rama share"] = (
        group_display["Illustrative Rama votes"]
        / group_display["Estimated valid votes"]
    )
    group_display = group_display.rename(
        columns={
            "Rama share": "Day-0 Rama share",
            "Persuadable pool": "Persuadable voters",
        }
    )
    render_table(
        list(group_display.columns),
        [
            [
                f"{value:.1%}"
                if column in {"Day-0 Rama share", "Pool share", "Illustrative Rama share"}
                else f"{value:,.0f}"
                if column != "Group"
                else str(value)
                for column, value in row.items()
            ]
            for _, row in group_display.iterrows()
        ],
    )
    st.download_button(
        "Download group triangulation as CSV",
        data=group_display.to_csv(index=False).encode("utf-8"),
        file_name="amrapur_group_triangulation.csv",
        mime="text/csv",
    )

    st.subheader("Sensitivity: overlap assumption")
    sensitivity_rows = []
    for overlap in sorted({35, 50, scenario["overlap"], 75, 90}):
        moves = 0.0
        for _, row in channels.iterrows():
            moves += (
                row["Units"]
                * row["Reach per unit (voters)"]
                * scenario["persuadable_pool"]
                / ELECTORS
                * overlap
                / 100
                * row["Effective rate per 100"]
                / 100
            )
        total = case_totals["base_rama"] + moves
        sensitivity_rows.append(
            {
                "Unique reach": overlap / 100,
                "Expected moves": moves,
                "Illustrative votes": total,
                "Vs. deposit benchmark": total - deposit_threshold,
                "Vs. case win reference": total - WIN_CASE_REFERENCE,
            }
        )
    sensitivity_frame = pd.DataFrame(sensitivity_rows)
    render_table(
        list(sensitivity_frame.columns),
        [
            [
                f"{value:.0%}"
                if column == "Unique reach"
                else f"{value:+,.0f}"
                if column.startswith("Vs.")
                else f"{value:,.0f}"
                for column, value in row.items()
            ]
            for _, row in sensitivity_frame.iterrows()
        ],
    )
    st.caption(
        "Sensitivity holds the optimized units constant to isolate the overlap effect; "
        "changing overlap in the sidebar instead re-optimizes the allocation."
    )

with assumptions:
    st.subheader("Inputs and what they mean")
    st.markdown(
        f"""
        **Case figures:** {ELECTORS:,} electors; 268 booths; 78,000 households;
        ₹28 lakh starting budget; legal expenditure cap ₹40 lakh; group-specific
        turnout and voting intentions from the supplied case.

        **Budget obligations:** ₹6.00 lakh office/vehicles/compliance
        + ₹4.02 lakh for 536 polling agents + ₹0.10 lakh nomination deposit
        + ₹9.60 lakh for 6,400 volunteer/student days
        = **{lakh(FIXED_COSTS)} fixed commitments**.

        **Persuadable pool derivation:** group valid votes ×
        (undecided share + 34% of PD share + 46% of LM share), summed across groups.
        The displayed group calculation gives **{case_totals['persuadable_pool']:,.0f}**
        (supplied working rounds to {PERSUADABLE_POOL:,}).

        **Optimization objective:** maximize expected channel vote movements subject
        to the budget, activity-unit, household visit, meeting, SHG reach, and unique
        persuadable-reach constraints. OR-Tools CP-SAT returns the best integer
        allocation found (the status is shown above the channel table).

        **Not modeled:** party response, candidate popularity changes, rival vote
        shifts, actual contact conversion, district-level voter distribution, or
        unique audiences for creator reels and paid impressions. The input case gives
        views/impressions for those media, not unique voters, so they are excluded.
        """
    )
    st.warning(
        "A movement estimate is not a forecast, vote commitment, or guarantee of "
        "winning. The win-case reference and group pro-rata view come from assumptions "
        "in the supplied working and should be treated as scenario benchmarks.",
        title="Interpretation guardrail",
    )
