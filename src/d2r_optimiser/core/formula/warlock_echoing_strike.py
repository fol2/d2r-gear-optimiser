"""Warlock Echoing Strike MF build formula.

Implements the BuildFormula protocol via structural typing (no inheritance needed).

Damage model (simplified for V1):
- Echoing Strike scales with weapon damage + skill level + synergies
- Physical + Magic dual damage split
- Weapon ED (enhanced damage) is the primary scaling stat
- FCR affects cast speed (more casts per second = more DPS)

Sources: Maxroll Echoing Strike guide, community testing (Season 13, 2026).
"""

from __future__ import annotations

from d2r_optimiser.core.formula.common import effective_mf, lookup_breakpoint
from d2r_optimiser.core.models import BuildDefinition, ScoreBreakdown

# ─── Constants ──────────────────────────────────────────────────────────────

# Base damage range for a level 20 Echoing Strike with decent weapon
# V1 approximation — calibrate via live validation
_BASE_DAMAGE_MIN = 80.0
_BASE_DAMAGE_MAX = 200.0

# Warlock base stats at level 99 (no gear)
_BASE_LIFE = 55  # Starting life
_LIFE_PER_LEVEL = 2.0  # Life gained per character level
_LIFE_PER_VIT = 3.0  # Life per point of vitality (Warlock estimate)
_BASE_VITALITY = 25  # Starting vitality
_BASE_LEVEL = 99
_BO_LIFE_ESTIMATE = 0.35  # Battle Orders adds ~35% life (typical party buff)

# DR cap in D2R is 50% physical damage reduction
_DR_CAP = 0.50

# Resistance cap in Hell difficulty
_RES_CAP = 75.0

# Breakpoint scoring weights
_FCR_BP_WEIGHT = 0.70  # Most important for Echoing Strike cast speed
_FHR_BP_WEIGHT = 0.20  # Hit recovery matters for survivability
_RES_BP_WEIGHT = 0.10  # Resistance cap attainment


