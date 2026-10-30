"""Unit tests for configuration loading, saving, environment expansion, and profile resolution."""

import os
import pytest

from rcon_craft.config import (
    add_profile,
    get_profile,
    load_config,
    remove_profile,
    resolve_env_value,
    save_config,
)
from rcon_craft.models import ConfigError, ServerProfile


def test_resolve_env_value(monkeypatch):
    monkeypatch.setenv("MC_PASS", "super_secret_123")
    monkeypatch.setenv("MC_HOST", "mc.hypixel.net")

    assert resolve_env_value("env:MC_PASS") == "super_secret_123"
    assert resolve_env_value("${MC_HOST}") == "mc.hypixel.net"
    assert resolve_env_value("prefix_${MC_HOST}_suffix") == "prefix_mc.hypixel.net_suffix"
    assert resolve_env_value("plain_value") == "plain_value"


def test_load_save_config_roundtrip(tmp_path):
    cfg_file = tmp_path / "servers.toml"

    p1 = ServerProfile(name="survival", host="10.0.0.1", port=25575, password="pass1", timeout=6.0)
    p2 = ServerProfile(name="creative", host="10.0.0.2", port=25576, password="pass2", timeout=3.0)

    save_config({"survival": p1, "creative": p2}, default_server="survival", path=cfg_file)

    profiles, default_server = load_config(cfg_file)
    assert default_server == "survival"
    assert len(profiles) == 2
    assert "survival" in profiles
    assert "creative" in profiles

    s = profiles["survival"]
    assert s.host == "10.0.0.1"
    assert s.port == 25575
    assert s.password == "pass1"
    assert s.timeout == 6.0


def test_get_profile_explicit_and_default(tmp_path):
    cfg_file = tmp_path / "servers.toml"
    p1 = ServerProfile(name="s1", host="1.1.1.1", password="pw1")
    p2 = ServerProfile(name="s2", host="2.2.2.2", password="pw2")

    save_config({"s1": p1, "s2": p2}, default_server="s2", path=cfg_file)

    # Fetch default profile
    def_prof = get_profile(None, config_path=cfg_file)
    assert def_prof.name == "s2"
    assert def_prof.host == "2.2.2.2"

    # Fetch explicit profile
    s1_prof = get_profile("s1", config_path=cfg_file)
    assert s1_prof.name == "s1"
    assert s1_prof.host == "1.1.1.1"


def test_get_profile_not_found(tmp_path):
    cfg_file = tmp_path / "servers.toml"
    p1 = ServerProfile(name="s1", host="1.1.1.1")
    save_config({"s1": p1}, default_server="s1", path=cfg_file)

    with pytest.raises(ConfigError, match="not found"):
        get_profile("non_existent", config_path=cfg_file)


def test_get_profile_no_profiles(tmp_path):
    cfg_file = tmp_path / "servers.toml"
    save_config({}, default_server=None, path=cfg_file)

    with pytest.raises(ConfigError, match="No server profiles found"):
        get_profile(None, config_path=cfg_file)


def test_get_profile_single_fallback_without_default(tmp_path):
    cfg_file = tmp_path / "servers.toml"
    p1 = ServerProfile(name="only_one", host="1.1.1.1")
    save_config({"only_one": p1}, default_server=None, path=cfg_file)

    # When there's only 1 profile, it should automatically be used
    prof = get_profile(None, config_path=cfg_file)
    assert prof.name == "only_one"


def test_add_and_remove_profile(tmp_path):
    cfg_file = tmp_path / "servers.toml"
    p1 = ServerProfile(name="hub", host="192.168.1.100")

    add_profile(p1, set_as_default=True, config_path=cfg_file)
    profiles, def_serv = load_config(cfg_file)
    assert "hub" in profiles
    assert def_serv == "hub"

    removed = remove_profile("hub", config_path=cfg_file)
    assert removed is True
    profiles, def_serv = load_config(cfg_file)
    assert "hub" not in profiles
    assert def_serv is None

    # Remove non-existent returns False
    assert remove_profile("hub", config_path=cfg_file) is False


def test_load_config_invalid_toml(tmp_path):
    cfg_file = tmp_path / "invalid.toml"
    cfg_file.write_text("this is completely invalid toml = [", encoding="utf-8")

    with pytest.raises(ConfigError, match="Failed to parse config file"):
        load_config(cfg_file)
