"""Warlock Summoner build formula.

The summoner playstyle derives most of its power from demon skill levels,
support curses, and breakpoint-driven repositioning rather than weapon damage.
This formula therefore scores:

- summon scaling from ``all_skills``, ``demon_skills``, and summon-specific bonuses
- Magic Find on the standard D2R diminishing-returns curve
- survivability from life, mana buffer, resistances, and ``cannot_be_frozen``
- breakpoint attainment with a primary focus on the 75% FCR target

Sources: Maxroll Summoner Warlock guide (Season 13, updated 2026-02-19),
plus repo-local stat conventions.
"""

from __future__ import annotations

from d2r_optimiser.core.formula.common import effective_mf, lookup_breakpoint
from d2r_optimiser.core.models import BuildDefinition, ScoreBreakdown

_BASE_LIFE = 55.0
_LIFE_PER_LEVEL = 2.0
_LIFE_PER_VIT = 3.0
_BASE_VITALITY = 25.0
_BASE_LEVEL = 99.0
_BO_LIFE_ESTIMATE = 0.25

_DR_CAP = 0.50
_RES_CAP = 75.0

_FCR_BP_WEIGHT = 0.60
_FHR_BP_WEIGHT = 0.10
_RES_BP_WEIGHT = 0.20
_CBF_BP_WEIGHT = 0.10


