"""Tests for credential detection and redaction in persisted migration records."""

from bqtofabric.converter import CompatibilityLevel, SqlConversion, TargetDialect
from bqtofabric.converter.models import SparkCodeLanguage
from bqtofabric.converter.spark_converter import SparkConverter
from bqtofabric.security import CredentialScanner


def test_scan_service_account_path() -> None:
    """Service-account file paths must be detected before persistence."""
    text = 'export GOOGLE_APPLICATION_CREDENTIALS="C:\\secrets\\gcp-sa.json"'

    findings = CredentialScanner().scan(text)

    assert findings
    assert any("gcp-sa.json" in finding.pattern for finding in findings)


def test_redact_private_key() -> None:
    """Private-key blocks must not appear in serialized artifacts."""
    text = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgk...\n-----END PRIVATE KEY-----"

    redacted = CredentialScanner().redact(text)

    assert "[REDACTED" in redacted  # Matches [REDACTED_PRIVATE_KEY] or similar
    assert "BEGIN PRIVATE KEY" not in redacted


def test_sql_conversion_redacts_credentials_on_serialize() -> None:
    """SQL conversion evidence must redact secret values before JSON serialization."""
    result = SqlConversion(
        source_id="project.dataset.view",
        target_dialect=TargetDialect.TSQL,
        source_text='SELECT * FROM table1 WHERE api_key = "sk-1234567890"',
        target_text='SELECT * FROM table1 WHERE api_key = "sk-1234567890"',
        compatibility_level=CompatibilityLevel.DIRECT,
    )

    serialized = result.to_json()

    # Ensure credentials are redacted in serialized form
    assert "sk-1234567890" not in serialized


def test_spark_conversion_redacts_service_account_path() -> None:
    """Spark conversion records must not retain service-account file paths."""
    code = 'credentials = "C:\\secrets\\gcp-sa.json"\nspark.read.parquet("gs://bucket/data")'

    result = SparkConverter().convert(
        source_id="dataproc-job",
        code=code,
        language=SparkCodeLanguage.PYSPARK,
    )

    assert "gcp-sa.json" not in result.source_text
    assert "gcp-sa.json" not in result.target_text