"""Versioned council profiles and hierarchical specialist routing."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kalshi_bot.agents.contracts import AgentRole, RoleCriticality

Transport = Literal["in_process", "a2a"]
Provider = Literal["openai", "anthropic", "ollama", "a2a"]
ProfileLifecycle = Literal[
    "disabled", "fixture", "replay", "shadow", "paper_advisory", "paper_council"
]

REQUIRED_ROLES: frozenset[AgentRole] = frozenset(
    {
        "researcher",
        "bull_thesis",
        "bear_thesis",
        "skeptic",
        "execution_liquidity",
        "rules_settlement",
        "portfolio_risk",
        "master_synthesizer",
    }
)


class ModelAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    provider: Provider
    model: str = Field(min_length=1)
    enabled: bool = True


class RoleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    role: AgentRole
    criticality: RoleCriticality
    model: ModelAssignment
    timeout_seconds: float = Field(gt=0, le=300)
    max_output_tokens: int = Field(gt=0, le=128_000)
    max_cost_usd: float = Field(ge=0, le=100)
    allow_price_ceiling: bool = False
    allow_size_ceiling: bool = False


class CouncilBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_timeout_seconds: float = Field(gt=0, le=900)
    total_output_tokens: int = Field(gt=0, le=1_000_000)
    total_cost_usd: float = Field(ge=0, le=500)
    max_concurrency: int = Field(gt=0, le=32)
    max_reconsideration_rounds: int = Field(ge=0, le=1)
    max_format_retries: int = Field(ge=0, le=1)


class CouncilProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    profile_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    domain: Literal["prediction", "perp", "sports"]
    specialization_pattern: str = Field(min_length=1)
    lifecycle: ProfileLifecycle = "disabled"
    transport: Transport = "in_process"
    a2a_agent_card_uri: str | None = Field(default=None, min_length=1)
    roles: tuple[RoleConfig, ...] = ()
    budget: CouncilBudget
    allow_paper_influence: bool = False

    @model_validator(mode="after")
    def _validate_profile(self) -> CouncilProfile:
        role_names = [role.role for role in self.roles]
        if len(role_names) != len(set(role_names)):
            raise ValueError("council roles must be unique")
        missing = REQUIRED_ROLES.difference(role_names)
        if missing:
            raise ValueError(f"profile is missing required roles: {sorted(missing)}")
        if self.transport == "a2a" and not self.a2a_agent_card_uri:
            raise ValueError("A2A profiles require an Agent Card URI")
        if self.lifecycle not in {"paper_advisory", "paper_council"} and self.allow_paper_influence:
            raise ValueError("paper influence is only valid for a paper lifecycle")
        return self

    def matches(self, specialization_key: str) -> bool:
        expected = self.specialization_pattern.strip("/").split("/")
        actual = specialization_key.strip("/").split("/")
        if len(expected) != len(actual):
            return False
        return all(
            pattern == "*" or pattern == value
            for pattern, value in zip(expected, actual, strict=True)
        )

    @property
    def specificity(self) -> int:
        return sum(segment != "*" for segment in self.specialization_pattern.strip("/").split("/"))


def _default_roles() -> tuple[RoleConfig, ...]:
    models: dict[AgentRole, ModelAssignment] = {
        "researcher": ModelAssignment(provider="openai", model="gpt-6-astra"),
        "bull_thesis": ModelAssignment(provider="openai", model="gpt-5.6-terra"),
        "bear_thesis": ModelAssignment(provider="openai", model="gpt-5.6-terra"),
        "skeptic": ModelAssignment(provider="openai", model="gpt-5.6-terra"),
        "execution_liquidity": ModelAssignment(provider="openai", model="gpt-5.6-terra"),
        "rules_settlement": ModelAssignment(provider="openai", model="gpt-5.6-terra"),
        "portfolio_risk": ModelAssignment(provider="openai", model="gpt-5.6-terra"),
        "master_synthesizer": ModelAssignment(provider="openai", model="gpt-6-astra"),
    }
    critical = {"execution_liquidity", "rules_settlement", "portfolio_risk", "master_synthesizer"}
    return tuple(
        RoleConfig(
            role=role,
            criticality="critical" if role in critical else "advisory",
            model=model,
            timeout_seconds=20 if role != "master_synthesizer" else 45,
            max_output_tokens=1_500 if role != "master_synthesizer" else 3_000,
            max_cost_usd=0.25 if role != "master_synthesizer" else 1.0,
            allow_price_ceiling=role == "master_synthesizer",
            allow_size_ceiling=role
            in {"execution_liquidity", "portfolio_risk", "master_synthesizer"},
        )
        for role, model in models.items()
    )


_DEFAULT_BUDGET = CouncilBudget(
    total_timeout_seconds=90,
    total_output_tokens=16_000,
    total_cost_usd=3.0,
    max_concurrency=8,
    max_reconsideration_rounds=1,
    max_format_retries=1,
)

DEFAULT_COUNCIL_PROFILES: tuple[CouncilProfile, ...] = (
    CouncilProfile(
        profile_id="prediction-btc-15m",
        version="1",
        domain="prediction",
        specialization_pattern="prediction/BTC/15m",
        roles=_default_roles(),
        budget=_DEFAULT_BUDGET,
    ),
    CouncilProfile(
        profile_id="prediction-crypto-cadence",
        version="1",
        domain="prediction",
        specialization_pattern="prediction/*/*",
        roles=_default_roles(),
        budget=_DEFAULT_BUDGET,
    ),
    CouncilProfile(
        profile_id="perp-crypto-directional",
        version="1",
        domain="perp",
        specialization_pattern="perp/*/directional",
        roles=_default_roles(),
        budget=_DEFAULT_BUDGET,
    ),
    CouncilProfile(
        profile_id="perp-btc-directional",
        version="1",
        domain="perp",
        specialization_pattern="perp/BTC/directional",
        roles=_default_roles(),
        budget=_DEFAULT_BUDGET,
    ),
    CouncilProfile(
        profile_id="perp-btc-funding-carry",
        version="1",
        domain="perp",
        specialization_pattern="perp/BTC/funding-carry",
        roles=_default_roles(),
        budget=_DEFAULT_BUDGET,
    ),
    CouncilProfile(
        profile_id="sports-market-class",
        version="1",
        domain="sports",
        specialization_pattern="sports/*/*/*",
        roles=_default_roles(),
        budget=_DEFAULT_BUDGET,
    ),
)


def resolve_profile(
    specialization_key: str,
    profiles: tuple[CouncilProfile, ...] = DEFAULT_COUNCIL_PROFILES,
) -> CouncilProfile | None:
    """Choose the most specific compatible profile; exact wins over wildcard."""

    matches = [profile for profile in profiles if profile.matches(specialization_key)]
    if not matches:
        return None
    return max(matches, key=lambda profile: (profile.specificity, profile.profile_id))


__all__ = [
    "DEFAULT_COUNCIL_PROFILES",
    "REQUIRED_ROLES",
    "CouncilBudget",
    "CouncilProfile",
    "ModelAssignment",
    "ProfileLifecycle",
    "RoleConfig",
    "resolve_profile",
]
