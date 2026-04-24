import textwrap

import pytest
from pydantic import ValidationError

from src.common.config import ConnectorConfig, SeverityMap, StatusMap, load_yaml


def test_connector_config_parses(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text(textwrap.dedent("""
        source: servicenow
        category: cmdb
        base_url: https://dev.service-now.com
        auth:
          type: basic
          username_secret: sn_user
          password_secret: sn_pass
        pagination:
          strategy: offset
          page_size: 1000
        hwm:
          strategy: updated_at
          column: sys_updated_on
    """))
    cfg = load_yaml(ConnectorConfig, p)
    assert cfg.source == "servicenow"
    assert cfg.pagination.strategy == "offset"
    assert cfg.hwm.strategy == "updated_at"
    assert cfg.hwm.column == "sys_updated_on"


def test_connector_config_rejects_unknown_hwm_strategy(tmp_path):
    p = tmp_path / "config.yml"
    p.write_text(textwrap.dedent("""
        source: x
        category: sast
        base_url: https://example.com
        auth: {type: bearer, token_secret: t}
        pagination: {strategy: none}
        hwm: {strategy: bogus}
    """))
    with pytest.raises(ValidationError):
        load_yaml(ConnectorConfig, p)


def test_severity_map_loads(tmp_path):
    p = tmp_path / "sev.yml"
    p.write_text(textwrap.dedent("""
        BLOCKER: critical
        CRITICAL: critical
        MAJOR: high
        MINOR: medium
        INFO: low
    """))
    sm = load_yaml(SeverityMap, p)
    assert sm.root["BLOCKER"] == "critical"
    assert sm.root["INFO"] == "low"


def test_status_map_loads(tmp_path):
    p = tmp_path / "st.yml"
    p.write_text(textwrap.dedent("""
        OPEN: open
        CONFIRMED: confirmed
        FIXED: resolved
        FALSE_POSITIVE: false_positive
        WONTFIX: wontfix
    """))
    stm = load_yaml(StatusMap, p)
    assert stm.root["FIXED"] == "resolved"
