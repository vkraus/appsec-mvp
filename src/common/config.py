"""Config loader. YAML → Pydantic models. One ConnectorConfig per
connector + two RootModel dicts for severity/status normalization."""

from pathlib import Path
from typing import Literal, TypeVar

import yaml
from pydantic import BaseModel, RootModel, ConfigDict


T = TypeVar("T", bound=BaseModel)


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["basic", "bearer", "oauth_app", "aws_sigv4"]
    # Names of Databricks secret-scope keys; never contains actual secrets
    username_secret: str | None = None
    password_secret: str | None = None
    token_secret: str | None = None


class PaginationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: Literal["offset", "cursor", "keyset", "none"]
    page_size: int = 100


class HwmConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: Literal["updated_at", "commit_sha", "scan_id"]
    column: str | None = None


class ConnectorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    category: Literal["cmdb", "scm", "sast", "sca", "secrets", "dast", "waf"]
    base_url: str
    auth: AuthConfig
    pagination: PaginationConfig
    hwm: HwmConfig


class SeverityMap(RootModel[dict[str, Literal["critical", "high", "medium", "low", "info"]]]):
    pass


class StatusMap(RootModel[dict[str, Literal["open", "confirmed", "resolved", "false_positive", "wontfix"]]]):
    pass


def load_yaml(model: type[T], path: Path) -> T:
    with open(path) as fh:
        data = yaml.safe_load(fh)
    return model.model_validate(data)
