"""专用 PostgreSQL 编排入口的安全边界检查（不需要 Docker 或数据库）。

对应 design D1：外部目标拒绝、镜像锁定、run id 校验、清理范围。
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

HARNESS_PATH = Path(__file__).resolve().parents[3] / "scripts" / "test-postgresql.py"


def load_harness():
    # 文件名带连字符，只能按路径加载；需先登记到 sys.modules，dataclass 才能解析类型注解。
    spec = importlib.util.spec_from_file_location("pg_harness", HARNESS_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["pg_harness"] = module
    spec.loader.exec_module(module)
    return module


harness = load_harness()


class FakeDocker:
    """只实现编排入口用到的 inspect / remove，用于断言删除范围。"""

    def __init__(self, info):
        self.info = info
        self.removed = []

    def inspect(self, name):
        if self.info is None or isinstance(self.info, Exception):
            raise LookupError(name)
        return self.info

    def remove(self, name):
        self.removed.append(name)
        self.info = None


def container_info(run_id="a1b2c3d4e5f60718", container_id="cid-1", host_ip="127.0.0.1", host_port="54321"):
    return {
        "Id": container_id,
        "Config": {"Labels": {harness.LABEL_RUN: run_id, harness.LABEL_OWNER: harness.OWNER_VALUE}},
        "State": {"Running": True},
        "NetworkSettings": {"Ports": {"5432/tcp": [{"HostIp": host_ip, "HostPort": host_port}]}},
    }


def test_configured_image_lock_is_pinned_to_postgres_17_index_digest():
    lock = harness.load_image_lock()
    assert lock.major_version == 17
    assert lock.reference.startswith("postgres:17.")
    # 必须锁多架构清单 digest，才能同时覆盖本机 arm64 与 CI amd64。
    assert lock.reference.endswith("@" + lock.digest)
    assert len(lock.digest) == len("sha256:") + 64


@pytest.mark.parametrize(
    "payload",
    [
        {"repository": "postgres", "tag": "17", "digest": "sha256:" + "0" * 64, "major_version": 17},
        {"repository": "postgres", "tag": "latest", "digest": "sha256:" + "0" * 64, "major_version": 17},
        {"repository": "postgres", "tag": "16.4", "digest": "sha256:" + "0" * 64, "major_version": 17},
        {"repository": "postgres", "tag": "17.11", "digest": "sha256:short", "major_version": 17},
        {"repository": "postgres", "tag": "17.11", "digest": "sha256:" + "0" * 64, "major_version": 16},
        {"repository": "../evil", "tag": "17.11", "digest": "sha256:" + "0" * 64, "major_version": 17},
    ],
)
def test_image_lock_rejects_unpinned_or_non_pg17_targets(tmp_path, payload):
    path = tmp_path / "image.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(harness.HarnessError):
        harness.load_image_lock(path)


def test_entry_point_has_no_database_url_option():
    parser = harness.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--database-url", "postgresql://someone@example.test/prod"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--url", "postgresql://someone@example.test/prod"])


def test_environment_drops_business_dsn_and_all_libpq_variables():
    source = {
        "PATH": "/usr/bin",
        "HOME": "/home/test",
        "SWIM_CLOUD_DATABASE_URL": "postgresql://app@production/db",
        "DATABASE_URL": "postgresql://app@production/db",
        "PGHOST": "production",
        "PGPASSWORD": "secret",
        "PGSERVICE": "business",
        "PGSERVICEFILE": "/tmp/pg_service.conf",
        "PGPASSFILE": "/tmp/.pgpass",
        "PGOPTIONS": "-c search_path=public",
        "SWIM_CLOUD_PG_HARNESS_RUN": "a1b2c3d4e5f60718",
    }
    cleaned = harness.sanitized_environment(source)
    assert cleaned["PATH"] == "/usr/bin" and cleaned["HOME"] == "/home/test"
    assert cleaned["SWIM_CLOUD_PG_HARNESS_RUN"] == "a1b2c3d4e5f60718"
    for removed in ("SWIM_CLOUD_DATABASE_URL", "DATABASE_URL", "PGHOST", "PGPASSWORD", "PGSERVICE", "PGSERVICEFILE", "PGPASSFILE", "PGOPTIONS"):
        assert removed not in cleaned
    # 被忽略的变量必须在摘要里如实列出，便于报告说明“业务连接不能成为测试目标”。
    assert "SWIM_CLOUD_DATABASE_URL" in harness.ignored_connection_keys(source)
    assert "PGSERVICE" in harness.ignored_connection_keys(source)


def test_run_id_and_container_name_are_validated():
    run_id = harness.new_run_id()
    assert harness.RUN_ID_PATTERN.match(run_id)
    assert harness.container_name(run_id) == f"swim-pg-test-{run_id}"
    for bad in ("", "../x", "a1b2c3d4e5f6071", "A1B2C3D4E5F60718", "a1b2c3d4e5f60718\n"):
        with pytest.raises(harness.HarnessError):
            harness.container_name(bad)


def test_host_port_resolution_requires_own_container_and_loopback():
    run_id = "a1b2c3d4e5f60718"
    resources = harness.RunResources(run_id=run_id, container=harness.container_name(run_id))
    docker = FakeDocker(container_info(run_id))
    harness.resolve_host_port(docker, resources)
    assert resources.host_port == 54321

    foreign = FakeDocker(container_info("ffffffffffffffff"))
    with pytest.raises(harness.HarnessError):
        harness.resolve_host_port(foreign, resources)

    exposed = FakeDocker(container_info(run_id, host_ip="0.0.0.0"))
    with pytest.raises(harness.HarnessError):
        harness.resolve_host_port(exposed, resources)

    mismatched = FakeDocker(container_info(run_id, container_id="cid-2"))
    resources.container_id = "cid-1"
    with pytest.raises(harness.HarnessError):
        harness.resolve_host_port(mismatched, resources)


def test_cleanup_only_removes_its_own_container():
    run_id = "a1b2c3d4e5f60718"
    name = harness.container_name(run_id)

    own = FakeDocker(container_info(run_id))
    assert harness.cleanup_container(own, name, run_id) == "removed"
    assert own.removed == [name]

    foreign = FakeDocker(container_info("ffffffffffffffff"))
    assert harness.cleanup_container(foreign, name, run_id) == "refused:label-mismatch"
    assert foreign.removed == []

    absent = FakeDocker(None)
    assert harness.cleanup_container(absent, name, run_id) == "absent"
    assert absent.removed == []


def test_cleanup_from_run_file_rejects_forged_or_mismatched_records(tmp_path):
    run_id = "a1b2c3d4e5f60718"
    docker = FakeDocker(container_info(run_id))

    good = tmp_path / "good.json"
    good.write_text(json.dumps({"run_id": run_id, "container": harness.container_name(run_id)}), encoding="utf-8")
    code, report = harness.cleanup_from_run_file(docker, good)
    assert code == 0 and report["status"] == "removed"

    for payload in (
        {"run_id": run_id, "container": "swim-test-some-other-container"},
        {"run_id": "not-a-run-id", "container": "swim-pg-test-not-a-run-id"},
        {"run_id": run_id, "container": "postgres"},
    ):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(harness.HarnessError):
            harness.cleanup_from_run_file(FakeDocker(container_info(run_id)), path)


def test_missing_run_file_is_not_an_error(tmp_path):
    code, report = harness.cleanup_from_run_file(FakeDocker(None), tmp_path / "missing.json")
    assert code == 0 and report["status"] == "no-run-file"


def test_unavailable_docker_fails_without_sqlite_fallback(monkeypatch):
    monkeypatch.setattr(harness.shutil, "which", lambda _: None)
    with pytest.raises(harness.HarnessError):
        harness.resolve_docker()

    monkeypatch.setattr(harness.shutil, "which", lambda _: "/usr/local/bin/docker")
    monkeypatch.setattr(harness.Docker, "daemon_ready", lambda self: False)
    with pytest.raises(harness.HarnessError):
        harness.resolve_docker()
