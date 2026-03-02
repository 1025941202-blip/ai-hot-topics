from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import SourceEntry
from .utils import merge_env_from_file, unique_keep_order


SUPPORTED_PLATFORMS = ("douyin", "xiaohongshu", "huitun", "x", "youtube")


@dataclass
class ProjectPaths:
    project_dir: Path
    sources_file: Path
    keywords_file: Path
    scoring_file: Path
    env_file: Path
    data_dir: Path
    raw_data_dir: Path
    db_path: Path
    prompt_file: Path


@dataclass
class KeywordsConfig:
    include_keywords: list[str]
    include_hashtags: list[str]
    exclude_keywords: list[str]
    platform_overrides: dict[str, dict[str, list[str]]]
    language_hint: str = "zh"

    def keywords_for_platform(self, platform: str) -> list[str]:
        override = self.platform_overrides.get(platform, {})
        extra = override.get("include_keywords", [])
        return unique_keep_order([*self.include_keywords, *extra])


@dataclass
class ScoringConfig:
    weights: dict[str, float]
    weights_version: str
    generation_threshold: float
    platform_normalization: dict[str, dict[str, float]]
    penalties: dict[str, float]
    heuristics: dict[str, list[str]]


@dataclass
class RuntimeConfig:
    paths: ProjectPaths
    env: dict[str, str]
    sources: list[SourceEntry]
    keywords: KeywordsConfig
    scoring: ScoringConfig


def _safe_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config must be a mapping: {path}")
    return data


def discover_project_paths(project_dir: str | Path) -> ProjectPaths:
    root = Path(project_dir).resolve()
    env_values = merge_env_from_file(root / ".env")
    data_dir = Path(env_values.get("DATA_DIR", root / "data"))
    raw_data_dir = Path(env_values.get("RAW_DATA_DIR", data_dir / "raw"))
    db_path = Path(env_values.get("DB_PATH", data_dir / "hot_topics.db"))
    return ProjectPaths(
        project_dir=root,
        sources_file=root / "sources.yaml",
        keywords_file=root / "keywords.yaml",
        scoring_file=root / "scoring.yaml",
        env_file=root / ".env",
        data_dir=data_dir,
        raw_data_dir=raw_data_dir,
        db_path=db_path,
        prompt_file=root / "prompts" / "short_video_outline.md",
    )


def load_sources(path: Path) -> list[SourceEntry]:
    data = _safe_yaml(path)
    if data.get("schema_version") != 1:
        raise ValueError("sources.yaml schema_version must be 1")
    sources = data.get("sources")
    if not isinstance(sources, list):
        raise ValueError("sources.yaml 'sources' must be a list")
    result: list[SourceEntry] = []
    for item in sources:
        if not isinstance(item, dict):
            raise ValueError("sources.yaml item must be a mapping")
        result.append(
            SourceEntry(
                id=str(item["id"]),
                name=str(item["name"]),
                url=str(item["url"]),
                category=str(item["category"]),
                language=str(item["language"]),
                region=(str(item["region"]) if item.get("region") else None),
                status=str(item["status"]),
                priority=int(item["priority"]),
                notes=(str(item["notes"]) if item.get("notes") else None),
                added_at=str(item["added_at"]),
            )
        )
    return result


def load_keywords(path: Path) -> KeywordsConfig:
    data = _safe_yaml(path)
    if data.get("schema_version") != 1:
        raise ValueError("keywords.yaml schema_version must be 1")
    include_keywords = [str(x) for x in data.get("include_keywords", [])]
    include_hashtags = [str(x) for x in data.get("include_hashtags", [])]
    exclude_keywords = [str(x) for x in data.get("exclude_keywords", [])]
    platform_overrides_raw = data.get("platform_overrides", {})
    if not isinstance(platform_overrides_raw, dict):
        raise ValueError("platform_overrides must be a mapping")
    platform_overrides: dict[str, dict[str, list[str]]] = {}
    for platform, value in platform_overrides_raw.items():
        if platform not in SUPPORTED_PLATFORMS:
            raise ValueError(f"Unsupported platform in keywords.yaml: {platform}")
        if not isinstance(value, dict):
            raise ValueError(f"platform_overrides.{platform} must be a mapping")
        normalized = {
            k: [str(x) for x in v]
            for k, v in value.items()
            if isinstance(v, list)
        }
        platform_overrides[platform] = normalized
    if not include_keywords:
        raise ValueError("include_keywords cannot be empty")
    return KeywordsConfig(
        include_keywords=include_keywords,
        include_hashtags=include_hashtags,
        exclude_keywords=exclude_keywords,
        platform_overrides=platform_overrides,
        language_hint=str(data.get("language_hint", "zh")),
    )


def load_scoring(path: Path) -> ScoringConfig:
    data = _safe_yaml(path)
    if data.get("schema_version") != 1:
        raise ValueError("scoring.yaml schema_version must be 1")
    weights = {str(k): float(v) for k, v in (data.get("weights") or {}).items()}
    required = {"hotness", "freshness", "reproducibility", "china_fit"}
    if set(weights) != required:
        missing = required - set(weights)
        extra = set(weights) - required
        raise ValueError(f"scoring weights keys mismatch; missing={missing}, extra={extra}")
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"scoring weights must sum to 1.0, got {total}")
    platform_norm = data.get("platform_normalization") or {}
    if not isinstance(platform_norm, dict):
        raise ValueError("platform_normalization must be a mapping")
    return ScoringConfig(
        weights=weights,
        weights_version=str(data.get("weights_version", "v1")),
        generation_threshold=float(data.get("generation_threshold", 70)),
        platform_normalization={
            str(platform): {str(k): float(v) for k, v in (vals or {}).items()}
            for platform, vals in platform_norm.items()
            if isinstance(vals, dict)
        },
        penalties={str(k): float(v) for k, v in (data.get("penalties") or {}).items()},
        heuristics={
            str(k): [str(x) for x in v]
            for k, v in (data.get("heuristics") or {}).items()
            if isinstance(v, list)
        },
    )


def load_runtime_config(project_dir: str | Path) -> RuntimeConfig:
    paths = discover_project_paths(project_dir)
    env = merge_env_from_file(paths.env_file)
    return RuntimeConfig(
        paths=paths,
        env=env,
        sources=load_sources(paths.sources_file),
        keywords=load_keywords(paths.keywords_file),
        scoring=load_scoring(paths.scoring_file),
    )