class EchoingStrikeFormula:
    """Warlock Echoing Strike MF build formula.

    Implements BuildFormula protocol (structural typing, no inheritance needed).
    All ``compute_*`` methods accept pre-aggregated ``stats: dict[str, float]``
    — the search engine sums all item stats before calling the formula.
    """

    def __init__(self, breakpoints: dict | None = None) -> None:
        """Initialise with optional breakpoint data.

        *breakpoints*: the warlock section from ``data/breakpoints.yaml``,
        e.g. ``{"fcr": [...], "fhr": [...]}``.
        """
        self._breakpoints = breakpoints or {}

    # ── Damage ──────────────────────────────────────────────────────────────

    def compute_damage(self, stats: dict[str, float], build: BuildDefinition) -> float:
        """Estimate relative damage output (normalised 0-1 scale).

        Key stats consumed:
        - ``ed``: enhanced damage %
        - ``all_skills``: +to all skills
        - ``damage_min`` / ``damage_max``: flat added damage
        - ``ds``: deadly strike %
        - ``cb``: crushing blow %
        - ``fcr``: faster cast rate (affects frames via breakpoint)

        Formula (V1 approximation):
            avg_damage = (base_min + damage_min + base_max + damage_max) / 2
            ed_mult    = 1 + ed / 100
            skill_mult = 1 + all_skills * 0.10   # ~10% more damage per +skill level
            fcr_mult   = base_frames / actual_frames  # faster casting = more DPS
            ds_mult    = 1 + ds / 200             # deadly strike ~ 50% value of crit
            raw        = avg_damage * ed_mult * skill_mult * fcr_mult * ds_mult

        The result is normalised against a reference ceiling so it falls
        roughly in [0, 1] for typical gear.
        """
        damage_min = stats.get("damage_min", 0.0)
        damage_max = stats.get("damage_max", 0.0)
        ed = stats.get("ed", 0.0)
        all_skills = stats.get("all_skills", 0.0)
        ds = stats.get("ds", 0.0)
        fcr = stats.get("fcr", 0.0)

        avg_damage = (_BASE_DAMAGE_MIN + damage_min + _BASE_DAMAGE_MAX + damage_max) / 2.0
        ed_mult = 1.0 + ed / 100.0
        # V1 approximation — calibrate via live validation
        skill_mult = 1.0 + all_skills * 0.10
        ds_mult = 1.0 + ds / 200.0

        # FCR multiplier: fewer frames = more casts per second
        fcr_mult = self._fcr_speed_factor(fcr)

        raw = avg_damage * ed_mult * skill_mult * fcr_mult * ds_mult

        # Normalise against a reference ceiling (high-end gear produces ~3000-5000)
        # V1 approximation — calibrate via live validation
        ceiling = 5000.0
        return min(raw / ceiling, 1.0)

    # ── Magic Find ──────────────────────────────────────────────────────────

    def compute_mf(self, stats: dict[str, float], build: BuildDefinition) -> float:
        """Score MF using effective_mf() diminishing returns curve.

        Weight unique-find MF highest since that is the primary farming goal.
        Score = effective_mf["unique"] / 250  (normalised to 0-1 range; 250 is
        the theoretical asymptote for unique find chance).
        """
        raw_mf = stats.get("mf", 0.0)
        eff = effective_mf(raw_mf)
        # Unique find rate is the bottleneck — use it as the score basis
        return eff["unique"] / 250.0

    # ── Effective HP ────────────────────────────────────────────────────────

    def compute_ehp(self, stats: dict[str, float], build: BuildDefinition) -> float:
        """Effective HP = life * damage_reduction_factor * resistance_factor.

        Life pool:
            base_life (at level 99) + vitality * life_per_vit + flat_life + BO estimate

        Damage reduction:
            1 / (1 - min(dr/100, 0.50))   — DR capped at 50%

        Resistance factor:
            average(min(res, 75) for each resistance) / 75

        Normalised against a reference ceiling for 0-1 range.
        """
        vitality = stats.get("vitality", 0.0)
        flat_life = stats.get("life", 0.0)
        dr = stats.get("dr", 0.0)

        # Life pool
        base_life = _BASE_LIFE + (_BASE_LEVEL * _LIFE_PER_LEVEL) + (_BASE_VITALITY * _LIFE_PER_VIT)
        gear_life = vitality * _LIFE_PER_VIT + flat_life
        total_life = (base_life + gear_life) * (1.0 + _BO_LIFE_ESTIMATE)

        # Damage reduction factor (physical)
        effective_dr = min(dr / 100.0, _DR_CAP)
        dr_factor = 1.0 / (1.0 - effective_dr)

        # Resistance factor (elemental survivability)
        fire = min(stats.get("fire_res", 0.0) + stats.get("resistance_all", 0.0), _RES_CAP)
        cold = min(stats.get("cold_res", 0.0) + stats.get("resistance_all", 0.0), _RES_CAP)
        light = min(stats.get("light_res", 0.0) + stats.get("resistance_all", 0.0), _RES_CAP)
        poison = min(stats.get("poison_res", 0.0) + stats.get("resistance_all", 0.0), _RES_CAP)
        avg_res = (fire + cold + light + poison) / 4.0
        res_factor = max(avg_res, 0.0) / _RES_CAP

        raw_ehp = total_life * dr_factor * (0.5 + 0.5 * res_factor)

        # Normalise against a reference ceiling
        # Well-geared character: ~2500 life * 2.0 DR * 1.0 res ~ 5000
        # V1 approximation — calibrate via live validation
        ceiling = 5000.0
        return min(raw_ehp / ceiling, 1.0)

    # ── Breakpoint Score ────────────────────────────────────────────────────

    def compute_breakpoint_score(
        self, stats: dict[str, float], build: BuildDefinition
    ) -> float:
        """Score breakpoint attainment on a 0-1 scale.

        Weights:
        - FCR: 0.70 (most important for Echoing Strike cast speed)
        - FHR: 0.20 (hit recovery for survivability)
        - Resistance cap: 0.10 (all-res >= 75 target)

        Each component scores 1.0 if the build's constraint is met or exceeded,
        with partial credit for proximity.
        """
        fcr_score = self._breakpoint_attainment(stats, build, "fcr", _FCR_BP_WEIGHT)
        fhr_score = self._breakpoint_attainment(stats, build, "fhr", _FHR_BP_WEIGHT)

        # Resistance cap attainment
        res_all = stats.get("resistance_all", 0.0)
        res_score = min(res_all / _RES_CAP, 1.0) * _RES_BP_WEIGHT

        return fcr_score + fhr_score + res_score

    # ── Combined Score ──────────────────────────────────────────────────────

    def score(self, stats: dict[str, float], build: BuildDefinition) -> ScoreBreakdown:
        """Compute all dimensions and return a ScoreBreakdown."""
        return ScoreBreakdown(
            damage=self.compute_damage(stats, build),
            magic_find=self.compute_mf(stats, build),
            effective_hp=self.compute_ehp(stats, build),
            breakpoint_score=self.compute_breakpoint_score(stats, build),
        )

    # ── Private helpers ─────────────────────────────────────────────────────

    def _fcr_speed_factor(self, fcr: float) -> float:
        """Compute the relative cast-speed multiplier from FCR breakpoints.

        Returns ``base_frames / actual_frames`` so that hitting a faster
        breakpoint yields a proportionally higher multiplier (>1.0).
        Falls back to a linear approximation if no breakpoint data is loaded.
        """
        fcr_table = self._breakpoints.get("fcr")
        if not fcr_table:
            # Fallback: linear scaling 1.0 at 0 FCR, ~1.67 at 200 FCR
            # V1 approximation — calibrate via live validation
            return 1.0 + fcr / 300.0

        base_frames = fcr_table[0]["frames"]  # slowest (0% FCR)
        bp = lookup_breakpoint(fcr_table, fcr)
        actual_frames = bp["frames"]
        if actual_frames <= 0:
            return float(base_frames)  # safety guard
        return base_frames / actual_frames

    def _breakpoint_attainment(
        self,
        stats: dict[str, float],
        build: BuildDefinition,
        stat_name: str,
        weight: float,
    ) -> float:
        """Score how close we are to the build's constraint for *stat_name*.

        Returns weighted score: ``weight * attainment`` where attainment is
        1.0 if the constraint is met, otherwise ``actual / target`` clamped to [0, 1].
        """
        # Find the constraint target for this stat
        target = 0.0
        for c in build.constraints:
            if c.stat == stat_name:
                target = c.value
                break

        actual = stats.get(stat_name, 0.0)

        if target <= 0:
            # No constraint set for this stat — check breakpoint progression instead
            bp_table = self._breakpoints.get(stat_name)
            if bp_table:
                max_threshold = bp_table[-1]["threshold"]
                if max_threshold > 0:
                    return weight * min(actual / max_threshold, 1.0)
            return weight * (1.0 if actual > 0 else 0.0)

        attainment = min(actual / target, 1.0) if target > 0 else 1.0
        return weight * attainment
