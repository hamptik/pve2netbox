"""Tests for compute_reconcile_actions, absence counters, apply_decommission
and the A->B migration scenario.

Contracts (stream C core, may not exist yet at run time):
- pve2netbox.compute_reconcile_actions(nb_objects, inventory_vmids,
  cluster_resource_vmids, my_cluster_id, decommission_cluster_id)
  -> {'adopt_vmids': list[int], 'decommission_candidates': list[int]} — pure.
- pve2netbox._absence_counters / pve2netbox._bump_absence(vmid) -> int.
- pve2netbox.apply_decommission(_nb_api, nb_objects, vmids, dry_run) -> int.
"""

import pytest

import pve2netbox

from .conftest import FakeCluster, FakeVM, RecordingAPI, make_nb_objects

MY_CLUSTER = 1
GRAVEYARD = 9
OTHER_LIVE = 2


def _nb_vm_with_cluster(vm_id, name, cluster_id, serial=None):
    """FakeVM-like stub for reconcile inputs (no save()/device needed)."""

    class _StubVM:
        pass

    vm = _StubVM()
    vm.id = vm_id
    vm.name = name
    vm.cluster = FakeCluster(cluster_id)
    vm.serial = str(serial) if serial is not None else None
    return vm


def _nb_objects_with(vms):
    objects = make_nb_objects(*vms)
    # compute_reconcile_actions may rely on the duplicates map; make sure it
    # exists even when empty.
    objects.setdefault('virtual_machines_duplicates', {})
    return objects


class TestComputeReconcileActions:
    def test_graveyard_record_in_inventory_is_adopt(self):
        """Record sits in graveyard + vmid live in inventory -> adopt."""
        buried = _nb_vm_with_cluster(12, 'web01', GRAVEYARD, serial=100)
        nb_objects = _nb_objects_with([buried])

        result = pve2netbox.compute_reconcile_actions(
            nb_objects,
            inventory_vmids={100},
            cluster_resource_vmids=set(),
            my_cluster_id=MY_CLUSTER,
            decommission_cluster_id=GRAVEYARD,
        )

        assert result['adopt_vmids'] == [100]
        assert result['decommission_candidates'] == []

    def test_my_cluster_record_in_cluster_resources_is_not_candidate(self):
        """Record in my cluster, vmid absent from inventory but present in
        cluster_resources -> NOT a decommission candidate (counter-level)."""
        mine = _nb_vm_with_cluster(11, 'web01', MY_CLUSTER, serial=100)
        nb_objects = _nb_objects_with([mine])

        result = pve2netbox.compute_reconcile_actions(
            nb_objects,
            inventory_vmids=set(),
            cluster_resource_vmids={100},
            my_cluster_id=MY_CLUSTER,
            decommission_cluster_id=GRAVEYARD,
        )

        assert result['adopt_vmids'] == []
        assert result['decommission_candidates'] == []

    def test_my_cluster_record_seen_nowhere_is_candidate(self):
        """Record in my cluster, vmid neither in inventory nor in
        cluster_resources -> decommission candidate."""
        mine = _nb_vm_with_cluster(11, 'web01', MY_CLUSTER, serial=100)
        nb_objects = _nb_objects_with([mine])

        result = pve2netbox.compute_reconcile_actions(
            nb_objects,
            inventory_vmids=set(),
            cluster_resource_vmids=set(),
            my_cluster_id=MY_CLUSTER,
            decommission_cluster_id=GRAVEYARD,
        )

        assert result['decommission_candidates'] == [100]
        assert result['adopt_vmids'] == []

    def test_other_live_cluster_records_are_ignored(self):
        """Records of a foreign live cluster produce no actions at all."""
        foreign_inventory = _nb_vm_with_cluster(21, 'web01', OTHER_LIVE, serial=100)
        foreign_missing = _nb_vm_with_cluster(22, 'db01', OTHER_LIVE, serial=200)
        nb_objects = _nb_objects_with([foreign_inventory, foreign_missing])

        result = pve2netbox.compute_reconcile_actions(
            nb_objects,
            inventory_vmids={100},  # foreign VM alive there, not here
            cluster_resource_vmids=set(),
            my_cluster_id=MY_CLUSTER,
            decommission_cluster_id=GRAVEYARD,
        )

        assert result == {'adopt_vmids': [], 'decommission_candidates': []}

    def test_non_numeric_serial_is_ignored(self):
        """A record with a non-numeric serial can't be mapped to a vmid."""
        weird = _nb_vm_with_cluster(31, 'weird', MY_CLUSTER, serial='not-a-number')
        nb_objects = _nb_objects_with([weird])

        result = pve2netbox.compute_reconcile_actions(
            nb_objects,
            inventory_vmids=set(),
            cluster_resource_vmids=set(),
            my_cluster_id=MY_CLUSTER,
            decommission_cluster_id=GRAVEYARD,
        )

        assert result == {'adopt_vmids': [], 'decommission_candidates': []}

    def test_duplicate_serials_are_ignored(self):
        """Serial collision (same serial on two records) -> never a candidate."""
        first = _nb_vm_with_cluster(41, 'web01', MY_CLUSTER, serial=100)
        second = _nb_vm_with_cluster(42, 'db01', MY_CLUSTER, serial=100)
        nb_objects = _nb_objects_with([first, second])

        result = pve2netbox.compute_reconcile_actions(
            nb_objects,
            inventory_vmids=set(),
            cluster_resource_vmids=set(),
            my_cluster_id=MY_CLUSTER,
            decommission_cluster_id=GRAVEYARD,
        )

        assert result == {'adopt_vmids': [], 'decommission_candidates': []}

    def test_function_is_pure(self):
        """Inputs are not mutated by compute_reconcile_actions."""
        buried = _nb_vm_with_cluster(12, 'web01', GRAVEYARD, serial=100)
        nb_objects = _nb_objects_with([buried])
        inventory = {100}
        resources = set()

        pve2netbox.compute_reconcile_actions(
            nb_objects, inventory, resources, MY_CLUSTER, GRAVEYARD,
        )

        assert inventory == {100}
        assert resources == set()


