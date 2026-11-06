# Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Yarvelle Core configuration settings via Pydantic Settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field, PrivateAttr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from yarvelle_core import identity


class BrandConfig(BaseModel):
    """Branding and namespace configuration for product runtime."""

    product_name: str = "Yarvelle Core"
    env_prefix: str = "YARVELLE_CORE_"
    # Runtime identity defaults come from ``yarvelle_core.identity`` (env vars).
    home_dir_name: str = Field(default_factory=identity.home_dir_name)
    db_filename: str = Field(default_factory=identity.db_filename)
    oauth_scheme: str = Field(default_factory=identity.url_scheme)
    cookie_prefix: str = Field(default_factory=lambda: f"{identity.app_slug()}_")
    default_agent: str = "assistant"

from yarvelle_core.constants.defaults import DEFAULT_CORS_ORIGINS
from yarvelle_core.constants.models import (
    DEFAULT_MODEL,
    DEFAULT_MODEL_TIMEOUT_SECONDS,
    DEFAULT_OLLAMA_URL,
    ENV_OLLAMA_URLS,
)
from yarvelle_core.constants.paths import (
    AGENTS_DIR,
    ATTACHMENTS_DIR,
    DEFAULT_AUDIT_LOG_FILE,
    DEFAULT_CATALOG_DB,
    DEFAULT_CHECKPOINTS_DB,
    ENV_AUDIT_LOG_PATH,
    ENV_CATALOG_DB_PATH,
    ENV_DB_PATH,
    ENV_WORKSPACE_ROOT,
    LOGS_DIR,
    NOTES_DIR,
    SKILLS_DIR,
    SQL_DB_FILENAME,
    UPLOADS_DIR,
    WORKSPACE_DIR,
    WORKSPACE_NOTES_DIR,
)


def get_default_workspace_root() -> Path:
    """Finds repository workspace root or defaults to cwd."""
    # Check YARVELLE_WORKSPACE_ROOT env var
    env_root = os.getenv(ENV_WORKSPACE_ROOT)
    if env_root and os.path.isdir(env_root):
        return Path(env_root).resolve()

    # If backend/ is subdirectory of workspace
    current = Path.cwd().resolve()
    if (current / AGENTS_DIR).is_dir() and (current / SKILLS_DIR).is_dir():
        return current
    if (current.parent / AGENTS_DIR).is_dir() and (current.parent / SKILLS_DIR).is_dir():
        return current.parent.resolve()

    return current


def resolve_yarvelle_home() -> Path:
    """Resolves the canonical Yarvelle Core home storage directory (~/.yarvelle).

    Resolution Precedence:
    1. YARVELLE_HOME environment variable (or YARVELLE_HOME_DIR)
    2. YARVELLE_WORKSPACE_ROOT environment variable (if explicitly pointing to
       a .yarvelle directory or non-repository test sandbox)
    3. Cross-platform user home default: Path.home() / identity.home_dir_name()
       - Linux:   /home/<user>/.yarvelle
       - macOS:   /Users/<user>/.yarvelle
       - Windows: C:\\Users\\<user>\\.yarvelle (via %USERPROFILE%)

    Returns:
        Path: Absolute resolved filesystem path to the Yarvelle Core home directory.
    """
    # 1. Primary override: YARVELLE_HOME or YARVELLE_HOME_DIR
    env_home = identity.getenv("HOME") or identity.getenv("HOME_DIR")
    if env_home and env_home.strip():
        return Path(env_home.strip()).expanduser().resolve()

    # 2. Secondary override: YARVELLE_WORKSPACE_ROOT
    env_ws = identity.getenv("WORKSPACE_ROOT")
    if env_ws and env_ws.strip():
        ws_path = Path(env_ws.strip()).expanduser().resolve()
        # If explicitly pointed at a .yarvelle folder
        home_dir_name = identity.home_dir_name()
        if ws_path.name == home_dir_name:
            return ws_path
        # If containing a .yarvelle subfolder
        if (ws_path / home_dir_name).is_dir():
            return (ws_path / home_dir_name).resolve()
        # If pointing to an isolated sandbox/test path (does not contain repository agents/skills)
        if not (ws_path / AGENTS_DIR).is_dir() and not (ws_path / "backend").is_dir():
            return ws_path

    # 3. Default: cross-platform user home directory
    return (Path.home() / identity.home_dir_name()).resolve()


