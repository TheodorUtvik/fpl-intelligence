"""
FPL points predictor.

Wraps the trained XGBoost model and SHAP explainer for use by the
Dash app and the LP optimizer.

Usage
-----
    from src.models.predict import FPLPredictor

    predictor = FPLPredictor()
    predictor.load()                          # loads model + explainer from models/
    preds = predictor.predict(features_df)    # pd.Series of predicted pts
    shap_vals = predictor.explain(features_df)  # shap.Explanation object
"""

import json
import logging
import pickle
from pathlib import Path

import pandas as pd

# shap and xgboost are imported lazily inside methods — both are heavy
# at import time (shap triggers numba/CUDA probing; xgb is large).
# This keeps app startup fast; the cost is paid once on first use.

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent.parent.parent / "models"


class FPLPredictor:
    """
    Train, save, load and serve the XGBoost prediction model.

    Parameters
    ----------
    models_dir : Path, optional
        Directory where model artefacts are stored.
        Defaults to the project-level `models/` folder.
    """

    def __init__(self, models_dir: Path = MODELS_DIR):
        self.models_dir = Path(models_dir)
        self.model = None          # xgb.XGBRegressor — loaded lazily
        self.explainer = None      # shap.TreeExplainer — loaded lazily
        self.feature_cols: list[str] | None = None

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(
        self,
        features_df: pd.DataFrame,
        params: dict | None = None,
    ) -> "FPLPredictor":
        """
        Fit XGBoost on the full features DataFrame.

        Parameters
        ----------
        features_df : pd.DataFrame
            Output of FeatureEngineer.fit_transform() — must contain
            all feature columns and `pts_next_gw`.
        params : dict, optional
            XGBoost hyperparameters. If None, uses defaults (or
            best_params.json if it exists in models_dir).

        Returns
        -------
        self
        """
        import shap  # noqa: PLC0415
        import xgboost as xgb  # noqa: PLC0415

        self.feature_cols = self._load_feature_cols()

        if params is None:
            params = self._load_best_params()

        X = features_df[self.feature_cols]
        y = features_df["pts_next_gw"]

        logger.info(f"Training XGBoost on {len(X)} rows, {len(self.feature_cols)} features...")

        self.model = xgb.XGBRegressor(
            n_estimators=params.get("n_estimators", 400),
            max_depth=params.get("max_depth", 5),
            learning_rate=params.get("learning_rate", 0.05),
            subsample=params.get("subsample", 0.8),
            colsample_bytree=params.get("colsample_bytree", 0.8),
            reg_alpha=params.get("reg_alpha", 0.1),
            reg_lambda=params.get("reg_lambda", 1.0),
            random_state=42,
            n_jobs=-1,
            verbosity=0,
        )
        self.model.fit(X, y)
        self.explainer = shap.TreeExplainer(self.model)
        logger.info("Training complete.")
        return self

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict(self, features_df: pd.DataFrame) -> pd.Series:
        """
        Return predicted next-GW points for each row.

        Parameters
        ----------
        features_df : pd.DataFrame
            Must contain all columns in self.feature_cols.

        Returns
        -------
        pd.Series
            Predicted points indexed the same as features_df.
        """
        self._check_loaded()
        X = features_df[self.feature_cols]
        preds = self.model.predict(X)
        return pd.Series(preds, index=features_df.index, name="predicted_pts")

    def explain(self, features_df: pd.DataFrame):
        """
        Return SHAP values for the given rows.

        Parameters
        ----------
        features_df : pd.DataFrame
            Subset of the feature matrix (e.g. a single player's row
            for a waterfall plot, or all players for a beeswarm).

        Returns
        -------
        shap.Explanation
            SHAP Explanation object. Use shap.plots.waterfall(result[0])
            or shap.plots.beeswarm(result) to visualise.
        """
        self._check_loaded()
        X = features_df[self.feature_cols]
        return self.explainer(X)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Save model, explainer and feature list to models_dir."""
        self._check_loaded()
        self.models_dir.mkdir(exist_ok=True)

        self.model.save_model(self.models_dir / "xgboost_model.json")

        with open(self.models_dir / "shap_explainer.pkl", "wb") as f:
            pickle.dump(self.explainer, f)

        with open(self.models_dir / "feature_cols.json", "w") as f:
            json.dump(self.feature_cols, f)

        logger.info(f"Model saved to {self.models_dir}")

    def load(self) -> "FPLPredictor":
        """Load model, explainer and feature list from models_dir."""
        model_path     = self.models_dir / "xgboost_model.json"
        explainer_path = self.models_dir / "shap_explainer.pkl"
        cols_path      = self.models_dir / "feature_cols.json"

        if not model_path.exists():
            raise FileNotFoundError(
                f"Model not found at {model_path}. Run notebook 04 first."
            )

        import xgboost as xgb  # noqa: PLC0415
        self.model = xgb.XGBRegressor()
        self.model.load_model(model_path)

        with open(explainer_path, "rb") as f:
            self.explainer = pickle.load(f)

        with open(cols_path) as f:
            self.feature_cols = json.load(f)

        logger.info("Model loaded.")
        return self

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_loaded(self) -> None:
        if self.model is None or self.feature_cols is None:
            raise RuntimeError("Model not loaded. Call .load() or .train() first.")

    def _load_feature_cols(self) -> list[str]:
        cols_path = self.models_dir / "feature_cols.json"
        if cols_path.exists():
            with open(cols_path) as f:
                return json.load(f)
        # Fallback to hardcoded list if file not yet created
        return [
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
        ]

    def _load_best_params(self) -> dict:
        params_path = self.models_dir / "best_params.json"
        if params_path.exists():
            with open(params_path) as f:
                logger.info("Loaded hyperparameters from best_params.json")
                return json.load(f)
        return {}  # use XGBRegressor defaults defined in train()
