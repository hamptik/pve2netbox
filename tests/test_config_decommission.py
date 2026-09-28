"""Config validation tests for the decommission feature (stream A config).

Contract (may not be fully implemented yet at run time):
- ENABLE_CLEANUP=true without NB_DECOMMISSION_CLUSTER_ID -> SystemExit
- ENABLE_CLEANUP unset/false without it -> OK
- DECOMMISSION_AFTER_CYCLES=0 -> SystemExit
- Valid full set -> parsed fields present on the returned Config.
"""

import pytest

from pve2netbox.config import load_config

REQUIRED_ENV = {
    'PVE_API_HOST': 'pve.example.org',
    'PVE_API_USER': 'netsync@pve',
    'PVE_API_TOKEN': 'tok',
    'PVE_API_SECRET': 'sec',
    'NB_API_URL': 'https://netbox.example.org',
    'NB_API_TOKEN': 'nb-tok',
}

DECOMMISSION_ENV = {
    'ENABLE_CLEANUP': 'true',
    'NB_DECOMMISSION_CLUSTER_ID': '17',
    'DECOMMISSION_AFTER_CYCLES': '3',
}


@pytest.fixture
def clean_env(monkeypatch):
    """Wipe every config-relevant variable, then set the required base."""
    for var in list(REQUIRED_ENV) + [
        'ENABLE_CLEANUP',
        'NB_DECOMMISSION_CLUSTER_ID',
        'DECOMMISSION_AFTER_CYCLES',
        'NB_CLUSTER_ID',
        'DRY_RUN',
        'SYNC_INTERVAL_SECONDS',
        'QUICK_CHECK_INTERVAL_SECONDS',
        'PRIMARY_SUBNETS',
    ]:
        monkeypatch.delenv(var, raising=False)
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


class TestDecommissionConfigValidation:
    def test_enable_cleanup_without_decommission_cluster_exits(self, clean_env):
        """ENABLE_CLEANUP=true but no NB_DECOMMISSION_CLUSTER_ID -> SystemExit."""
        clean_env.setenv('ENABLE_CLEANUP', 'true')
        with pytest.raises(SystemExit):
            load_config()

    def test_cleanup_disabled_without_decommission_cluster_is_ok(self, clean_env):
        """ENABLE_CLEANUP=false (default) and no NB_DECOMMISSION_CLUSTER_ID -> OK."""
        clean_env.setenv('ENABLE_CLEANUP', 'false')
        config = load_config()
        assert config.enable_cleanup is False

    def test_decommission_after_cycles_zero_exits(self, clean_env):
        """DECOMMISSION_AFTER_CYCLES=0 must be rejected."""
        clean_env.setenv('ENABLE_CLEANUP', 'true')
        clean_env.setenv('NB_DECOMMISSION_CLUSTER_ID', '17')
        clean_env.setenv('DECOMMISSION_AFTER_CYCLES', '0')
        with pytest.raises(SystemExit):
            load_config()

    def test_valid_decommission_config_fields_present(self, clean_env):
        """Full valid set -> Config carries all decommission fields."""
        for key, value in DECOMMISSION_ENV.items():
            clean_env.setenv(key, value)

        config = load_config()

        assert config.pve_api_host == 'pve.example.org'
        assert config.pve_api_user == 'netsync@pve'
        assert config.pve_api_token == 'tok'
        assert config.pve_api_secret == 'sec'
        assert config.nb_api_url == 'https://netbox.example.org'
        assert config.nb_api_token == 'nb-tok'
        assert config.nb_decommission_cluster_id == 17
        assert config.decommission_after_cycles == 3
        assert config.enable_cleanup is True
