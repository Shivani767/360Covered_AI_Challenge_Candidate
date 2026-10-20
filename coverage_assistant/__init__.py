"""AI Coverage Assistant - reliable, grounded coverage explanations.

Public API::

    from coverage_assistant import CoverageAssistant
    bot = CoverageAssistant(mode="offline")
    print(bot.answer("What is my deductible?", state))
"""
from .assistant import CoverageAssistant, TurnTrace
from .catalog import Catalog, CatalogError
from .llm import (
    MissingCredentialError,
    ProviderError,
    SpendCapError,
    build_provider,
)
from .state import NormalizedState, normalize_state, resolve_referent

__all__ = [
    "CoverageAssistant",
    "TurnTrace",
    "Catalog",
    "CatalogError",
    "NormalizedState",
    "normalize_state",
    "resolve_referent",
    "ProviderError",
    "MissingCredentialError",
    "SpendCapError",
    "build_provider",
]

__version__ = "1.0.0"