class SummonerFormula:
    """Summoner-focused scoring model for Warlock loadouts."""

    def __init__(self, breakpoints: dict | None = None) -> None:
        self._breakpoints = breakpoints or {}

    def compute_damage(self, stats: dict[str, float], build: BuildDefinition) -> float:
        """Estimate summon damage contribution from gear on a 0-1 scale."""
        baseline = self._summon_raw_damage({}, build)
        geared = self._summon_raw_damage(stats, build)
        bonus_damage = max(geared - baseline, 0.0)
        ceiling = 7000.0
        return min(bonus_damage / ceiling, 1.0)

    def compute_mf(self, stats: dict[str, float], build: BuildDefinition) -> float:
        """Score Magic Find using the unique-item diminishing-returns curve."""
        eff = effective_mf(stats.get("mf", 0.0))
        return eff["unique"] / 250.0

    def compute_ehp(self, stats: dict[str, float], build: BuildDefinition) -> float:
        """Estimate survivability with emphasis on resists and mobility safety."""
        vitality = stats.get("vitality", 0.0)
        flat_life = stats.get("life", 0.0)
        mana = stats.get("mana", 0.0)
        dr = stats.get("dr", 0.0)
        block = stats.get("increased_chance_of_blocking", 0.0)

        base_life = _BASE_LIFE + (_BASE_LEVEL * _LIFE_PER_LEVEL) + (_BASE_VITALITY * _LIFE_PER_VIT)
        gear_life = vitality * _LIFE_PER_VIT + flat_life
        total_life = (base_life + gear_life) * (1.0 + _BO_LIFE_ESTIMATE)
        mana_buffer = mana * 0.35

        effective_dr = min(dr / 100.0, _DR_CAP)
        dr_factor = 1.0 / (1.0 - effective_dr)

        avg_res = self._average_resistance(stats)
        res_factor = 0.55 + 0.45 * (avg_res / _RES_CAP)

        block_factor = 1.0 + min(block, 25.0) / 250.0
        cbf_factor = 1.08 if stats.get("cannot_be_frozen", 0.0) > 0 else 1.0

        raw_ehp = (total_life + mana_buffer) * dr_factor * res_factor * block_factor * cbf_factor
        ceiling = 3000.0
        return min(raw_ehp / ceiling, 1.0)

    def compute_breakpoint_score(
        self, stats: dict[str, float], build: BuildDefinition
    ) -> float:
        """Score breakpoint attainment for summoner QoL and safety."""
        fcr_score = self._breakpoint_attainment(stats, build, "fcr", _FCR_BP_WEIGHT)
        fhr_score = self._breakpoint_attainment(stats, build, "fhr", _FHR_BP_WEIGHT)
        res_score = min(self._average_resistance(stats) / _RES_CAP, 1.0) * _RES_BP_WEIGHT
        cbf_score = _CBF_BP_WEIGHT if stats.get("cannot_be_frozen", 0.0) > 0 else 0.0
        return fcr_score + fhr_score + res_score + cbf_score

    def score(self, stats: dict[str, float], build: BuildDefinition) -> ScoreBreakdown:
        """Return the full score breakdown for the given stats."""
        return ScoreBreakdown(
            damage=self.compute_damage(stats, build),
            magic_find=self.compute_mf(stats, build),
            effective_hp=self.compute_ehp(stats, build),
            breakpoint_score=self.compute_breakpoint_score(stats, build),
        )

    def _summon_raw_damage(self, stats: dict[str, float], build: BuildDefinition) -> float:
        """Approximate summon output before normalisation."""
        goatman_level = self._skill_level(stats, build, "summon_goatman")
        mastery_level = self._skill_level(stats, build, "demonic_mastery")
        bind_level = self._skill_level(stats, build, "bind_demon")
        death_mark_level = self._skill_level(stats, build, "death_mark")
        engorge_level = self._skill_level(stats, build, "engorge")

        all_skills = stats.get("all_skills", 0.0)
        demon_skills = stats.get("demon_skills", 0.0)
        fcr = stats.get("fcr", 0.0)

        flat_damage = 500.0 + (goatman_level * 28.0) + (all_skills * 16.0) + (demon_skills * 18.0)
        mastery_mult = 1.0 + (mastery_level * 0.028)
        bind_mult = 1.0 + (bind_level * 0.024)
        death_mark_mult = 1.0 + (death_mark_level * 0.020)
        engorge_mult = 1.0 + (engorge_level * 0.010)
        fcr_mult = 1.0 + max(self._fcr_speed_factor(fcr) - 1.0, 0.0) * 0.08

        return flat_damage * mastery_mult * bind_mult * death_mark_mult * engorge_mult * fcr_mult

    def _skill_level(
        self,
        stats: dict[str, float],
        build: BuildDefinition,
        skill_name: str,
    ) -> float:
        """Resolve a summon-related skill level from build investment and gear."""
        return (
            float(build.skill_points.get(skill_name, 0))
            + stats.get("all_skills", 0.0)
            + stats.get("demon_skills", 0.0)
            + stats.get(skill_name, 0.0)
        )

    def _average_resistance(self, stats: dict[str, float]) -> float:
        """Return capped average elemental resistance."""
        res_all = stats.get("resistance_all", 0.0)
        fire = min(stats.get("fire_res", 0.0) + res_all, _RES_CAP)
        cold = min(stats.get("cold_res", 0.0) + res_all, _RES_CAP)
        light = min(stats.get("light_res", 0.0) + res_all, _RES_CAP)
        poison = min(stats.get("poison_res", 0.0) + res_all, _RES_CAP)
        return max((fire + cold + light + poison) / 4.0, 0.0)

    def _fcr_speed_factor(self, fcr: float) -> float:
        """Translate FCR to a relative cast-speed multiplier."""
        fcr_table = self._breakpoints.get("fcr")
        if not fcr_table:
            return 1.0 + fcr / 300.0

        base_frames = fcr_table[0]["frames"]
        bp = lookup_breakpoint(fcr_table, fcr)
        actual_frames = bp["frames"]
        if actual_frames <= 0:
            return float(base_frames)
        return base_frames / actual_frames

    def _breakpoint_attainment(
        self,
        stats: dict[str, float],
        build: BuildDefinition,
        stat_name: str,
        weight: float,
    ) -> float:
        """Return weighted progress towards a breakpoint-oriented target."""
        target = 0.0
        for constraint in build.constraints:
            if constraint.stat == stat_name:
                target = constraint.value
                break

        actual = stats.get(stat_name, 0.0)

        if target <= 0:
            bp_table = self._breakpoints.get(stat_name)
            if bp_table:
                max_threshold = bp_table[-1]["threshold"]
                if max_threshold > 0:
                    return weight * min(actual / max_threshold, 1.0)
            return weight * (1.0 if actual > 0 else 0.0)

        return weight * min(actual / target, 1.0)
