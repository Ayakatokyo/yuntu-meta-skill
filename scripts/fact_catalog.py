"""Catalog of the fact packages persisted by a completed Yuntu run."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .analysis_facts import _safe_path, _sha256
    from .fact_selection import FactPackage
except ImportError:  # pragma: no cover - direct script imports
    from analysis_facts import _safe_path, _sha256
    from fact_selection import FactPackage


@dataclass(frozen=True)
class FactCatalog:
    run_id: str
    schema_version: int | str
    record_counts: dict[FactPackage, int]
    fields: dict[FactPackage, tuple[str, ...]]
    available_fields: dict[FactPackage, dict[str, int]]
    package_paths: dict[FactPackage, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "packages": {
                package.value: {
                    "record_count": self.record_counts[package],
                    "fields": list(self.fields[package]),
                    "available_fields": self.available_fields[package],
                    "path": self.package_paths[package],
                }
                for package in self.record_counts
            },
        }


def _read(path: Path) -> Any:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def _walk(value: Any, prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            result[path] = child
            result.update(_walk(child, path))
    return result


def build_fact_catalog(run_root: Path) -> FactCatalog:
    root = Path(run_root).resolve()
    manifest_path = root / "facts" / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"facts manifest is missing: {manifest_path}")
    manifest = _read(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError("facts manifest must be an object")
    packages = manifest.get("packages")
    if not isinstance(packages, dict):
        raise ValueError("facts manifest packages must be an object")

    counts: dict[FactPackage, int] = {}
    fields: dict[FactPackage, tuple[str, ...]] = {}
    availability: dict[FactPackage, dict[str, int]] = {}
    paths: dict[FactPackage, str] = {}
    for raw_name, metadata in packages.items():
        try:
            package = FactPackage(raw_name)
        except ValueError:
            continue
        if not isinstance(metadata, dict) or not isinstance(metadata.get("path"), str):
            raise ValueError(f"package metadata is invalid: {raw_name}")
        package_path = _safe_path(root, metadata["path"])
        if not package_path.is_file():
            raise ValueError(f"fact package is missing: {metadata['path']}")
        expected_hash = metadata.get("sha256")
        if expected_hash and _sha256(package_path) != expected_hash:
            raise ValueError(f"fact package SHA-256 mismatch: {metadata['path']}")
        package_doc = _read(package_path)
        records = package_doc.get("records") if isinstance(package_doc, dict) else None
        if not isinstance(records, list):
            raise ValueError(f"fact package records must be an array: {metadata['path']}")
        if len(records) != metadata.get("record_count"):
            raise ValueError(f"fact package record_count mismatch: {metadata['path']}")
        field_counts: dict[str, int] = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            for field, value in _walk(record).items():
                field_counts.setdefault(field, 0)
                if value not in (None, "", [], {}):
                    field_counts[field] += 1
        counts[package] = len(records)
        fields[package] = tuple(sorted(field_counts))
        availability[package] = field_counts
        paths[package] = metadata["path"]

    run_id = manifest.get("run_id") or manifest.get("runId")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("facts manifest run_id is required")
    return FactCatalog(run_id, manifest.get("schema_version"), counts, fields, availability, paths)


__all__ = ["FactCatalog", "build_fact_catalog"]
