"""Public ForgeTrace package.

The implementation remains in the ``pico`` package for backward compatibility
with existing sessions and integrations. New applications should import from
``forgetrace``.
"""

from pico import (
    AnthropicCompatibleModelClient,
    FakeModelClient,
    OllamaModelClient,
    OpenAICompatibleModelClient,
    RepoIndex,
    ForgeTrace,
    SessionStore,
    WorkspaceContext,
    build_agent,
    build_arg_parser,
    build_welcome,
    main,
)

__all__ = [
    "AnthropicCompatibleModelClient",
    "FakeModelClient",
    "OllamaModelClient",
    "OpenAICompatibleModelClient",
    "RepoIndex",
    "ForgeTrace",
    "SessionStore",
    "WorkspaceContext",
    "build_agent",
    "build_arg_parser",
    "build_welcome",
    "main",
]