class TestAbsenceCounters:
    def test_bump_absence_increments_and_returns(self):
        """Repeated bumps return 1, 2, 3... per vmid, independently."""
        assert pve2netbox._bump_absence(100) == 1
        assert pve2netbox._bump_absence(100) == 2
        assert pve2netbox._bump_absence(100) == 3
        assert pve2netbox._bump_absence(200) == 1
        assert pve2netbox._bump_absence(100) == 4

    def test_counters_reset_by_pop(self):
        """Semantics: reset via _absence_counters.pop restarts the count."""
        assert pve2netbox._bump_absence(100) == 1
        assert pve2netbox._bump_absence(100) == 2
        popped = pve2netbox._absence_counters.pop(100)
        assert popped == 2
        assert 100 not in pve2netbox._absence_counters
        assert pve2netbox._bump_absence(100) == 1

    def test_counters_map_exposed(self):
        """_absence_counters is a plain dict mapping vmid -> count."""
        pve2netbox._bump_absence(300)
        pve2netbox._bump_absence(300)
        assert dict(pve2netbox._absence_counters) == {300: 2}


class FakeSaveableVM(FakeVM):
    """FakeVM already records save() calls; alias for readability."""

    def delete(self):
        raise AssertionError('decommission must never delete a VM')


class TestApplyDecommission:
    @pytest.fixture
    def nb_objects(self):
        return {
            'virtual_machines': {},
            'virtual_machines_duplicates': {},
            'virtual_machines_by_name_cluster': {},
        }

    def _add(self, nb_objects, vm):
        nb_objects['virtual_machines'][str(vm.serial)] = vm

    def test_dry_run_changes_nothing(self, nb_objects):
        """dry_run=True: no save(), no attribute changes, not counted."""
        vm = FakeSaveableVM(11, 'web01', MY_CLUSTER, serial=100)
        self._add(nb_objects, vm)

        moved = pve2netbox.apply_decommission(
            RecordingAPI(), nb_objects, [100], True,
        )

        assert moved == 0
        assert vm.save_calls == 0
        assert vm.cluster.id == MY_CLUSTER
        assert vm.device == 'keep'

    def test_real_run_moves_to_graveyard(self, nb_objects):
        """dry_run=False: cluster/decommissioning/device=None set and saved."""
        vm = FakeSaveableVM(11, 'web01', MY_CLUSTER, serial=100)
        self._add(nb_objects, vm)

        moved = pve2netbox.apply_decommission(
            RecordingAPI(), nb_objects, [100], False,
        )

        assert moved == 1
        assert vm.save_calls == 1
        assert vm.cluster == GRAVEYARD  # int after apply_decommission writes it
        assert vm.status == 'decommissioning'
        assert vm.device is None

    def test_save_failure_is_partial_success(self, nb_objects):
        """A VM whose save() raises is skipped without aborting the rest,
        and the function does not propagate the exception."""
        broken = FakeSaveableVM(11, 'broken', MY_CLUSTER, serial=100)

        def _boom():
            raise RuntimeError('netbox 500')

        broken.save = _boom
        healthy = FakeSaveableVM(12, 'healthy', MY_CLUSTER, serial=200)
        self._add(nb_objects, broken)
        self._add(nb_objects, healthy)

        moved = pve2netbox.apply_decommission(
            RecordingAPI(), nb_objects, [100, 200], False,
        )

        assert moved == 1  # only the healthy one
        assert healthy.save_calls == 1
        assert healthy.status == 'decommissioning'


