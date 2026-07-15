"""Runtime configuration for the single-expert ACLF pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ACLFConfig:
    max_tool_rounds: int = 7
    max_retries: int = 3
    temperature: float = 0.3
    top_p: float = 0.9
    reasoning_effort: str = "medium"
    gather_max_tokens: int = 4096
    assess_max_tokens: int = 16384
    concurrency: int = 4

    def __post_init__(self) -> None:
        if self.max_tool_rounds < 0:
            raise ValueError("max_tool_rounds must be >= 0")
        if self.max_retries < 1:
            raise ValueError("max_retries must be >= 1")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be in [0, 2]")
        if not 0 < self.top_p <= 1:
            raise ValueError("top_p must be in (0, 1]")
        if self.gather_max_tokens < 1 or self.assess_max_tokens < 1:
            raise ValueError("token budgets must be positive")
        if self.concurrency < 1:
            raise ValueError("concurrency must be >= 1")


__all__ = ["ACLFConfig"]
