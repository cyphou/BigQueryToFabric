"""Credential detection and redaction for safe persistence of migration records."""

import re
from dataclasses import dataclass
from typing import ClassVar


@dataclass
class CredentialFinding:
    """A detected credential or secret pattern."""

    pattern: str
    finding_type: str
    severity: str = "HIGH"


class CredentialScanner:
    """Detects and redacts credentials before artifact serialization."""

    # Patterns for common credential types
    PATTERNS: ClassVar[dict[str, re.Pattern[str]]] = {
        "private_key": re.compile(
            r"-----BEGIN (PRIVATE KEY|RSA PRIVATE KEY|EC PRIVATE KEY)-----.*?-----END \1-----",
            re.DOTALL | re.IGNORECASE,
        ),
        "api_key": re.compile(
            r'(?:api[_-]?key|apikey|sk-)["\']?([a-zA-Z0-9_\-]{8,})["\'"]?',
            re.IGNORECASE,
        ),
        "service_account_path": re.compile(
            r'(?:GOOGLE_APPLICATION_CREDENTIALS|service[_-]?account|gcp[_-]?sa)["\']?[=:]\s*["\']?([^\s"\']+\.json)["\']?|[A-Za-z]:[\\/][^\s"\']*(?:service[_-]?account|gcp[_-]?sa|credentials?)[^\s"\']*\.json',
            re.IGNORECASE,
        ),
        "connection_string": re.compile(
            r"(?:postgresql|mysql|mssql|oracle)://[^\s]+:[^\s@]+@[^\s\"\']",
            re.IGNORECASE,
        ),
        "oauth_token": re.compile(
            r'(?:access_token|oauth_token|bearer)["\']?[=:]\s*["\']?([a-zA-Z0-9_\-\.]+)["\']?',
            re.IGNORECASE,
        ),
        "aws_key": re.compile(
            r"(?:AKIA[0-9A-Z]{16})",
        ),
    }

    def scan(self, text: str) -> list[CredentialFinding]:
        """Scan text for credential patterns."""
        findings = []

        for finding_type, pattern in self.PATTERNS.items():
            matches = pattern.finditer(text)
            for match in matches:
                findings.append(
                    CredentialFinding(
                        pattern=match.group(0),
                        finding_type=finding_type,
                        severity="HIGH",
                    )
                )

        return findings

    def redact(self, text: str) -> str:
        """Redact all detected credentials from text."""
        result = text

        # Redact private keys
        result = self.PATTERNS["private_key"].sub(
            "[REDACTED_PRIVATE_KEY]", result
        )

        # Redact API keys
        result = self.PATTERNS["api_key"].sub(
            "[REDACTED_API_KEY]", result
        )

        # Redact service account paths
        result = self.PATTERNS["service_account_path"].sub(
            "[REDACTED_SERVICE_ACCOUNT_PATH]", result
        )

        # Redact connection strings
        result = self.PATTERNS["connection_string"].sub(
            "[REDACTED_CONNECTION_STRING]", result
        )

        # Redact OAuth tokens
        result = self.PATTERNS["oauth_token"].sub(
            "[REDACTED_TOKEN]", result
        )

        # Redact AWS keys
        result = self.PATTERNS["aws_key"].sub(
            "[REDACTED_AWS_KEY]", result
        )

        return result
