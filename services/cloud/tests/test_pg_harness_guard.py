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
        if isinstance(self.info, Exception):
            raise self.info
        if self.info is None:
            raise LookupError(name)
        return self.info

    def remove(self, name):
        self.removed.append(name)
        self.info = None


def container_info(run_id="a1b2c3d4e5f60718", container_id="1" * 64, host_ip="127.0.0.1", host_port="54321"):
    return {
        "Id": container_id,
        "Name": "/" + harness.container_name(run_id),
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
    resources = harness.RunResources(run_id=run_id, container=harness.container_name(run_id), container_id="1" * 64)
    docker = FakeDocker(container_info(run_id))
    harness.resolve_host_port(docker, resources)
    assert resources.host_port == 54321

    foreign = FakeDocker(container_info("ffffffffffffffff"))
    with pytest.raises(harness.HarnessError):
        harness.resolve_host_port(foreign, resources)

    exposed = FakeDocker(container_info(run_id, host_ip="0.0.0.0"))
    with pytest.raises(harness.HarnessError):
        harness.resolve_host_port(exposed, resources)

    mismatched = FakeDocker(container_info(run_id, container_id="2" * 64))
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


def test_missing_run_file_cannot_confirm_absence(tmp_path):
    code, report = harness.cleanup_from_run_file(FakeDocker(None), tmp_path / "missing.json")
    assert code != 0 and report["status"] == "error:no-run-file"


def test_unavailable_docker_fails_without_sqlite_fallback(monkeypatch):
    monkeypatch.setattr(harness.shutil, "which", lambda _: None)
    with pytest.raises(harness.HarnessError):
        harness.resolve_docker()

    monkeypatch.setattr(harness.shutil, "which", lambda _: "/usr/local/bin/docker")
    monkeypatch.setattr(harness.Docker, "daemon_ready", lambda self: False)
    with pytest.raises(harness.HarnessError):
        harness.resolve_docker()


@pytest.mark.parametrize('stderr,missing', [
    ('Error: No such object: target', True),
    ('error: no such object: target', True),
    ('Cannot connect to the Docker daemon', False),
    ('permission denied', False),
    ('Error: No such object: other', False),
])
def test_inspect_only_explicit_missing_object_is_absent(monkeypatch, stderr, missing):
    import subprocess
    monkeypatch.setattr(harness.Docker, '_run', lambda *a, **kw: subprocess.CompletedProcess([], 1, '', stderr))
    with pytest.raises(LookupError if missing else harness.HarnessError):
        harness.Docker().inspect('target')


@pytest.mark.parametrize('output', ['[]', '{}', 'invalid-json'])
def test_inspect_malformed_success_is_not_absent(monkeypatch, output):
    import subprocess
    monkeypatch.setattr(harness.Docker, '_run', lambda *a, **kw: subprocess.CompletedProcess([], 0, output, ''))
    with pytest.raises(harness.HarnessError):
        harness.Docker().inspect('target')


def test_docker_rm_failure_raises(monkeypatch):
    import subprocess
    monkeypatch.setattr(harness.Docker, '_run', lambda *a, **kw: subprocess.CompletedProcess([], 125, '', 'rm failed'))
    with pytest.raises(harness.HarnessError, match='删除容器失败'):
        harness.Docker().remove('target')


def test_postgresql_junit_uses_record_property_compatible_family(monkeypatch, tmp_path):
    import subprocess
    captured = {}

    def run(command, **kwargs):
        captured['command'] = command
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(harness.subprocess, 'run', run)
    junit = tmp_path / 'pg-junit.xml'
    basetemp = tmp_path / 'pg-temp'
    assert harness.run_pytest({}, junit, basetemp, []) == 0
    command = captured['command']
    option_index = command.index('junit_family=xunit1')
    assert command[option_index - 1] == '-o'


class CleanupFailureDocker(FakeDocker):
    def __init__(self, problem):
        super().__init__(container_info())
        self.problem = problem
        self.testing_finished = False
        self.removal_attempted = False

    def inspect(self, name):
        if self.testing_finished:
            if self.problem == 'inspect-daemon':
                raise harness.HarnessError('Cannot connect to Docker daemon')
            if self.problem == 'label':
                info = container_info()
                info['Config']['Labels'][harness.LABEL_RUN] = 'f' * 16
                return info
            if self.removal_attempted and self.problem == 'confirm-daemon':
                raise harness.HarnessError('cannot confirm deletion: daemon unavailable')
        return super().inspect(name)

    def remove(self, name):
        self.removal_attempted = True
        if self.problem == 'rm':
            raise harness.HarnessError('rm failed')
        if self.problem != 'unverified':
            super().remove(name)


@pytest.mark.parametrize('problem', ['rm', 'inspect-daemon', 'label', 'unverified', 'confirm-daemon'])
def test_cleanup_failure_propagates_nonzero_and_consistent_summary(monkeypatch, tmp_path, problem):
    docker = CleanupFailureDocker(problem)
    monkeypatch.setattr(harness, 'resolve_docker', lambda: docker)
    docker.image_present = lambda _: True
    docker.run_container = lambda **kw: '1' * 64
    docker.image_details = lambda _: {}
    monkeypatch.setattr(harness, 'new_run_id', lambda: 'a1b2c3d4e5f60718')
    monkeypatch.setattr(harness, 'wait_until_ready', lambda *a: None)
    monkeypatch.setattr(harness, 'source_version', lambda *a: {})
    monkeypatch.setattr(harness, 'bootstrap_roles', lambda *a: {harness.MIGRATION_USER: 'test', harness.APP_USER: 'test'})
    monkeypatch.setattr(harness, 'CLEANUP_CONFIRM_SECONDS', 0)

    def tests_pass(*args):
        docker.testing_finished = True
        return 0

    monkeypatch.setattr(harness, 'run_pytest', tests_pass)
    summary_path = tmp_path / 'summary.json'
    code = harness.main(['--summary', str(summary_path), '--run-file', str(tmp_path / 'run.json')])
    summary = json.loads(summary_path.read_text())
    assert code != 0
    assert summary['pytest_exit_code'] == 0
    assert summary['exit_code'] == code
    assert summary['result'] == 'failed'
    assert summary['cleanup'] not in {'removed', 'absent'}

    # 同一个失败也必须从 CI always cleanup-run-file 的入口返回非零。
    docker = CleanupFailureDocker(problem)
    docker.testing_finished = True
    monkeypatch.setattr(harness, 'resolve_docker', lambda: docker)
    assert harness.main(['--cleanup-run-file', str(tmp_path / 'run.json')]) != 0


@pytest.mark.parametrize('present', [True, False])
def test_cleanup_run_file_success_requires_verified_removal_or_absence(monkeypatch, tmp_path, present):
    docker = FakeDocker(container_info() if present else None)
    monkeypatch.setattr(harness, 'resolve_docker', lambda: docker)
    path = tmp_path / 'run.json'
    path.write_text(json.dumps({'run_id': 'a1b2c3d4e5f60718', 'container': harness.container_name('a1b2c3d4e5f60718')}))
    assert harness.main(['--cleanup-run-file', str(path)]) == 0


def valid_pg_environment():
    from pg_support import ENV_KEYS
    values = dict(run='a1b2c3d4e5f60718', host='127.0.0.1', port='54321',
                  container_id='1' * 64, container_name='swim-pg-test-a1b2c3d4e5f60718',
                  owner=harness.OWNER_VALUE, admin_user='swim_admin', migration_user='swim_migrator',
                  app_user='swim_app', admin_password='test', migration_password='test', app_password='test')
    return {ENV_KEYS[key]: value for key, value in values.items()}


@pytest.mark.parametrize('problem', ['absent', 'daemon', 'id', 'name', 'run', 'owner', 'port', 'exposed', 'stopped'])
def test_environment_rejects_forged_target_before_database_connection(monkeypatch, problem):
    import psycopg
    from pg_support import PgEnvironment, PostgresEnvironmentError, harness_module
    module = harness_module()
    info = container_info()
    if problem == 'absent':
        info = None
    elif problem == 'daemon':
        info = module.HarnessError('daemon unavailable')
    elif problem == 'id':
        info['Id'] = '2' * 64
    elif problem == 'name':
        info['Name'] = '/other-container'
    elif problem in {'run', 'owner'}:
        info['Config']['Labels'][module.LABEL_RUN if problem == 'run' else module.LABEL_OWNER] = 'foreign'
    elif problem == 'port':
        info['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort'] = '54322'
    elif problem == 'exposed':
        info['NetworkSettings']['Ports']['5432/tcp'][0]['HostIp'] = '0.0.0.0'
    else:
        info['State']['Running'] = False
    monkeypatch.setattr(module, 'resolve_docker', lambda: FakeDocker(info))
    connections = []
    monkeypatch.setattr(psycopg, 'connect', lambda *a, **kw: connections.append(kw))
    with pytest.raises(PostgresEnvironmentError, match='拒绝数据库连接'):
        PgEnvironment.from_environment(valid_pg_environment())
    assert connections == []


def test_pytest_initialization_rejects_complete_environment_without_container(monkeypatch):
    import conftest
    import psycopg
    import subprocess
    from pg_support import PostgresEnvironmentError, harness_module
    module = harness_module()
    monkeypatch.setattr(module.shutil, 'which', lambda _: '/fake/docker')
    def docker_cli(self, *args, **kwargs):
        if args[0] == 'info':
            return subprocess.CompletedProcess([], 0, '{}', '')
        return subprocess.CompletedProcess([], 1, '', 'Error: No such object: swim-pg-test-a1b2c3d4e5f60718')
    monkeypatch.setattr(module.Docker, '_run', docker_cli)
    for key, value in valid_pg_environment().items():
        monkeypatch.setenv(key, value)
    connections = []
    monkeypatch.setattr(psycopg, 'connect', lambda *a, **kw: connections.append(kw))
    class Config:
        stash = {}
        def addinivalue_line(self, *a): pass
        def getoption(self, *a): return 'postgresql'
    with pytest.raises(PostgresEnvironmentError):
        conftest.pytest_configure(Config())
    assert connections == []


def test_environment_accepts_matching_live_container(monkeypatch):
    from pg_support import PgEnvironment, harness_module
    monkeypatch.setattr(harness_module(), 'resolve_docker', lambda: FakeDocker(container_info()))
    env = PgEnvironment.from_environment(valid_pg_environment())
    assert env.container_id == '1' * 64 and env.port == 54321


@pytest.mark.parametrize('problem', ['rm', 'inspect-daemon', 'label', 'unverified', 'confirm-daemon'])
def test_ci_cleanup_command_exits_nonzero_on_failure(tmp_path, problem):
    """实际启动CLI子进程，Docker用本例专属可执行替身，不访问真实daemon。"""
    import os
    import subprocess
    fake = tmp_path / 'docker'
    info = container_info()
    fake.write_text('#!' + sys.executable + '\n' + f'''
import json, sys
from pathlib import Path
problem = {problem!r}
info = {info!r}
state = Path({str(tmp_path / 'removed')!r})
command = sys.argv[1]
if command == 'info':
    raise SystemExit(0)
if command == 'rm':
    if problem == 'rm':
        print('rm failed', file=sys.stderr)
        raise SystemExit(1)
    state.touch()
    raise SystemExit(0)
if command == 'inspect':
    if problem == 'inspect-daemon' or (state.exists() and problem == 'confirm-daemon'):
        print('Cannot connect to Docker daemon', file=sys.stderr)
        raise SystemExit(1)
    if problem == 'label':
        info['Config']['Labels'][{harness.LABEL_RUN!r}] = 'foreign'
    print(json.dumps([info]))
    raise SystemExit(0)
raise SystemExit(1)
''')
    fake.chmod(0o700)
    record = tmp_path / 'run.json'
    record.write_text(json.dumps({'run_id': 'a1b2c3d4e5f60718', 'container': harness.container_name('a1b2c3d4e5f60718')}))
    environment = {**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ.get('PATH', '')}
    result = subprocess.run([sys.executable, str(HARNESS_PATH), '--cleanup-run-file', str(record)],
                            env=environment, capture_output=True, text=True, timeout=15)
    assert result.returncode != 0, result.stdout
    report = json.loads(result.stdout)
    assert report['result'] == 'failed' and report['exit_code'] == result.returncode
    assert report['cleanup'] not in {'removed', 'absent'}
