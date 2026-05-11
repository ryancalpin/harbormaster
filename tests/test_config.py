import pytest
from pathlib import Path
from harbormaster.config import HarbormasterConfig, load_config, save_config

def test_default_config():
    cfg = HarbormasterConfig()
    assert cfg.api_port == 19191
    assert cfg.watch_range == (1024, 49151)
    assert cfg.approval_gateway == "tui"
    assert cfg.approval_timeout == 0
    assert len(cfg.secret) == 64  # 32 bytes hex

def test_load_config_creates_file_if_missing(tmp_path):
    config_file = tmp_path / "config.toml"
    cfg = load_config(config_file)
    assert config_file.exists()
    assert cfg.api_port == 19191

def test_save_and_reload_config(tmp_path):
    config_file = tmp_path / "config.toml"
    cfg = load_config(config_file)
    cfg.approval_gateway = "telegram"
    cfg.approval_timeout = 30
    cfg.watch_range = (2000, 40000)
    cfg.telegram.bot_token = "test-token-123"
    save_config(cfg, config_file)
    reloaded = load_config(config_file)
    assert reloaded.approval_gateway == "telegram"
    assert reloaded.approval_timeout == 30
    assert reloaded.watch_range == (2000, 40000)
    assert isinstance(reloaded.watch_range, tuple)
    assert reloaded.telegram.bot_token == "test-token-123"

def test_secret_stable_across_reloads(tmp_path):
    config_file = tmp_path / "config.toml"
    cfg1 = load_config(config_file)
    cfg2 = load_config(config_file)
    assert cfg1.secret == cfg2.secret


def test_notification_lead_time_default(tmp_path):
    from harbormaster.config import load_config
    cfg = load_config(tmp_path / "config.toml")
    assert cfg.notification_lead_time == 3600  # default 1 hour


def test_notification_lead_time_from_toml(tmp_path):
    import tomli_w
    from harbormaster.config import load_config
    config_file = tmp_path / "config.toml"
    data = {"notification": {"lead_time": "30m"}}
    with open(config_file, "wb") as f:
        tomli_w.dump(data, f)
    cfg = load_config(config_file)
    assert cfg.notification_lead_time == 1800


def test_notification_lead_time_integer_toml(tmp_path):
    import tomli_w
    from harbormaster.config import load_config
    config_file = tmp_path / "config.toml"
    data = {"notification": {"lead_time": 7200}}
    with open(config_file, "wb") as f:
        tomli_w.dump(data, f)
    cfg = load_config(config_file)
    assert cfg.notification_lead_time == 7200