class TestMigrationAToBPhases:
    """End-to-end (pure-function) scenario: VM migrates from cluster A to B.

    Phase 1: vmid already in B inventory, record still in cluster A -> skip.
    Phase 2: record moved to graveyard; A sees neither inventory nor resource
             -> decommission candidate from A's perspective.
    Phase 3: from B's perspective the graveyard record + B inventory -> adopt.
    """

    MY = 1  # cluster B (the side running this sync)
    OTHER = 2  # cluster A
    GRAVEYARD = 9

    def test_migration_a_to_b_phases(self):
        vmid = 100
        name = 'web01'

        # --- Phase 1: record still points to cluster A, VM already runs in B.
        record_in_a = _nb_vm_with_cluster(11, name, self.OTHER, serial=vmid)
        nb_objects = _nb_objects_with([record_in_a])

        result = pve2netbox.compute_reconcile_actions(
            nb_objects,
            inventory_vmids={vmid},
            cluster_resource_vmids=set(),
            my_cluster_id=self.MY,
            decommission_cluster_id=self.GRAVEYARD,
        )
        assert result == {'adopt_vmids': [], 'decommission_candidates': []}

        # --- Phase 2: cluster A no longer has the vmid in its inventory nor in
        # its cluster resources, and the record is still in cluster A
        # (run from A's side) -> decommission candidate.
        record_still_in_a = _nb_vm_with_cluster(11, name, self.OTHER, serial=vmid)
        nb_objects = _nb_objects_with([record_still_in_a])

        result = pve2netbox.compute_reconcile_actions(
            nb_objects,
            inventory_vmids=set(),  # inventory A without vmid
            cluster_resource_vmids=set(),  # cluster_resources without vmid
            my_cluster_id=self.OTHER,  # running from A's side
            decommission_cluster_id=self.GRAVEYARD,
        )
        assert result['adopt_vmids'] == []
        assert result['decommission_candidates'] == [vmid]

        # --- Phase 3: from B's side, the record has been moved to the
        # graveyard (by A's decommission pass) and B's inventory has the
        # vmid -> adopt.
        record_in_graveyard = _nb_vm_with_cluster(11, name, self.GRAVEYARD, serial=vmid)
        nb_objects = _nb_objects_with([record_in_graveyard])

        result = pve2netbox.compute_reconcile_actions(
            nb_objects,
            inventory_vmids={vmid},
            cluster_resource_vmids=set(),
            my_cluster_id=self.MY,
            decommission_cluster_id=self.GRAVEYARD,
        )
        assert vmid in result['adopt_vmids']
