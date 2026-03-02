from __future__ import annotations

from typing import Protocol


class LLMProvider(Protocol):
    name: str
    model: str

    def generate(self, prompt: str) -> str:
        ...

