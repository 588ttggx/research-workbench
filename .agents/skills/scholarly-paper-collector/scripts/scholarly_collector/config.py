from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


SECRET_KEYS = ("api_key", "apikey", "x-apikey", "x-api-key", "key", "token", "authorization", "email", "mailto")


@dataclass(frozen=True)
class CollectorConfig:
    openalex_api_key: str
    semantic_scholar_api_key: str
    contact_email: str
    unpaywall_email: str
    cache_dir: Path
    wos_api_key: str = ""
    wos_api: str = "starter"
    wos_database: str = "WOS"

    @classmethod
    def from_env(cls, run_dir: Path) -> "CollectorConfig":
        file_values = load_config_file()
        contact = get_config_value("SPC_CONTACT_EMAIL", file_values).strip()
        cache_dir = get_config_value("SPC_CACHE_DIR", file_values).strip()
        return cls(
            openalex_api_key=get_config_value("OPENALEX_API_KEY", file_values).strip(),
            semantic_scholar_api_key=get_config_value("SEMANTIC_SCHOLAR_API_KEY", file_values).strip(),
            contact_email=contact,
            unpaywall_email=get_config_value("UNPAYWALL_EMAIL", file_values).strip(),
            cache_dir=Path(cache_dir) if cache_dir else default_cache(run_dir),
            wos_api_key=get_config_value("WOS_API_KEY", file_values).strip(),
            wos_api=get_config_value("WOS_API", file_values).strip().lower() or "starter",
            wos_database=get_config_value("WOS_DATABASE", file_values).strip() or "WOS",
        )


def default_cache(run_dir: Path) -> Path:
    configured_root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ResearchWorkbench/Cache"
    return configured_root / "scholarly"


def skill_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_config_path() -> Path:
    return skill_root() / "config.local.env"


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def load_config_file() -> dict[str, str]:
    configured = os.environ.get("SPC_CONFIG_FILE", "").strip()
    path = Path(configured).expanduser() if configured else default_config_path()
    return parse_env_file(path)


def get_config_value(name: str, file_values: dict[str, str]) -> str:
    env_value = os.environ.get(name)
    if env_value is not None:
        return env_value
    return file_values.get(name, "")


def redact(value: object) -> str:
    text = str(value)
    text = re.sub(r"(?i)(api[_-]?key=)[^&\s]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(authorization:\s*)\S+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(mailto=)[^&\s]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)(email=)[^&\s]+", r"\1[REDACTED]", text)
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", text)
    return text


def redact_mapping(headers: dict[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    clean: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in SECRET_KEYS or "authorization" in key.lower():
            clean[key] = "[REDACTED]"
        else:
            clean[key] = redact(value)
    return clean
