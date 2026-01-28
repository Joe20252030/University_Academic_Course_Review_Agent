from __future__ import annotations


class UACRAgentError(Exception):
	"""Base exception for expected, user-facing failures."""


class ConfigurationError(UACRAgentError):
	"""Raised when required configuration (env vars, paths) is missing/invalid."""


class IngestError(UACRAgentError):
	"""Raised when document loading/chunking fails."""


class LLMError(UACRAgentError):
	"""Raised when an LLM call fails in a recoverable/user-facing way."""


class ParseError(UACRAgentError):
	"""Raised when structured outputs cannot be parsed/validated."""
