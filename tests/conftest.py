"""Shared fixtures and hand-rolled fakes for pve2netbox tests.

No mock libraries: everything is a plain class with just the attributes the
contract requires.

Contract under test (stream C core, may not exist yet at run time):
- pve2netbox._get_nb_vm_for_sync(_nb_api, _nb_objects, vmid, vm_name)
    -> (action, vm) with action in {'create', 'update', 'adopt', 'skip'}
- pve2netbox.compute_reconcile_actions(nb_objects, inventory_vmids,
    cluster_resource_vmids, my_cluster_id, decommission_cluster_id)
    -> {'adopt_vmids': [...], 'decommission_candidates': [...]}
- pve2netbox._absence_counters / pve2netbox._bump_absence(vmid) -> int
- pve2netbox.apply_decommission(_nb_api, nb_objects, vmids, dry_run) -> int
"""

import pytest

import pve2netbox


class FakeCluster:
    """Minimal NetBox cluster: only ``id`` matters."""

    def __init__(self, cluster_id):
        self.id = cluster_id


class FakeVM:
    """Minimal NetBox virtual machine record."""

    def __init__(self, vm_id, name, cluster_id, serial=None, status='active', device='keep'):
        self.id = vm_id
        self.name = name
        self.cluster = FakeCluster(cluster_id)
        self.serial = str(serial) if serial is not None else None
        self.status = status
        # apply_decommission() contract: device must be cleared to None.
        self.device = device
        self.save_calls = 0

    def save(self):
        self.save_calls += 1


class SentinelAPI:
    """Stands in for the NetBox API; any attribute access blows up.

    Used to prove that skip/adopt paths never touch the API.
    """

    def __getattr__(self, name):
        raise AssertionError(
            f'NetBox API must not be touched in this path (accessed: {name})'
        )


class RecordingAPI:
    """Records which top-level API attributes were touched; never fails."""

    def __init__(self):
        self.touched = []

    def __getattr__(self, name):
        self.touched.append(name)
        raise AssertionError(f'unexpected API access: {name}')


class LegacyLookupAPI:
    """Allows exactly the legacy name+cluster lookup, returns no candidates.

    ``virtualization.virtual_machines.filter(...)`` yields an empty list;
    any other chained access behaves the same (returns empty), which is
    enough for the create-path tests.
    """

    class _Endpoint:
        def __call__(self, **kwargs):
            return []

        def __getattr__(self, name):
            return LegacyLookupAPI._Endpoint()

    def __getattr__(self, name):
        return LegacyLookupAPI._Endpoint()


def make_fake_config(nb_cluster_id=1, nb_decommission_cluster_id=9):
    """Build a stand-in for pve2netbox._config with just the fields needed."""

    class _FakeConfig:
        def __init__(self, my_id=nb_cluster_id, decommission_id=nb_decommission_cluster_id):
            self.nb_cluster_id = my_id
            self.nb_decommission_cluster_id = decommission_id

    return _FakeConfig()


def make_nb_objects(*vms):
    """Build the _nb_objects cache dict from FakeVM instances.

    Indexes by serial (``virtual_machines``), by serial with the duplicate
    tracker (``virtual_machines_duplicates``) and by (name, cluster_id).
    """
    objects = {
        'virtual_machines': {},
        'virtual_machines_duplicates': {},
        'virtual_machines_by_name_cluster': {},
    }
    for vm in vms:
        if vm.serial:
            if vm.serial in objects['virtual_machines']:
                objects['virtual_machines_duplicates'].setdefault(vm.serial, []).append(vm)
            else:
                objects['virtual_machines'][vm.serial] = vm
        objects['virtual_machines_by_name_cluster'][(vm.name, int(vm.cluster.id))] = vm
    return objects


@pytest.fixture(autouse=True)
def isolate_module_state(monkeypatch):
    """Save/restore global pve2netbox state around every test.

    Also installs a default fake _config (my cluster 1, graveyard 9): code
    under test reads module-level _config (e.g. apply_decommission), and
    leaving it None would only be realistic for the very first import.
    Test modules override it with their own autouse fixtures where needed.
    """
    saved_config = getattr(pve2netbox, '_config', None)
    monkeypatch.setattr(pve2netbox, '_config', make_fake_config(), raising=False)
    monkeypatch.setattr(
        pve2netbox, '_absence_counters', {}, raising=False,
    )
    yield
    pve2netbox._config = saved_config
    # _absence_counters is patched per-test by monkeypatch; nothing to do.
