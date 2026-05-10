import pytest
import tomllib
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
    save_config(cfg, config_file)
    reloaded = load_config(config_file)
    assert reloaded.approval_gateway == "telegram"

def test_secret_stable_across_reloads(tmp_path):
    config_file = tmp_path / "config.toml"
    cfg1 = load_config(config_file)
    cfg2 = load_config(config_file)
    assert cfg1.secret == cfg2.secret
