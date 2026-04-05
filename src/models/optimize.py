"""
FPL squad optimizer and transfer advisor.

Uses Integer Linear Programming (PuLP) to select the optimal 15-man
FPL squad and recommend transfers given a manager's current squad.

Usage
-----
    from src.models.optimize import FPLOptimizer

    optimizer = FPLOptimizer()

    # Select optimal squad from scratch
    result = optimizer.select_squad(players_df, budget=100.0)

    # Recommend transfers given current squad
    transfers = optimizer.recommend_transfers(
        current_squad_ids=[...],
        players_df=players_df,
        free_transfers=1,
        bank=0.5,
    )
"""

import logging
from itertools import combinations
from typing import Optional

import pandas as pd
import numpy as np
from pulp import (
    LpProblem, LpMaximize, LpVariable, LpBinary,
    lpSum, value, PULP_CBC_CMD
)

logger = logging.getLogger(__name__)

POSITION_COUNTS = {'GKP': 2, 'DEF': 5, 'MID': 5, 'FWD': 3}
SQUAD_SIZE      = 15
STARTING_XI     = 11
MAX_PER_CLUB    = 3


class FPLOptimizer:
    """
    Selects the optimal FPL squad and recommends transfers using ILP.

    Parameters
    ----------
    budget : float
        Total squad budget in £m (default 100.0).
    """

    def __init__(self, budget: float = 100.0):
        self.budget = budget

    # ------------------------------------------------------------------
    # Squad selection
    # ------------------------------------------------------------------

    def select_squad(
        self,
        players_df: pd.DataFrame,
        budget: Optional[float] = None,
    ) -> dict:
        """
        Select the optimal 15-man squad using ILP.

        Parameters
        ----------
        players_df : pd.DataFrame
            Must contain: player_id, web_name, position, team,
            now_cost (£m), predicted_pts.
        budget : float, optional
            Override the instance budget.

        Returns
        -------
        dict with keys:
            squad        : pd.DataFrame — selected 15 players
            captain      : str          — captain's web_name
            vice_captain : str          — vice-captain's web_name
            predicted_total : float     — total predicted pts (with captain)
            status       : str          — 'Optimal' or 'Infeasible'
        """
        budget = budget or self.budget
        df = players_df.copy().reset_index(drop=True)
        players = df.index.tolist()

        prob = LpProblem("FPL_Squad_Selection", LpMaximize)

        # Decision variables
        x = {p: LpVariable(f"x_{p}", cat=LpBinary) for p in players}  # in squad
        c = {p: LpVariable(f"c_{p}", cat=LpBinary) for p in players}  # is captain

        # Objective: predicted pts, captain counts double
        prob += lpSum(
            df.loc[p, 'predicted_pts'] * x[p] + df.loc[p, 'predicted_pts'] * c[p]
            for p in players
        )

        # Budget
        prob += lpSum(df.loc[p, 'now_cost'] * x[p] for p in players) <= budget

        # Position counts
        for pos, count in POSITION_COUNTS.items():
            pos_players = df[df['position'] == pos].index.tolist()
            prob += lpSum(x[p] for p in pos_players) == count

        # Max 3 per club
        for team_id in df['team'].unique():
            team_players = df[df['team'] == team_id].index.tolist()
            prob += lpSum(x[p] for p in team_players) <= MAX_PER_CLUB

        # Exactly one captain, must be in squad
        prob += lpSum(c[p] for p in players) == 1
        for p in players:
            prob += c[p] <= x[p]

        # Solve
        prob.solve(PULP_CBC_CMD(msg=0))
        status = prob.status

        if status != 1:
            logger.error("LP solver returned non-optimal status.")
            return {'status': 'Infeasible', 'squad': pd.DataFrame()}

        # Extract results
        selected = [p for p in players if value(x[p]) > 0.5]
        captain_idx = next(p for p in players if value(c[p]) > 0.5)

        squad_df = df.loc[selected].copy()
        squad_df['is_captain'] = squad_df.index == captain_idx

        # Vice captain: highest predicted pts among non-captain squad members
        non_cap = squad_df[~squad_df['is_captain']].sort_values('predicted_pts', ascending=False)
        vc_name = non_cap.iloc[0]['web_name']

        # Sort by position then predicted pts
        pos_order = {'GKP': 0, 'DEF': 1, 'MID': 2, 'FWD': 3}
        squad_df['pos_order'] = squad_df['position'].map(pos_order)
        squad_df = squad_df.sort_values(['pos_order', 'predicted_pts'], ascending=[True, False])
        squad_df = squad_df.drop(columns=['pos_order'])

        total_pts = sum(df.loc[p, 'predicted_pts'] * (2 if p == captain_idx else 1) for p in selected)

        logger.info(f"Optimal squad found. Predicted total: {total_pts:.1f} pts")

        return {
            'squad': squad_df.reset_index(drop=True),
            'captain': df.loc[captain_idx, 'web_name'],
            'vice_captain': vc_name,
            'predicted_total': round(total_pts, 2),
            'total_cost': round(squad_df['now_cost'].sum(), 1),
            'status': 'Optimal',
        }

    # ------------------------------------------------------------------
    # Transfer advisor
    # ------------------------------------------------------------------

    def recommend_transfers(
        self,
        current_squad_ids: list[int],
        players_df: pd.DataFrame,
        free_transfers: int = 1,
        bank: float = 0.0,
    ) -> list[dict]:
        """
        Recommend optimal transfers given a manager's current squad.

        Parameters
        ----------
        current_squad_ids : list[int]
            FPL player IDs currently in the squad (15 players).
        players_df : pd.DataFrame
            Full player pool with predicted_pts and now_cost.
        free_transfers : int
            Number of free transfers available (1 or 2).
        bank : float
            Extra budget available in £m (e.g. 0.5 = £0.5m in the bank).

        Returns
        -------
        list[dict] sorted by net_gain descending, each containing:
            transfers_out, transfers_in, gross_gain, hit, net_gain,
            cost_change, is_recommended
        """
        df = players_df.copy()
        current = df[df['player_id'].isin(current_squad_ids)].copy()
        available = df[~df['player_id'].isin(current_squad_ids)].copy()

        results = []

        for n_transfers in range(1, min(free_transfers + 2, 3)):
            hit = max(0, n_transfers - free_transfers) * 4
            out_combos = list(combinations(current.index, n_transfers))

            for out_idxs in out_combos:
                out_players = current.loc[list(out_idxs)]
                out_positions = out_players['position'].tolist()
                out_cost = out_players['now_cost'].sum()
                out_pts  = out_players['predicted_pts'].sum()

                # Find replacements: same positions, budget-neutral or cheaper
                max_spend = out_cost + bank
                pos_counts = {p: out_positions.count(p) for p in set(out_positions)}

                # Filter available to matching positions
                candidates = available.copy()
                # Must not clash with remaining squad (club limit)
                remaining = current.drop(index=list(out_idxs))
                club_counts = remaining['team'].value_counts()

                in_combos = self._find_in_combos(
                    candidates, pos_counts, max_spend, club_counts, n_transfers
                )

                for in_players_df in in_combos:
                    in_pts  = in_players_df['predicted_pts'].sum()
                    in_cost = in_players_df['now_cost'].sum()
                    gross_gain = in_pts - out_pts
                    net_gain   = gross_gain - hit

                    results.append({
                        'n_transfers':   n_transfers,
                        'transfers_out': out_players['web_name'].tolist(),
                        'transfers_in':  in_players_df['web_name'].tolist(),
                        'out_pts':       round(out_pts, 2),
                        'in_pts':        round(in_pts, 2),
                        'gross_gain':    round(gross_gain, 2),
                        'hit':           hit,
                        'net_gain':      round(net_gain, 2),
                        'cost_change':   round(in_cost - out_cost, 1),
                        'is_recommended': net_gain > 0,
                    })

        results.sort(key=lambda r: -r['net_gain'])
        return results[:20]  # return top 20

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_in_combos(
        self,
        candidates: pd.DataFrame,
        pos_counts: dict,
        max_spend: float,
        club_counts: pd.Series,
        n: int,
    ) -> list[pd.DataFrame]:
        """
        Return up to 50 valid replacement combinations respecting
        position, budget, and club constraints.
        """
        results = []

        # Filter to players matching the needed positions
        pos_pool = candidates[candidates['position'].isin(pos_counts.keys())]
        pos_pool = pos_pool[pos_pool['now_cost'] <= max_spend]

        # For single transfers: simple filter
        if n == 1:
            pos = list(pos_counts.keys())[0]
            pool = pos_pool[pos_pool['position'] == pos]
            for _, row in pool.iterrows():
                team_count = club_counts.get(row['team'], 0)
                if team_count < MAX_PER_CLUB:
                    results.append(pd.DataFrame([row]))
                if len(results) >= 50:
                    break
            return results

        # For 2 transfers: find pairs
        for combo in combinations(pos_pool.index, n):
            combo_df = pos_pool.loc[list(combo)]
            # Check positions match requirements
            combo_pos = combo_df['position'].value_counts().to_dict()
            if combo_pos != pos_counts:
                continue
            # Check budget
            if combo_df['now_cost'].sum() > max_spend:
                continue
            # Check club limits
            valid = True
            temp_counts = club_counts.copy()
            for _, row in combo_df.iterrows():
                if temp_counts.get(row['team'], 0) >= MAX_PER_CLUB:
                    valid = False
                    break
                temp_counts[row['team']] = temp_counts.get(row['team'], 0) + 1
            if valid:
                results.append(combo_df)
            if len(results) >= 50:
                break

        return results
