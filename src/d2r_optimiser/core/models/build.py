"""Build definition models (loaded from YAML, not DB-persisted)."""

from pydantic import BaseModel, model_validator


class ObjectiveWeights(BaseModel):
    """Weights for scoring dimensions. Must sum to ~1.0."""

    damage: float = 0.4
    magic_find: float = 0.4
    effective_hp: float = 0.15
    breakpoint_score: float = 0.05

    @model_validator(mode="after")
    def _check_weights_sum(self) -> "ObjectiveWeights":
        total = self.damage + self.magic_find + self.effective_hp + self.breakpoint_score
        if not (0.99 <= total <= 1.01):
            msg = f"Objective weights must sum to 1.0, got {total:.4f}"
            raise ValueError(msg)
        return self


class Constraint(BaseModel):
    """A hard constraint that must be met."""

    stat: str  # "fcr" / "resistance_all" / "strength"
    operator: str  # ">=" / "<=" / "=="
    value: float


class BuildDefinition(BaseModel):
    """A build target loaded from YAML."""

    name: str
    display_name: str
    character_class: str  # "warlock"
    description: str
    formula_module: str  # "warlock_echoing_strike" — maps to formula class
    skill_points: dict[str, int]  # skill_name -> points
    objectives: ObjectiveWeights
    constraints: list[Constraint]
    presets: dict[str, ObjectiveWeights]  # "mf" / "dps" / "balanced" preset overrides
    reference_loadouts: list[dict] | None = None  # for validation
