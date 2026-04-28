"""Dedicated registry API resolver.

Additive resolver mode that fetches APM packages over a REST registry contract
(see docs/proposals/registry-api.md). Sits alongside the existing Git resolver;
opt-in via ``apm experimental enable package-registry`` before using the
top-level ``registries:`` block in ``apm.yml``.

This package is intentionally separate from ``src/apm_cli/registry/`` (the MCP
registry client) — the two address different concepts and must not be confused.
"""

from .auth import (
    RegistryAuthContext,
    make_auth_context,
    resolve_registry_basic,
    resolve_registry_token,
)
from .client import RegistryClient, RegistryError, VersionEntry
from .extractor import (
    extract_archive,
    extract_tarball,
    extract_zip,
    verify_sha256,
)
from .feature_gate import (
    DISPLAY_NAME,
    ENABLE_COMMAND,
    FLAG_NAME,
    PackageRegistryFeatureDisabledError,
    is_package_registry_enabled,
    require_package_registry_enabled,
)
from .resolver import RegistryPackageResolver
from .semver import is_semver_range, match_version

__all__ = [
    "RegistryAuthContext",
    "RegistryClient",
    "RegistryError",
    "RegistryPackageResolver",
    "VersionEntry",
    "DISPLAY_NAME",
    "ENABLE_COMMAND",
    "FLAG_NAME",
    "PackageRegistryFeatureDisabledError",
    "extract_archive",
    "extract_tarball",
    "extract_zip",
    "is_semver_range",
    "is_package_registry_enabled",
    "make_auth_context",
    "match_version",
    "require_package_registry_enabled",
    "resolve_registry_basic",
    "resolve_registry_token",
    "verify_sha256",
]
