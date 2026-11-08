"""PG完整验证必须真的收集并执行共享与PG专属两类，独立于总数下限。"""
from types import SimpleNamespace
import pytest
import conftest


class Item:
    def __init__(self, name, kind):
        self.nodeid, self.kind = name, kind
    def get_closest_marker(self, marker):
        return self.kind == marker
    def add_marker(self, marker):
        pass


class Config:
    def __init__(self, minimum):
        self.stash = {}
        self.minimum = minimum
        self.pluginmanager = SimpleNamespace(get_plugin=lambda _: None)
    def getoption(self, key):
        return 'postgresql' if key == '--cloud-backend' else self.minimum


@pytest.mark.parametrize('shared,pg,sqlite,state,minimum,expected', [
    (0, 0, 0, 'passed', 80, 1),
    (80, 0, 0, 'passed', 80, 1),
    (0, 80, 0, 'passed', 80, 1),
    (40, 39, 0, 'passed', 80, 1),
    (40, 40, 1, 'passed', 80, 0),
    (40, 40, 0, 'skipped', 80, 1),
    (40, 40, 0, 'failed', 80, 1),
    (40, 40, 0, 'error', 80, 1),
    (40, 40, 0, 'collected', 80, 1),
    (1, 0, 0, 'passed', 0, 1),
    (0, 1, 0, 'passed', 0, 1),
    (1, 1, 0, 'passed', 0, 0),
])
def test_complete_pg_run_requires_both_categories_and_all_passed(shared, pg, sqlite, state, minimum, expected):
    config = Config(minimum)
    items = [Item(f'{kind}-{i}', kind) for kind, count in [('shared', shared), ('postgresql', pg), ('sqlite', sqlite)] for i in range(count)]
    conftest.pytest_collection_modifyitems(config, items)
    ledger = config.stash[conftest.PG_LEDGER]
    assert len(ledger) == shared + pg
    for nodeid in ledger:
        ledger[nodeid] = 'passed'
    if ledger:
        ledger[next(iter(ledger))] = state
    session = SimpleNamespace(config=config, exitstatus=0)
    conftest.pytest_sessionfinish(session, 0)
    assert int(session.exitstatus) == expected
