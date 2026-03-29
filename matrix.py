"""
matrix.py — Answer-profile generator based on the tendency matrix.

The generator follows the causal chain:
    age + income  →  education + employment  →  invest_status
    →  first_invest  →  risk  →  risk_agreement  →  drop_reaction
    →  financial literacy quiz  →  social trust  →  financial trust
    →  happiness  →  life satisfaction

Usage
-----
    from matrix import AnswerGenerator
    gen = AnswerGenerator(config)
    profile = gen.generate()
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


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _jittered_int(mean: float, lo: int, hi: int, jitter_frac: float = 0.30) -> str:
    """Return a string integer drawn from mean ± jitter, clamped to [lo, hi]."""
    spread = max((hi - lo) * jitter_frac, 1.0)
    raw = random.gauss(mean, spread)
    return str(int(round(_clamp(raw, lo, hi))))


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
        Return a dict of answer keys covering all 21 form questions.
        Gender is pre-set as a hidden field and excluded from the profile.
        """
        profile = self._pick_profile()
        education = self._decide_education(profile)
        employment = self._decide_employment(profile)
        invests = self._decide_invests(profile)
        first_invest = self._decide_first_invest(profile, invests)
        risk = self._decide_risk(profile, invests)
        risk_agreement = self._decide_risk_agreement(profile, risk)
        drop = self._decide_drop_reaction(profile, invests, risk)
        fl_q1 = self._decide_fin_literacy_q1(profile)
        fl_q2 = self._decide_fin_literacy_q2(profile)
        fl_q3 = self._decide_fin_literacy_q3(profile)
        st_q1, st_q2, st_q3 = self._decide_social_trust(profile)
        ft_q1, ft_q2, ft_q3 = self._decide_fin_trust(profile)
        happiness = self._decide_happiness(profile)
        life_sat = self._decide_life_satisfaction(profile)

        answer = {
            "age":              profile["age_group"],
            "education":        education,
            "employment":       employment,
            "income":           profile["income_bracket"],
            "fin_literacy_q1":  fl_q1,
            "fin_literacy_q2":  fl_q2,
            "fin_literacy_q3":  fl_q3,
            "invests_now":      "yes" if invests else "no",
            "first_invest":     first_invest,
            "risk":             risk,
            "risk_agreement":   risk_agreement,
            "drop_reaction":    drop,
            "social_trust_q1":  st_q1,
            "social_trust_q2":  st_q2,
            "social_trust_q3":  st_q3,
            "fin_trust_q1":     ft_q1,
            "fin_trust_q2":     ft_q2,
            "fin_trust_q3":     ft_q3,
            "happiness":        happiness,
            "life_satisfaction": life_sat,
            "_profile_id":      profile["id"],
            "_profile_label":   profile["label"],
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

    def _decide_education(self, profile: dict) -> str:
        return _weighted_choice(profile["education_options"])

    def _decide_employment(self, profile: dict) -> str:
        return _weighted_choice(profile["employment_options"])

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
                if random.random() < 0.5:
                    return "neinvestuoju"
            weights = dict(profile["first_invest_options"])
            weights.pop("neinvestuoju", None)
            return _weighted_choice(weights)

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
            weights["no_risk"] = weights.get("no_risk", 0) * 1.5 + 1
            weights["high"] = max(0.0, weights.get("high", 0) - 1)

        return _weighted_choice(weights)

    def _decide_risk_agreement(self, profile: dict, risk: str) -> str:
        """
        Likert agreement with risk-taking, correlated with risk level.
        Higher risk tolerance nudges toward agreement; lower toward disagreement.
        """
        weights = dict(profile["risk_agreement_options"])

        if risk == "high":
            weights["visiskai_sutinku"] = weights.get("visiskai_sutinku", 0) * 2 + 1
            weights["sutinku"] = weights.get("sutinku", 0) * 1.5 + 1
        elif risk == "above_average":
            weights["sutinku"] = weights.get("sutinku", 0) * 1.3 + 1
        elif risk == "no_risk":
            weights["visiskai_nesutinku"] = weights.get("visiskai_nesutinku", 0) * 2 + 1
            weights["nesutinku"] = weights.get("nesutinku", 0) * 1.5 + 1

        return _weighted_choice(weights)

    def _decide_drop_reaction(self, profile: dict, invests: bool, risk: str) -> str:
        """
        Investors + higher risk → tilt toward buy_more.
        Non-investors + no_risk → tilt toward hold/sell.
        """
        weights = dict(profile["drop_options"])

        if invests and risk in ("above_average", "high"):
            weights["buy_more"] = weights.get("buy_more", 0) * 1.5 + 1
            weights["sell"] = max(0.0, weights.get("sell", 0) - 1)
        elif not invests and risk == "no_risk":
            weights["hold"] = weights.get("hold", 0) * 1.3 + 1
            weights["sell"] = weights.get("sell", 0) * 1.2
            weights["buy_more"] = max(0.0, weights.get("buy_more", 0) - 2)

        return _weighted_choice(weights)

    # -- Financial literacy quiz questions --

    def _decide_fin_literacy_q1(self, profile: dict) -> str:
        """Inflation question. Correct: maziau. Higher literacy → more correct."""
        return self._literacy_quiz_pick(
            profile, correct="maziau",
            wrong_options=["daugiau", "tiek_pat", "nezinau"],
        )

    def _decide_fin_literacy_q2(self, profile: dict) -> str:
        """Investment fund question. Correct: neteisingas."""
        return self._literacy_quiz_pick(
            profile, correct="neteisingas",
            wrong_options=["teisingas", "nezinau"],
        )

    def _decide_fin_literacy_q3(self, profile: dict) -> str:
        """Compound interest question. Correct: daugiau."""
        return self._literacy_quiz_pick(
            profile, correct="daugiau",
            wrong_options=["lygiai", "maziau", "nezinau"],
        )

    def _literacy_quiz_pick(
        self, profile: dict, correct: str, wrong_options: list[str],
    ) -> str:
        """
        Pick a quiz answer weighted by literacy_mean.
        literacy_mean is on a 1–3 scale; higher → more likely correct.
        """
        jitter = self._q.get("literacy_jitter", 0.25)
        mean = profile["literacy_mean"]
        score = mean + random.uniform(-jitter * mean, jitter * mean)
        score = _clamp(score, 1.0, 3.0)

        # Map score to probability of correct answer: 1→0.25, 3→0.90
        p_correct = 0.25 + (score - 1.0) * (0.65 / 2.0)

        if random.random() < p_correct:
            return correct

        # Wrong answer: split evenly among wrong options
        return random.choice(wrong_options)

    # -- Social trust (three questions, linear scale 0-10) --

    def _decide_social_trust(self, profile: dict) -> tuple[str, str, str]:
        mean = profile["social_trust_mean"]
        return (
            _jittered_int(mean, 0, 10),
            _jittered_int(mean, 0, 10),
            _jittered_int(mean, 0, 10),
        )

    # -- Financial trust (three questions, linear scale 1-5) --

    def _decide_fin_trust(self, profile: dict) -> tuple[str, str, str]:
        mean = profile["fin_trust_mean"]
        return (
            _jittered_int(mean, 1, 5, jitter_frac=0.25),
            _jittered_int(mean, 1, 5, jitter_frac=0.25),
            _jittered_int(mean, 1, 5, jitter_frac=0.25),
        )

    # -- Happiness (linear scale 0-10) --

    def _decide_happiness(self, profile: dict) -> str:
        return _jittered_int(profile["happiness_mean"], 0, 10)

    # -- Life satisfaction (linear scale 0-10) --

    def _decide_life_satisfaction(self, profile: dict) -> str:
        return _jittered_int(profile["life_satisfaction_mean"], 0, 10)
