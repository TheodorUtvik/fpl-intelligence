"""
Feature engineering pipeline.

Transforms the merged FPL + Understat dataset into a modelling-ready
feature matrix. All rolling features use shift(1) before rolling to
ensure no data from gameweek N leaks into features for gameweek N.

Usage
-----
    from src.features.engineer import FeatureEngineer

    eng = FeatureEngineer()
    features_df = eng.fit_transform(merged_df, fixtures_df)
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TOTAL_FPL_PLAYERS = 13_038_826

FEATURE_COLS = [
    'player_id', 'web_name', 'round', 'position', 'team',
    'rolling_pts_3gw', 'rolling_pts_5gw',
    'rolling_minutes_3gw', 'rolling_minutes_5gw',
    'minutes_consistency', 'blank_gw_flag', 'form_streak',
    'rolling_xg_3gw', 'rolling_xg_5gw',
    'rolling_xa_3gw', 'rolling_xa_5gw',
    'xg_overperformance', 'shots_per_90', 'key_passes_per_90',
    'fdr_next', 'fdr_next3', 'is_home_next',
    'opp_goals_conceded_avg', 'has_fixture',
    'value', 'price_change_3gw', 'pts_per_million',
    'ownership_pct', 'ownership_change_3gw', 'is_differential',
    'gw_number', 'games_played',
    'is_gkp', 'is_def', 'is_mid', 'is_fwd',
    'pts_next_gw',
]


class FeatureEngineer:

    def fit_transform(
        self,
        merged_df: pd.DataFrame,
        fixtures_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Build the full feature set from the merged dataset.

        Parameters
        ----------
        merged_df : pd.DataFrame
            Output of the Phase 2 merge (merged_players.parquet).
        fixtures_df : pd.DataFrame
            Raw fixtures from fpl_fixtures.parquet.

        Returns
        -------
        pd.DataFrame
            One row per player per gameweek with all engineered features
            and the target column `pts_next_gw`.
        """
        df = merged_df.copy()
        df = self._fix_dtypes(df)
        df = self._aggregate_player_round(df)
        df = self._rolling_form(df)
        df = self._rolling_xg(df)
        df = self._fixture_features(df, fixtures_df)
        df = self._value_features(df)
        df = self._encode_position(df)
        df = self._target(df)
        df = self._select_and_filter(df)
        logger.info(f"Feature engineering complete: {df.shape}")
        return df

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    def _fix_dtypes(self, df: pd.DataFrame) -> pd.DataFrame:
        for col in ['influence', 'creativity', 'threat', 'ict_index']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        df['kickoff_time'] = pd.to_datetime(df['kickoff_time'], utc=True, errors='coerce')

        xg_cols = ['xG', 'xA', 'shots', 'key_passes', 'npxG', 'xGChain', 'xGBuildup', 'us_minutes']
        df[xg_cols] = df[xg_cols].fillna(0)

        df = df.sort_values(['player_id', 'round']).reset_index(drop=True)
        return df

    def _aggregate_player_round(self, df: pd.DataFrame) -> pd.DataFrame:
        before = len(df)
        df = df.sort_values(['player_id', 'round', 'kickoff_time']).reset_index(drop=True)

        sum_cols = [
            'total_points', 'minutes', 'goals_scored', 'assists', 'clean_sheets',
            'goals_conceded', 'own_goals', 'penalties_saved', 'penalties_missed',
            'yellow_cards', 'red_cards', 'saves', 'bonus', 'bps',
            'influence', 'creativity', 'threat', 'ict_index',
            'xG', 'xA', 'shots', 'key_passes', 'npxG', 'xGChain', 'xGBuildup', 'us_minutes',
        ]
        last_cols = ['value', 'selected', 'now_cost', 'kickoff_time']
        first_cols = ['web_name', 'position', 'team']

        agg = {}
        for col in sum_cols:
            if col in df.columns:
                agg[col] = 'sum'
        for col in last_cols:
            if col in df.columns:
                agg[col] = 'last'
        for col in first_cols:
            if col in df.columns:
                agg[col] = 'first'

        out = df.groupby(['player_id', 'round'], as_index=False).agg(agg)
        if len(out) < before:
            logger.info(f"Collapsed merged rows from {before} to {len(out)} on (player_id, round)")
        return out

    def _rolling_mean(self, group: pd.DataFrame, col: str, window: int) -> pd.Series:
        return group[col].shift(1).rolling(window, min_periods=1).mean()

    def _rolling_std(self, group: pd.DataFrame, col: str, window: int) -> pd.Series:
        return group[col].shift(1).rolling(window, min_periods=2).std()

    def _rolling_form(self, df: pd.DataFrame) -> pd.DataFrame:
        for col, windows in [('total_points', [3, 5]), ('minutes', [3, 5])]:
            prefix = 'rolling_pts' if col == 'total_points' else 'rolling_minutes'
            for w in windows:
                df[f'{prefix}_{w}gw'] = df.groupby('player_id', group_keys=False).apply(
                    lambda g, c=col, ww=w: self._rolling_mean(g, c, ww)
                )

        df['minutes_consistency'] = df.groupby('player_id', group_keys=False).apply(
            lambda g: self._rolling_std(g, 'minutes', 5)
        ).fillna(0)

        df['prev_minutes'] = df.groupby('player_id')['minutes'].shift(1)
        df['blank_gw_flag'] = (df['prev_minutes'] == 0).astype(int)
        df.drop(columns=['prev_minutes'], inplace=True)

        def _streak(group):
            pts = group['total_points'].shift(1)
            streak, count = [], 0
            for p in pts:
                if pd.isna(p):
                    streak.append(0)
                elif p > 4:
                    count += 1
                    streak.append(count)
                else:
                    count = 0
                    streak.append(0)
            return pd.Series(streak, index=group.index)

        df['form_streak'] = df.groupby('player_id', group_keys=False).apply(_streak)
        return df

    def _rolling_xg(self, df: pd.DataFrame) -> pd.DataFrame:
        for stat, windows in [('xG', [3, 5]), ('xA', [3, 5])]:
            for w in windows:
                df[f'rolling_{stat.lower()}_{w}gw'] = df.groupby('player_id', group_keys=False).apply(
                    lambda g, s=stat, ww=w: self._rolling_mean(g, s, ww)
                )

        df['goals_minus_xg'] = df['goals_scored'] - df['xG']
        df['xg_overperformance'] = df.groupby('player_id', group_keys=False).apply(
            lambda g: self._rolling_mean(g, 'goals_minus_xg', 5)
        ).fillna(0)
        df.drop(columns=['goals_minus_xg'], inplace=True)

        eps = 1e-6
        rolling_shots = df.groupby('player_id', group_keys=False).apply(
            lambda g: self._rolling_mean(g, 'shots', 5)
        )
        rolling_kp = df.groupby('player_id', group_keys=False).apply(
            lambda g: self._rolling_mean(g, 'key_passes', 5)
        )
        rolling_min = df.groupby('player_id', group_keys=False).apply(
            lambda g: self._rolling_mean(g, 'minutes', 5)
        )
        df['shots_per_90'] = (rolling_shots / (rolling_min / 90 + eps)).fillna(0)
        df['key_passes_per_90'] = (rolling_kp / (rolling_min / 90 + eps)).fillna(0)
        return df

    def _fixture_features(self, df: pd.DataFrame, fixtures: pd.DataFrame) -> pd.DataFrame:
        # Build home and away perspectives
        home = fixtures[['event', 'team_h', 'team_a', 'team_h_difficulty', 'team_a_difficulty']].rename(
            columns={'event': 'round', 'team_h': 'team_id', 'team_a': 'opponent_id', 'team_h_difficulty': 'fdr'}
        ).assign(is_home=1)[['round', 'team_id', 'opponent_id', 'fdr', 'is_home']]

        away = fixtures[['event', 'team_a', 'team_h', 'team_a_difficulty']].rename(
            columns={'event': 'round', 'team_a': 'team_id', 'team_h': 'opponent_id', 'team_a_difficulty': 'fdr'}
        ).assign(is_home=0)[['round', 'team_id', 'opponent_id', 'fdr', 'is_home']]

        fixture_lookup = pd.concat([home, away], ignore_index=True)

        # Opponent goals conceded rolling average
        finished = fixtures[fixtures['finished'] == True].copy()
        hc = finished[['event', 'team_h', 'team_a_score']].rename(
            columns={'event': 'round', 'team_h': 'team_id', 'team_a_score': 'gc'}
        )
        ac = finished[['event', 'team_a', 'team_h_score']].rename(
            columns={'event': 'round', 'team_a': 'team_id', 'team_h_score': 'gc'}
        )
        tc = pd.concat([hc, ac]).sort_values(['team_id', 'round'])
        tc['gc'] = pd.to_numeric(tc['gc'], errors='coerce').fillna(0)
        tc['opp_goals_conceded_avg'] = tc.groupby('team_id')['gc'].transform(
            lambda x: x.shift(1).rolling(5, min_periods=1).mean()
        )
        opp_lookup = tc[['round', 'team_id', 'opp_goals_conceded_avg']].rename(columns={'round': 'next_round'})

        # Next gameweek features aggregated to one row per team in next round.
        df['next_round'] = df['round'] + 1
        next_fix = fixture_lookup.rename(columns={'round': 'next_round'})
        next_fix = next_fix.merge(
            opp_lookup.rename(columns={'team_id': 'opponent_id'}),
            on=['next_round', 'opponent_id'],
            how='left',
        )
        next_team = (
            next_fix
            .groupby(['next_round', 'team_id'], as_index=False)
            .agg({
                'fdr': 'mean',
                'is_home': 'mean',
                'opp_goals_conceded_avg': 'mean',
            })
            .rename(columns={
                'fdr': 'fdr_next',
                'is_home': 'is_home_next',
            })
        )
        next_team['has_fixture'] = 1

        df = df.merge(
            next_team[['next_round', 'team_id', 'fdr_next', 'is_home_next', 'opp_goals_conceded_avg', 'has_fixture']],
            left_on=['next_round', 'team'], right_on=['next_round', 'team_id'],
            how='left',
        ).drop(columns=['team_id'])

        df['has_fixture'] = df['has_fixture'].fillna(0).astype(int)
        df['fdr_next'] = df['fdr_next'].fillna(3.0)
        df['is_home_next'] = df['is_home_next'].fillna(0.0)

        median_opp_gc = df['opp_goals_conceded_avg'].median()
        df['opp_goals_conceded_avg'] = df['opp_goals_conceded_avg'].fillna(median_opp_gc)

        # FDR next 3 fixtures
        def _fdr3(player_df):
            results = []
            for _, row in player_df.iterrows():
                future = fixture_lookup[
                    (fixture_lookup['round'].isin([row['round'] + 1, row['round'] + 2, row['round'] + 3])) &
                    (fixture_lookup['team_id'] == row['team'])
                ]['fdr']
                results.append(future.mean() if not future.empty else np.nan)
            return pd.Series(results, index=player_df.index)

        df['fdr_next3'] = df.groupby('player_id', group_keys=False).apply(_fdr3).fillna(3.0)
        return df

    def _value_features(self, df: pd.DataFrame) -> pd.DataFrame:
        df['price_change_3gw'] = (df['value'] - df.groupby('player_id')['value'].shift(3)).fillna(0)
        df['pts_per_million'] = (df['rolling_pts_5gw'] / df['value'].replace(0, np.nan)).fillna(0)
        df['ownership_pct'] = (df['selected'] / TOTAL_FPL_PLAYERS * 100).round(2)
        df['ownership_change_3gw'] = (
            df['ownership_pct'] - df.groupby('player_id')['ownership_pct'].shift(3)
        ).fillna(0)
        df['is_differential'] = (df['ownership_pct'] < 10).astype(int)
        df['gw_number'] = df['round']
        df['games_played'] = df.groupby('player_id').cumcount()
        return df

    def _encode_position(self, df: pd.DataFrame) -> pd.DataFrame:
        for pos in ['GKP', 'DEF', 'MID', 'FWD']:
            df[f'is_{pos.lower()}'] = (df['position'] == pos).astype(int)
        return df

    def _target(self, df: pd.DataFrame) -> pd.DataFrame:
        df['pts_next_gw'] = df.groupby('player_id')['total_points'].shift(-1)
        return df

    def _select_and_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        cols = [c for c in FEATURE_COLS if c in df.columns]
        out = df[cols].copy()
        # Drop only rows missing key features — NOT pts_next_gw.
        # Round N's pts_next_gw is null when GW N+1 hasn't been played yet
        # (i.e. the current/latest round). We KEEP those rows so inference
        # can predict the upcoming GW. The training step already gates on
        # `round < latest_complete_gw`, so null targets never enter training.
        out = out.dropna(subset=['rolling_pts_3gw'])
        return out
