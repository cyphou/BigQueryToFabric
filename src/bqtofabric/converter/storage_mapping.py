"""Storage path mapping: GCS/HDFS/WASB → OneLake shortcuts."""

from __future__ import annotations

import re
from typing import Any


class StoragePathMapper:
    """Map source storage paths to Fabric OneLake or equivalent targets."""

    @staticmethod
    def normalize_path(path: str) -> str:
        """Normalize path to standard form."""
        return path.strip().rstrip('/')

    @staticmethod
    def is_gcs_path(path: str) -> bool:
        """Check if path is Google Cloud Storage (gs://)."""
        return path.startswith('gs://')

    @staticmethod
    def is_hdfs_path(path: str) -> bool:
        """Check if path is HDFS (hdfs://)."""
        return path.startswith('hdfs://')

    @staticmethod
    def is_wasb_path(path: str) -> bool:
        """Check if path is WASB (wasb://)."""
        return path.startswith('wasb://')

    @staticmethod
    def is_abfs_path(path: str) -> bool:
        """Check if path is ABFS (abfs://)."""
        return path.startswith('abfs://')

    @staticmethod
    def is_s3_path(path: str) -> bool:
        """Check if path is S3 (s3:// or s3a://)."""
        return path.startswith(("s3://", "s3a://"))

    @staticmethod
    def extract_bucket_and_key(path: str) -> tuple[str, str]:
        """Extract bucket/container and key from path."""
        # Parse different path formats
        patterns = {
            'gs://': r'gs://([^/]+)/(.*)',
            'hdfs://': r'hdfs://([^/]+)/(.*)',
            'wasb://': r'wasb://([^@]+)@([^/]+)/(.*)',
            'abfs://': r'abfs://([^@]+)@([^/]+)/(.*)',
            's3://': r's3://([^/]+)/(.*)',
            's3a://': r's3a://([^/]+)/(.*)',
        }

        for prefix, pattern in patterns.items():
            if path.startswith(prefix):
                match = re.match(pattern, path)
                if match:
                    if prefix in ('wasb://', 'abfs://'):
                        # wasb://container@storageaccount.blob.core.windows.net/key
                        container = match.group(1)
                        key = match.group(3)
                    else:
                        container = match.group(1)
                        key = match.group(2)
                    return container, key
        
        return '', path

    @staticmethod
    def map_gcs_to_onelake(gcs_path: str, lakehouse_name: str | None = None) -> dict[str, Any]:
        """
        Map GCS path to OneLake shortcut.
        
        Returns:
            Dict with mapping info, including mapped_path, shortcut_name, rationale.
        """
        bucket, key = StoragePathMapper.extract_bucket_and_key(gcs_path)
        
        if not bucket:
            return {
                'source_path': gcs_path,
                'target_path': None,
                'shortcut_type': None,
                'compatibility': 'unsupported',
                'rationale': 'Unable to parse GCS path.',
                'manual_steps': ['Verify GCS path format', 'Create OneLake shortcut manually'],
            }
        
        # Suggest OneLake shortcut name
        shortcut_name = f"gcs_{bucket}" if not lakehouse_name else f"{lakehouse_name}_gcs_{bucket}"
        mapped_path = f"/Shortcuts/{shortcut_name}/{key}"
        
        return {
            'source_path': gcs_path,
            'target_path': mapped_path,
            'shortcut_type': 'onelake_shortcut',
            'shortcut_name': shortcut_name,
            'source_bucket': bucket,
            'source_key': key,
            'compatibility': 'transform',
            'rationale': 'GCS paths map to OneLake shortcuts in Fabric.',
            'manual_steps': [
                f'Create OneLake shortcut "{shortcut_name}" pointing to gs://{bucket}',
                f'Update code to use "{mapped_path}" or reference the shortcut in Fabric UI',
                'Configure GCS authentication in Fabric connection settings',
            ],
        }

    @staticmethod
    def map_hdfs_to_onelake(hdfs_path: str) -> dict[str, Any]:
        """
        Map HDFS path to OneLake (requires data migration).
        
        Returns:
            Dict with mapping info and manual steps.
        """
        host, key = StoragePathMapper.extract_bucket_and_key(hdfs_path)
        
        return {
            'source_path': hdfs_path,
            'target_path': None,
            'shortcut_type': None,
            'compatibility': 'redesign',
            'rationale': 'HDFS paths require data migration to OneLake; no direct shortcut support.',
            'manual_steps': [
                f'Export HDFS data from {host} using tools like Hadoop distcp or custom export',
                'Upload exported data to OneLake via Azure Storage Explorer or AzCopy',
                'Update code to reference new OneLake path',
                'Consider using Fabric Data Factory for automated data ingestion',
            ],
            'source_host': host,
            'source_key': key,
        }

    @staticmethod
    def map_wasb_to_onelake(wasb_path: str) -> dict[str, Any]:
        """
        Map WASB (Azure Blob Storage) path.
        
        WASB may already be Azure, but OneLake is preferred.
        """
        container, key = StoragePathMapper.extract_bucket_and_key(wasb_path)
        
        return {
            'source_path': wasb_path,
            'target_path': None,
            'shortcut_type': 'onelake_shortcut',
            'compatibility': 'transform',
            'rationale': 'WASB paths should migrate to OneLake shortcuts for unified Fabric access.',
            'manual_steps': [
                f'Create OneLake shortcut pointing to existing WASB container "{container}"',
                'Update code to reference OneLake shortcut path',
                'Consider migrating WASB data directly to OneLake for better integration',
            ],
            'source_container': container,
            'source_key': key,
        }

    @staticmethod
    def map_abfs_to_onelake(abfs_path: str) -> dict[str, Any]:
        """
        Map ABFS (Azure Data Lake Storage Gen2) path.
        
        ABFS is modern Azure storage; may reuse or migrate to OneLake.
        """
        container, key = StoragePathMapper.extract_bucket_and_key(abfs_path)
        
        return {
            'source_path': abfs_path,
            'target_path': None,
            'shortcut_type': 'onelake_shortcut',
            'compatibility': 'transform',
            'rationale': 'ABFS paths should reference OneLake shortcuts for Fabric integration.',
            'manual_steps': [
                f'Create OneLake shortcut pointing to ADLS Gen2 filesystem "{container}"',
                'Update code to reference OneLake shortcut path',
                'Verify access credentials (managed identity or service principal)',
            ],
            'source_container': container,
            'source_key': key,
        }

    @staticmethod
    def map_s3_to_onelake(s3_path: str) -> dict[str, Any]:
        """
        Map S3/S3A path (cross-cloud; requires migration).
        """
        bucket, key = StoragePathMapper.extract_bucket_and_key(s3_path)
        
        return {
            'source_path': s3_path,
            'target_path': None,
            'shortcut_type': None,
            'compatibility': 'redesign',
            'rationale': 'S3 paths are outside Azure; data must be migrated to OneLake.',
            'manual_steps': [
                'Export S3 bucket data using AWS CLI or similar tools',
                'Upload to OneLake via AzCopy or Fabric Data Factory',
                'Update code to reference new OneLake path',
                'Consider AWS DataSync or similar for large-scale migration',
            ],
            'source_bucket': bucket,
            'source_key': key,
        }

    @staticmethod
    def map_path(path: str, lakehouse_name: str | None = None) -> dict[str, Any]:
        """
        Map any storage path to OneLake equivalent.
        
        Args:
            path: Source path (gs://, hdfs://, wasb://, abfs://, s3://, etc.).
            lakehouse_name: Optional Fabric lakehouse name for naming shortcuts.
        
        Returns:
            Dict with mapping details and manual steps.
        """
        normalized = StoragePathMapper.normalize_path(path)
        
        if StoragePathMapper.is_gcs_path(normalized):
            return StoragePathMapper.map_gcs_to_onelake(normalized, lakehouse_name)
        elif StoragePathMapper.is_hdfs_path(normalized):
            return StoragePathMapper.map_hdfs_to_onelake(normalized)
        elif StoragePathMapper.is_wasb_path(normalized):
            return StoragePathMapper.map_wasb_to_onelake(normalized)
        elif StoragePathMapper.is_abfs_path(normalized):
            return StoragePathMapper.map_abfs_to_onelake(normalized)
        elif StoragePathMapper.is_s3_path(normalized):
            return StoragePathMapper.map_s3_to_onelake(normalized)
        else:
            return {
                'source_path': path,
                'target_path': None,
                'shortcut_type': None,
                'compatibility': 'unknown',
                'rationale': 'Path format not recognized.',
                'manual_steps': ['Verify path format', 'Refer to storage type documentation'],
            }

    @staticmethod
    def map_multiple_paths(
        paths: tuple[str, ...] | list[str],
        lakehouse_name: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """
        Map multiple paths at once.
        
        Returns:
            Dict with path → mapping info.
        """
        mappings = {}
        for path in paths:
            mappings[path] = StoragePathMapper.map_path(path, lakehouse_name)
        return mappings

    @staticmethod
    def check_embedded_credentials(path: str) -> tuple[bool, str]:
        """
        Check if path contains embedded credentials (security issue).
        
        Returns:
            (has_credentials, reason)
        """
        credential_patterns = (
            r'[?&](key|password|secret|token|api_key)=',
            r'://\w+:\w+@',  # Basic auth
        )
        
        for pattern in credential_patterns:
            if re.search(pattern, path):
                return True, f"Credentials detected in path: {pattern}"
        
        return False, ""
