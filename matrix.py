"""
matrix.py — Answer-profile generator based on the tendency matrix.

The generator follows the causal chain:
    age + income  →  invest_status  →  risk  →  drop_reaction  →  literacy

Usage
-----
    from matrix import AnswerGenerator
    gen = AnswerGenerator(config)
    profile = gen.generate()
    # → {"age": "18-24", "income": "801-1500", "invests": True,
    #     "first_invest": "one_to_three_years", "risk": "average",
    #     "drop_reaction": "hold", "literacy": "medium"}
"""

import random
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _weighted_choice(option_map: dict[str, int | float]) -> str:
    """Pick a key from a weight dict, skipping keys with zero weight."""
    keys = [k for k, w in option_map.items() if w > 0]
    weights = [option_map[k] for k in keys]
    return random.choices(keys, weights=weights, k=1)[0]


class AnswerGenerator:
    """
    Generates a single coherent answer profile that mirrors the internal
    logic of the 120 genuine responses.

    Parameters
    ----------
    config : dict
        Parsed content of config.yaml (full document).
    session_stats : dict, optional
        Running counters so constraints (e.g. neinvestuoju ceiling) can be
        enforced across submissions.  Shape: {"total": int, "neinvestuoju": int}
    """

    def __init__(self, config: dict[str, Any], session_stats: dict | None = None):
        self._config = config
        self._matrix = config["matrix"]
        self._constraints = config["constraints"]
        self._q = config["questions"]
        self._stats = session_stats or {"total": 0, "neinvestuoju": 0}

        # Build profile list with weights for sampling
        self._profiles = self._matrix
        self._profile_weights = [p["weight"] for p in self._profiles]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self) -> dict[str, str]:
        """
        Return a dict of answer keys:
            age, income, invests_now, first_invest,
            risk, drop_reaction, literacy
        """
        profile = self._pick_profile()
        invests = self._decide_invests(profile)
        first_invest = self._decide_first_invest(profile, invests)
        risk = self._decide_risk(profile, invests)
        drop = self._decide_drop_reaction(profile, invests, risk)
        literacy = self._decide_literacy(profile)

        answer = {
            "age":           profile["age_group"],
            "income":        profile["income_bracket"],
            "invests_now":   "yes" if invests else "no",
            "first_invest":  first_invest,
            "risk":          risk,
            "drop_reaction": drop,
            "literacy":      literacy,
            "_profile_id":   profile["id"],
            "_profile_label": profile["label"],
        }

        self._stats["total"] += 1
        if first_invest == "neinvestuoju":
            self._stats["neinvestuoju"] += 1

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Generated profile: %s", answer)

        return answer

    def stats(self) -> dict:
        """Return running session statistics."""
        return dict(self._stats)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pick_profile(self) -> dict:
        return random.choices(self._profiles, weights=self._profile_weights, k=1)[0]

    def _decide_invests(self, profile: dict) -> bool:
        return random.random() < profile["invest_prob"]

    def _decide_first_invest(self, profile: dict, invests: bool) -> str:
        """
        If the person does not currently invest AND the global neinvestuoju
        fraction is still below the ceiling, we may assign "neinvestuoju".
        Otherwise we fall back to one of the real time-range options.
        """
        if not invests:
            ceiling = self._constraints["neinvestuoju_max_fraction"]
            total = self._stats["total"] or 1  # avoid div/0 on first run
            current_fraction = self._stats["neinvestuoju"] / total
            if current_fraction < ceiling:
                # Randomly decide (50/50) whether to place neinvestuoju here
                if random.random() < 0.5:
                    return "neinvestuoju"
            # Non-investor but neinvestuoju quota full → pick earliest bracket
            weights = dict(profile["first_invest_options"])
            weights.pop("neinvestuoju", None)  # exclude if present
            return _weighted_choice(weights)

        # Currently invests → pick from time-range options (no neinvestuoju)
        weights = dict(profile["first_invest_options"])
        weights.pop("neinvestuoju", None)
        return _weighted_choice(weights)

    def _decide_risk(self, profile: dict, invests: bool) -> str:
        """
        Non-investors are nudged toward lower risk;
        investors may express their profile's full distribution.
        """
        weights = dict(profile["risk_options"])

        if not invests:
            # Boost no_risk and below_average for non-investors
            weights["no_risk"] = weights.get("no_risk", 0) * 1.5 + 1
            weights["high"] = max(0.0, weights.get("high", 0) - 1)

        return _weighted_choice(weights)

    def _decide_drop_reaction(self, profile: dict, invests: bool, risk: str) -> str:
        """
        Investors + higher risk → tilt toward buy_more.
        Non-investors + no_risk  → tilt toward hold/sell.
        """
        weights = dict(profile["drop_options"])

        if invests and risk in ("above_average", "high"):
            weights["buy_more"] = weights.get("buy_more", 0) * 1.5 + 1
            weights["sell_all"] = max(0.0, weights.get("sell_all", 0) - 1)
        elif not invests and risk in ("no_risk", "below_average"):
            weights["hold"] = weights.get("hold", 0) * 1.3 + 1
            weights["sell_some"] = weights.get("sell_some", 0) * 1.2
            weights["buy_more"] = max(0.0, weights.get("buy_more", 0) - 2)

        return _weighted_choice(weights)

    def _decide_literacy(self, profile: dict) -> str:
        """
        Add ±jitter noise to the mean literacy score, then bucket into
        low / medium / high.
        """
        lit_cfg = self._q["literacy"]
        jitter = lit_cfg.get("literacy_jitter", 0.25)
        mean = profile["literacy_mean"]
        score = mean + random.uniform(-jitter * mean, jitter * mean)
        score = max(1.0, min(3.0, score))

        medium_min = lit_cfg["score_thresholds"]["medium_min"]
        high_min = lit_cfg["score_thresholds"]["high_min"]

        if score >= high_min:
            return "high"
        if score >= medium_min:
            return "medium"
        return "low"
