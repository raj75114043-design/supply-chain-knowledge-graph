"""Runtime configuration (read when Settings() is created)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    raw_dir: str = field(default_factory=lambda: os.getenv("RAW_DIR", str(ROOT / "data" / "raw")))
    graph_backend: str = field(default_factory=lambda: os.getenv("GRAPH_BACKEND", "networkx"))   # networkx | neo4j (mirror)
    neo4j_uri: str = field(default_factory=lambda: os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    neo4j_user: str = field(default_factory=lambda: os.getenv("NEO4J_USER", "neo4j"))
    neo4j_password: str = field(default_factory=lambda: os.getenv("NEO4J_PASSWORD", "password"))
    use_llm_extraction: bool = field(default_factory=lambda: os.getenv("LLM_EXTRACTION", "0") == "1")
    api_keys: list[str] = field(default_factory=lambda: [k for k in os.getenv("API_KEYS", "dev-key").split(",") if k])
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "auto"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", ""))
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", ""))
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", os.getenv("GROQ_API_KEY", "")))
    llm_timeout_s: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT_S", "30")))


def get_settings() -> Settings:
    return Settings()
