"""Safe content-addressed paths for large, immutable raw data files."""

from __future__ import annotations

import hashlib
from pathlib import Path


class ArtifactPathError(ValueError):
    pass


def artifact_path(root: str | Path, content_sha256: str, filename: str) -> Path:
    if len(content_sha256) != 64 or any(
        c not in "0123456789abcdef" for c in content_sha256.lower()
    ):
        raise ArtifactPathError("content_sha256 must be a 64-character hex digest")
    name = Path(filename)
    if name.name != filename or not filename or filename in {".", ".."}:
        raise ArtifactPathError("filename must be a single safe path component")
    base = Path(root).resolve()
    target = (base / content_sha256[:2] / filename).resolve()
    if base not in target.parents:
        raise ArtifactPathError("artifact path escapes configured root")
    return target


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["ArtifactPathError", "artifact_path", "sha256_file"]