def get_default_ollama_url() -> str:
    """Resolves default Ollama URL from environment variables or constant."""
    for var in ENV_OLLAMA_URLS:
        val = os.getenv(var)
        if val and val.strip():
            return val.strip()
    return DEFAULT_OLLAMA_URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="YARVELLE_CORE_",
        env_file=".env",
        extra="ignore"
    )

    # Product Brand Customization
    _brand_config: BrandConfig = PrivateAttr(default_factory=BrandConfig)

    @property
    def brand_config(self) -> BrandConfig:
        return self._brand_config

    @property
    def product_name(self) -> str:
        return self._brand_config.product_name

    @property
    def env_prefix(self) -> str:
        return self._brand_config.env_prefix

    @property
    def home_dir_name(self) -> str:
        return self._brand_config.home_dir_name

    @property
    def db_filename(self) -> str:
        return self._brand_config.db_filename

    @property
    def oauth_scheme(self) -> str:
        return self._brand_config.oauth_scheme

    @property
    def cookie_prefix(self) -> str:
        return self._brand_config.cookie_prefix

    @property
    def default_agent(self) -> str:
        return self._brand_config.default_agent

    workspace_root: Path = get_default_workspace_root()
    home_dir: Path = Field(default_factory=resolve_yarvelle_home)

    ollama_url: str = Field(default_factory=get_default_ollama_url)
    default_model: str = DEFAULT_MODEL
    model_timeout_seconds: float = DEFAULT_MODEL_TIMEOUT_SECONDS

    # Logging configuration
    log_level: str = "INFO"
    log_json: bool = False

    # Audit logging configuration
    audit_log_path: Optional[Path] = None
    audit_store_bodies: bool = False

    # SQLite checkpointer database path
    db_path: Optional[Path] = None

    # Checkpoint encryption at rest (opt-in). The key is derived from the vault KEK.
    # checkpoint_plaintext_reads keeps legacy plaintext rows readable during migration;
    # turn it off once 'checkpoints encrypt' has run. Bump checkpoint_key_version to
    # rotate (older versions stay readable; 'checkpoints encrypt' re-encrypts them).
    checkpoint_encryption: bool = False
    checkpoint_plaintext_reads: bool = True
    checkpoint_key_version: int = Field(default=1, ge=1)

    # Opt-in at-rest encryption for audit detail bodies and long-term memory payloads.
    # Keys derive from the vault KEK (same pattern as checkpoint encryption). Defaults
    # preserve plaintext. plaintext_reads keeps legacy rows readable during migration;
    # turn them off after an explicit app-side migration (e.g. Carefold F4).
    audit_encryption: bool = False
    audit_plaintext_reads: bool = True
    audit_key_version: int = Field(default=1, ge=1)
    memory_encryption: bool = False
    memory_plaintext_reads: bool = True
    memory_key_version: int = Field(default=1, ge=1)

    # Relational Database configuration (R1)
    database_url: Optional[str] = Field(
        default=None,
        description="Database URL supporting SQLite and PostgreSQL (YARVELLE_DATABASE_URL or DATABASE_URL)",
    )

    # Memory and Catalog abstraction configuration (R2)
    memory_backend: str = "sqlite"
    spector_url: str = "http://localhost:7070"
    catalog_db_path: Optional[Path] = None
    memory_fallback_to_sqlite: bool = Field(
        default=True,
        description="Fallback to local SQLite/InMemory store if Spector is unreachable",
    )

    # Authentication provider configuration (R2)
    auth_provider: str = Field(
        default="local",
        description="Active authentication provider (local, disabled, oidc)",
    )

    # CORS configuration
    cors_origins: List[str] = list(DEFAULT_CORS_ORIGINS)

    @model_validator(mode="after")
    def _resolve_database_url(self) -> "Settings":
        """Initializes database_url if not explicitly set."""
        if not self.database_url:
            env_cf = identity.getenv("DATABASE_URL")
            if env_cf and env_cf.strip():
                self.database_url = env_cf.strip()
            else:
                env_db = os.getenv("DATABASE_URL")
                if env_db and env_db.strip():
                    self.database_url = env_db.strip()
                else:
                    self.database_url = f"sqlite+aiosqlite:///{self.home_dir}/{self.db_filename}"
        return self

    def get_home_dir(self) -> Path:
        """Returns the resolved root home storage directory (~/.yarvelle)."""
        return self.home_dir

    def get_uploads_dir(self) -> Path:
        """Returns the uploads directory (~/.yarvelle/uploads) managed via StoragePort."""
        return self.home_dir / UPLOADS_DIR

    def get_database_url(self) -> str:
        """Resolves active database URL, honoring environment overrides or home_dir."""
        env_cf = identity.getenv("DATABASE_URL")
        if env_cf and env_cf.strip():
            return env_cf.strip()
        env_db = os.getenv("DATABASE_URL")
        if env_db and env_db.strip():
            return env_db.strip()
        # If database_url was set to a custom external DB (e.g. Postgres), preserve it.
        # Otherwise, dynamically evaluate against self.home_dir to support test isolation.
        if (
            self.database_url
            and not self.database_url.endswith("/workspace/yarvelle_core.db")
            and not self.database_url.endswith(f"/workspace/{self.db_filename}")
            and not (self.database_url.startswith("sqlite+aiosqlite:///") and (self.database_url.endswith(f"/{SQL_DB_FILENAME}") or self.database_url.endswith(f"/{self.db_filename}")))
        ):
            return self.database_url
        return f"sqlite+aiosqlite:///{self.home_dir}/{self.db_filename}"

    def get_catalog_db_path(self) -> Path:
        """Resolves catalog database path, defaulting to home_dir / DEFAULT_CATALOG_DB."""
        if self.catalog_db_path is not None:
            return self.catalog_db_path
        env_cat = os.getenv(ENV_CATALOG_DB_PATH)
        if env_cat and env_cat.strip():
            return Path(env_cat.strip()).resolve()
        return self.home_dir / DEFAULT_CATALOG_DB

    def get_checkpointer_path(self) -> Path:
        """Resolves LangGraph checkpointer SQLite database path, defaulting to home_dir / DEFAULT_CHECKPOINTS_DB."""
        if self.db_path is not None:
            return self.db_path.resolve()
        env_db = os.getenv(ENV_DB_PATH)
        if env_db and env_db.strip():
            return Path(env_db.strip()).resolve()
        return self.home_dir / DEFAULT_CHECKPOINTS_DB

    def get_audit_log_path(self) -> Path:
        """Resolves audit log path, defaulting to home_dir / logs / audit.jsonl."""
        if self.audit_log_path is not None:
            return self.audit_log_path
        env_audit = os.getenv(ENV_AUDIT_LOG_PATH)
        if env_audit and env_audit.strip():
            return Path(env_audit.strip()).resolve()
        return self.home_dir / LOGS_DIR / DEFAULT_AUDIT_LOG_FILE

    def get_agents_dir(self) -> Path:
        """Returns bundled agent definition directory (in repository or packaged _content)."""
        candidate = self.workspace_root / AGENTS_DIR
        if candidate.is_dir():
            return candidate
        try:
            import importlib.resources
            packaged = Path(str(importlib.resources.files("yarvelle_core").joinpath("_content/agents")))
            if packaged.is_dir():
                return packaged
        except Exception:
            pass
        return candidate

    def get_skills_dir(self) -> Path:
        """Returns bundled skill packs directory (in repository or packaged _content)."""
        candidate = self.workspace_root / SKILLS_DIR
        if candidate.is_dir():
            return candidate
        try:
            import importlib.resources
            packaged = Path(str(importlib.resources.files("yarvelle_core").joinpath("_content/skills")))
            if packaged.is_dir():
                return packaged
        except Exception:
            pass
        return candidate

    def get_attachments_dir(self) -> Path:
        """Returns attachments directory. In Phase1, aliases to get_uploads_dir()."""
        return self.get_uploads_dir()

    def get_notes_dir(self) -> Path:
        """Returns notes directory, rooted under home_dir to prevent writing to repository."""
        if not (self.workspace_root / "backend").is_dir() and (self.workspace_root / WORKSPACE_NOTES_DIR).is_dir():
            return self.workspace_root / WORKSPACE_NOTES_DIR
        notes_path = self.home_dir / NOTES_DIR
        notes_path.mkdir(parents=True, exist_ok=True)
        return notes_path


settings = Settings()
