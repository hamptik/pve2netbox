"""Decision table tests for _get_nb_vm_for_sync (serial=vmid global key).

Contract: pve2netbox._get_nb_vm_for_sync(_nb_api, _nb_objects, vmid, vm_name)
returns a tuple ``(action, vm)`` with action in
{'create', 'update', 'adopt', 'skip'}.
"""

import pytest

import pve2netbox

from .conftest import (
    FakeVM,
    RecordingAPI,
    SentinelAPI,
    make_fake_config,
    make_nb_objects,
)

MY_CLUSTER = 1
GRAVEYARD = 9
OTHER_LIVE = 2


@pytest.fixture(autouse=True)
def _fake_config(monkeypatch):
    monkeypatch.setattr(
        pve2netbox, '_config', make_fake_config(MY_CLUSTER, GRAVEYARD),
    )


def test_no_record_returns_create():
    """No record anywhere -> ('create', None)."""
    nb_objects = make_nb_objects()
    action, vm = pve2netbox._get_nb_vm_for_sync(SentinelAPI(), nb_objects, 100, 'web01')
    assert action == 'create'
    assert vm is None


def test_single_record_in_my_cluster_returns_update():
    """One record with serial=vmid in my cluster -> ('update', vm)."""
    existing = FakeVM(11, 'web01', MY_CLUSTER, serial=100)
    nb_objects = make_nb_objects(existing)
    action, vm = pve2netbox._get_nb_vm_for_sync(SentinelAPI(), nb_objects, 100, 'web01')
    assert action == 'update'
    assert vm is existing


def test_single_record_in_graveyard_returns_adopt():
    """One record with serial=vmid in the graveyard cluster -> ('adopt', vm)."""
    buried = FakeVM(12, 'web01', GRAVEYARD, serial=100)
    nb_objects = make_nb_objects(buried)
    action, vm = pve2netbox._get_nb_vm_for_sync(SentinelAPI(), nb_objects, 100, 'web01')
    assert action == 'adopt'
    assert vm is buried


def test_single_record_in_other_live_cluster_returns_skip():
    """One record with serial=vmid in another live cluster -> ('skip', None)."""
    foreign = FakeVM(13, 'web01', OTHER_LIVE, serial=100)
    nb_objects = make_nb_objects(foreign)
    action, vm = pve2netbox._get_nb_vm_for_sync(SentinelAPI(), nb_objects, 100, 'web01')
    assert action == 'skip'
    assert vm is None


def test_duplicate_serials_return_skip():
    """Two records with the same serial -> ('skip', None)."""
    first = FakeVM(14, 'web01', MY_CLUSTER, serial=100)
    second = FakeVM(15, 'web02', GRAVEYARD, serial=100)
    nb_objects = make_nb_objects(first, second)
    assert nb_objects['virtual_machines_duplicates']  # fixture sanity

    action, vm = pve2netbox._get_nb_vm_for_sync(SentinelAPI(), nb_objects, 100, 'web01')
    assert action == 'skip'
    assert vm is None


def test_skip_and_adopt_never_touch_api():
    """skip/adopt paths must not issue any NetBox API calls."""
    foreign = FakeVM(13, 'web01', OTHER_LIVE, serial=100)
    nb_objects = make_nb_objects(foreign)
    api = RecordingAPI()
    action, _vm = pve2netbox._get_nb_vm_for_sync(api, nb_objects, 100, 'web01')
    assert action == 'skip'
    assert api.touched == []

    buried = FakeVM(12, 'web02', GRAVEYARD, serial=101)
    nb_objects = make_nb_objects(buried)
    api = RecordingAPI()
    action, _vm = pve2netbox._get_nb_vm_for_sync(api, nb_objects, 101, 'web02')
    assert action == 'adopt'
    assert api.touched == []


def test_adopt_matches_graveyard_even_with_different_name():
    """Adopt is keyed on serial (global vmid), not on the VM name."""
    buried = FakeVM(16, 'old-name', GRAVEYARD, serial=100)
    nb_objects = make_nb_objects(buried)
    action, vm = pve2netbox._get_nb_vm_for_sync(SentinelAPI(), nb_objects, 100, 'renamed')
    assert action == 'adopt'
    assert vm is buried
