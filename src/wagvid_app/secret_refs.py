"""Resolve credential references without persisting plaintext secret values."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping


class SecretReferenceError(ValueError):
    pass


class EnvironmentSecretResolver:
    def __init__(self, environment: Mapping[str, str] | None = None):
        self.environment = environment if environment is not None else os.environ

    def resolve(self, reference: str) -> str:
        if not reference.startswith("env:"):
            raise SecretReferenceError(
                "Only env: references are available; configure a vault adapter for other schemes"
            )
        name = reference.removeprefix("env:")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,127}", name):
            raise SecretReferenceError("invalid environment secret reference")
        value = self.environment.get(name, "")
        if not value:
            raise SecretReferenceError(f"secret reference is unavailable: env:{name}")
        return value
