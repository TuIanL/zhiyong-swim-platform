#!/usr/bin/env python3
"""专用 PostgreSQL 17 测试编排（change `validate-cloud-foundation-postgresql` 的 D1/D2）。

安全边界（实现见下方 `guard_*`/`sanitized_environment`）：
- 命令行不提供任何数据库地址参数；连接目标只能来自本次创建的临时容器。
- 忽略并从子进程环境剔除 `SWIM_CLOUD_DATABASE_URL` 与全部 `PG*` 变量，避免本机已有
  libpq 配置或业务连接把测试指向其他数据库。
- 连接前用 container ID、run id label 与回环端口三者交叉校验目标归属；
  “数据库名带 test 前缀”不被当作安全凭据。
- 清理只按本次 run id 精确删除，不做全局 prune。

用法：
    python scripts/test-postgresql.py                    # 完整验证（生成 JUnit 与摘要）
    python scripts/test-postgresql.py --dev-select ...    # 仅本机迭代，不构成证据
    python scripts/test-postgresql.py --cleanup-run-file var/pg-test-run.json

不可捕获终止（SIGKILL、宿主崩溃）无法保证脚本即时清理。恢复方法：
    1. docker ps -a --filter label=com.zhiyong.swim-pg-test.run --format '{{.Names}}'
    2. 逐条确认容器名符合 `swim-pg-test-<16位十六进制>` 且不再需要后执行
       docker rm --force <容器名>
    不执行 `docker system prune` 或按镜像统删，避免影响其他项目。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
IMAGE_CONFIG = ROOT / "configs" / "postgresql-test-image.json"
DEFAULT_JUNIT = ROOT / "var" / "postgresql-junit.xml"
DEFAULT_SUMMARY = ROOT / "var" / "postgresql-validation-summary.json"
DEFAULT_RUN_FILE = ROOT / "var" / "pg-test-run.json"
DEFAULT_INSTANCE_LOG = ROOT / "var" / "postgresql-instance.log"

LABEL_RUN = "com.zhiyong.swim-pg-test.run"
LABEL_OWNER = "com.zhiyong.swim-pg-test.owner"
OWNER_VALUE = "zhiyong-swim-platform"

RUN_ID_PATTERN = re.compile(r"^[0-9a-f]{16}\Z")
CONTAINER_PATTERN = re.compile(r"^swim-pg-test-[0-9a-f]{16}\Z")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}\Z")
# 必须落到具体补丁版本（如 17.11）；裸 17 或 latest 都不接受。
TAG_PATTERN = re.compile(r"^17\.\d+(?:\.\d+)?(?:-[a-z0-9.]+)?\Z")
REPOSITORY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._/-]*\Z")

ADMIN_USER = "swim_admin"
MIGRATION_USER = "swim_migrator"
APP_USER = "swim_app"

# 子进程里必须剔除的变量：业务连接与 libpq 默认配置。
STRIPPED_ENV_KEYS = ("SWIM_CLOUD_DATABASE_URL", "DATABASE_URL", "SQLALCHEMY_DATABASE_URI")
STRIPPED_ENV_PREFIXES = ("PG",)

# 允许 pytest 至少收集到的 PostgreSQL 必需场景数（全部非 sqlite 用例）。
# 当前实际为 86；下限用于发现“零收集/大批用例被跳过”这类静默退化。
MINIMUM_PG_SCENARIOS = 80


class HarnessError(RuntimeError):
    """编排本身失败（容器、镜像、身份或清理），与业务断言失败区分。"""


class Terminated(Exception):
    """收到终止信号；由 main 统一转为非零退出并执行清理。"""


class ImageLock:
    """从 `configs/postgresql-test-image.json` 解析出的固定镜像引用。"""

    __slots__ = ("repository", "tag", "digest", "major_version")

    def __init__(self, repository: str, tag: str, digest: str, major_version: int):
        self.repository = repository
        self.tag = tag
        self.digest = digest
        self.major_version = major_version

    @property
    def reference(self) -> str:
        return f"{self.repository}:{self.tag}@{self.digest}"

    def describe(self) -> dict:
        return {
            "reference": self.reference,
            "repository": self.repository,
            "tag": self.tag,
            "digest": self.digest,
            "major_version": self.major_version,
        }


def load_image_lock(path: Path = IMAGE_CONFIG) -> ImageLock:
    """读取并校验镜像锁定配置；任何未固定或非 PostgreSQL 17 的取值都拒绝。"""
    if not path.is_file():
        raise HarnessError(f"缺少镜像锁定配置：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise HarnessError(f"镜像锁定配置不是合法 JSON：{error}") from error
    if not isinstance(data, dict):
        raise HarnessError("镜像锁定配置必须是对象")

    repository = str(data.get("repository", ""))
    tag = str(data.get("tag", ""))
    digest = str(data.get("digest", ""))
    major_version = data.get("major_version")

    if not REPOSITORY_PATTERN.match(repository):
        raise HarnessError(f"镜像仓库名非法：{repository!r}")
    if not TAG_PATTERN.match(tag):
        raise HarnessError(f"镜像标签必须固定到 PostgreSQL 17 的具体补丁版本：{tag!r}")
    if not DIGEST_PATTERN.match(digest):
        raise HarnessError(f"镜像 digest 未固定或格式非法：{digest!r}")
    if major_version != 17:
        raise HarnessError(f"本 change 只验证 PostgreSQL 17，配置为 {major_version!r}")
    return ImageLock(repository, tag, digest, major_version)


def new_run_id() -> str:
    return secrets.token_hex(8)


def container_name(run_id: str) -> str:
    if not RUN_ID_PATTERN.match(run_id):
        raise HarnessError(f"run id 非法：{run_id!r}")
    return f"swim-pg-test-{run_id}"


def sanitized_environment(source: Mapping[str, str]) -> dict[str, str]:
    """构造子进程环境：剔除业务连接串与全部 libpq 默认变量。

    返回值中不会包含 `SWIM_CLOUD_DATABASE_URL`，也不会包含任何 `PG*` 变量，
    因此子进程无法通过环境继承到本机其他数据库的连接配置。
    """
    cleaned: dict[str, str] = {}
    for key, value in source.items():
        if key in STRIPPED_ENV_KEYS:
            continue
        if any(key.startswith(prefix) for prefix in STRIPPED_ENV_PREFIXES):
            continue
        cleaned[key] = value
    return cleaned


def ignored_connection_keys(source: Mapping[str, str]) -> list[str]:
    """列出被忽略的连接相关变量名，供报告说明“业务连接不能成为测试目标”。"""
    return sorted(
        key
        for key in source
        if key in STRIPPED_ENV_KEYS or any(key.startswith(prefix) for prefix in STRIPPED_ENV_PREFIXES)
    )


def generate_password() -> str:
    return secrets.token_urlsafe(24)


@dataclass
class RunResources:
    """本次运行创建的资源；只有这里的容器允许被删除。"""

    run_id: str
    container: str
    container_id: str | None = None
    host_port: int | None = None
    image_reference: str | None = None

    def to_file_payload(self) -> dict:
        return {
            "run_id": self.run_id,
            "container": self.container,
            "container_id": self.container_id,
            "image": self.image_reference,
            "created_at": datetime.now(UTC).isoformat(),
        }


class Docker:
    """极薄的 docker CLI 封装；所有参数显式传入，不拼接 shell。"""

    def __init__(self, executable: str = "docker"):
        self.executable = executable

    def _run(self, *args: str, check: bool = True, stdin: str | None = None) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [self.executable, *args],
            capture_output=True,
            text=True,
            input=stdin,
        )
        if check and result.returncode != 0:
            raise HarnessError(
                f"docker {' '.join(args[:2])} 失败（退出码 {result.returncode}）：{result.stderr.strip()}"
            )
        return result

    def daemon_ready(self) -> bool:
        return self._run("info", check=False).returncode == 0

    def image_present(self, reference: str) -> bool:
        return self._run("image", "inspect", reference, check=False).returncode == 0

    def pull(self, reference: str) -> None:
        self._run("pull", reference)

    def inspect(self, name: str) -> dict:
        result = self._run("inspect", name, check=False)
        if result.returncode != 0:
            raise LookupError(name)
        payload = json.loads(result.stdout)
        if not payload:
            raise LookupError(name)
        return payload[0]

    def run_container(self, *, name: str, run_id: str, reference: str, admin_password: str) -> str:
        args = [
            "run", "--detach",
            "--name", name,
            "--label", f"{LABEL_RUN}={run_id}",
            "--label", f"{LABEL_OWNER}={OWNER_VALUE}",
            # 仅绑定回环地址，端口由内核随机分配；不暴露到局域网。
            "--publish", "127.0.0.1::5432",
            # 数据与 socket 放临时内存卷，容器销毁即消失，不挂载宿主目录。
            "--tmpfs", "/var/lib/postgresql/data:rw",
            "--tmpfs", "/var/run/postgresql:rw",
            "--env", "POSTGRES_DB=postgres",
            "--env", f"POSTGRES_USER={ADMIN_USER}",
            "--env", f"POSTGRES_PASSWORD={admin_password}",
            reference,
        ]
        result = self._run(*args)
        return result.stdout.strip()

    def exec(self, name: str, *command: str, check: bool = True) -> subprocess.CompletedProcess:
        return self._run("exec", name, *command, check=check)

    def logs(self, name: str, tail: int = 200) -> str:
        result = self._run("logs", "--tail", str(tail), name, check=False)
        return (result.stdout or "") + (result.stderr or "")

    def image_details(self, reference: str) -> dict:
        result = self._run("image", "inspect", reference, check=False)
        if result.returncode != 0:
            return {}
        payload = json.loads(result.stdout)
        return payload[0] if payload else {}

    def remove(self, name: str) -> None:
        # 注意是 `docker rm`；用错子命令时退出码 125 必须显式失败，不能静默残留。
        result = self._run("rm", "--force", name, check=False)
        if result.returncode != 0:
            raise HarnessError(
                f"删除容器失败（退出码 {result.returncode}）：{result.stderr.strip()}"
            )


def resolve_docker() -> Docker:
    executable = shutil.which("docker")
    if not executable:
        raise HarnessError("未找到 docker CLI；本入口只支持 Docker 提供的专用实例")
    docker = Docker(executable)
    if not docker.daemon_ready():
        raise HarnessError("Docker daemon 不可用；无法创建专用实例，测试不会回退到 SQLite")
    return docker


def resolve_host_port(docker: Docker, resources: RunResources) -> dict:
    """连接前核验容器归属：ID、run id label、回环绑定与目标端口。"""
    info = docker.inspect(resources.container)
    labels = (info.get("Config") or {}).get("Labels") or {}
    if labels.get(LABEL_RUN) != resources.run_id:
        raise HarnessError("容器 run id label 与本次运行不匹配，拒绝连接")
    if labels.get(LABEL_OWNER) != OWNER_VALUE:
        raise HarnessError("容器 owner label 与本次运行不匹配，拒绝连接")
    if resources.container_id and info.get("Id") != resources.container_id:
        raise HarnessError("容器 ID 与创建结果不一致，拒绝连接")
    if not (info.get("State") or {}).get("Running"):
        raise HarnessError("容器未处于运行状态")

    bindings = ((info.get("NetworkSettings") or {}).get("Ports") or {}).get("5432/tcp") or []
    if len(bindings) != 1:
        raise HarnessError(f"期望恰好一个端口映射，实际 {len(bindings)} 个")
    binding = bindings[0]
    if binding.get("HostIp") != "127.0.0.1":
        raise HarnessError(f"端口未绑定回环地址：{binding.get('HostIp')!r}")
    try:
        host_port = int(binding["HostPort"])
    except (KeyError, TypeError, ValueError) as error:
        raise HarnessError("端口映射缺少可用 HostPort") from error
    if not 1024 <= host_port <= 65535:
        raise HarnessError(f"HostPort 超出预期范围：{host_port}")

    resources.host_port = host_port
    return info


def wait_until_ready(docker: Docker, resources: RunResources, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = docker.exec(
            resources.container,
            "pg_isready", "--host=127.0.0.1", "--port=5432",
            f"--username={ADMIN_USER}", "--dbname=postgres",
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(0.4)
    raise HarnessError(f"实例在 {timeout:.0f}s 内未就绪")


def bootstrap_roles(host: str, port: int, admin_password: str) -> dict[str, str]:
    """创建迁移身份与最小权限应用身份；凭据只存在于本次进程内存。"""
    import psycopg
    from psycopg import sql

    passwords = {MIGRATION_USER: generate_password(), APP_USER: generate_password()}
    with psycopg.connect(
        host=host, port=port, user=ADMIN_USER, password=admin_password,
        dbname="postgres", autocommit=True,
    ) as connection:
        for role in (MIGRATION_USER, APP_USER):
            # 角色名与密码都走标识符/字面量转义，不拼接原始字符串。
            connection.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD {} "
                    "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                ).format(sql.Identifier(role), sql.Literal(passwords[role]))
            )
    return passwords


def cleanup_container(docker: Docker, name: str, run_id: str) -> str:
    """只删除本次容器；label 不匹配时拒绝并如实返回原因。"""
    try:
        info = docker.inspect(name)
    except LookupError:
        return "absent"
    labels = (info.get("Config") or {}).get("Labels") or {}
    if labels.get(LABEL_RUN) != run_id:
        return "refused:label-mismatch"
    if labels.get(LABEL_OWNER) != OWNER_VALUE:
        return "refused:owner-mismatch"
    try:
        docker.remove(name)
    except HarnessError as error:
        return f"error:{error}"
    # 删除后短暂重试确认，避免把 Docker 的瞬时视图当成残留。
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            docker.inspect(name)
        except LookupError:
            return "removed"
        time.sleep(0.2)
    return "removed:unverified"


def cleanup_from_run_file(docker: Docker, path: Path) -> tuple[int, dict]:
    """CI 的 always 兜底清理：只按记录在案的 run id 精确删除。"""
    if not path.is_file():
        return 0, {"status": "no-run-file", "path": str(path)}
    payload = json.loads(path.read_text(encoding="utf-8"))
    run_id = str(payload.get("run_id", ""))
    name = str(payload.get("container", ""))
    if not RUN_ID_PATTERN.match(run_id) or not CONTAINER_PATTERN.match(name):
        raise HarnessError(f"运行记录非法，拒绝清理：{path}")
    if name != container_name(run_id):
        raise HarnessError("运行记录中的容器名与 run id 不一致，拒绝清理")
    status = cleanup_container(docker, name, run_id)
    return 0, {"status": status, "container": name, "run_id": run_id}


def pytest_environment(
    *, run_id: str, host: str, port: int, admin_password: str, passwords: Mapping[str, str]
) -> dict[str, str]:
    """传给 pytest 子进程的环境；不含任何可指向外部数据库的地址。"""
    environment = sanitized_environment(os.environ)
    environment.update(
        {
            "SWIM_CLOUD_PG_HARNESS_RUN": run_id,
            "SWIM_CLOUD_PG_HOST": host,
            "SWIM_CLOUD_PG_PORT": str(port),
            "SWIM_CLOUD_PG_ADMIN_USER": ADMIN_USER,
            "SWIM_CLOUD_PG_ADMIN_PASSWORD": admin_password,
            "SWIM_CLOUD_PG_MIGRATION_USER": MIGRATION_USER,
            "SWIM_CLOUD_PG_MIGRATION_PASSWORD": passwords[MIGRATION_USER],
            "SWIM_CLOUD_PG_APP_USER": APP_USER,
            "SWIM_CLOUD_PG_APP_PASSWORD": passwords[APP_USER],
        }
    )
    return environment


def source_version(host: str, port: int, password: str) -> dict:
    import psycopg

    with psycopg.connect(
        host=host, port=port, user=ADMIN_USER, password=password,
        dbname="postgres", autocommit=True,
    ) as connection:
        version = connection.execute("SHOW server_version").fetchone()[0]
        settings = dict(
            connection.execute(
                "SELECT name, setting FROM pg_settings WHERE name IN ('server_encoding', 'TimeZone', 'max_connections')"
            ).fetchall()
        )
    return {"server_version": version, **settings}


def _install_signal_handlers() -> None:
    def handler(signum, _frame):
        raise Terminated(f"收到信号 {signum}")

    for signal_name in ("SIGINT", "SIGTERM", "SIGHUP"):
        signal_value = getattr(signal, signal_name, None)
        if signal_value is None:
            continue
        try:
            signal.signal(signal_value, handler)
        except (ValueError, OSError):
            continue


def run_pytest(environment: dict[str, str], junit: Path, basetemp: Path, extra: Sequence[str]) -> int:
    junit.parent.mkdir(parents=True, exist_ok=True)
    basetemp.parent.mkdir(parents=True, exist_ok=True)
    # 用 --dev-select 只做本机迭代时，不施加“必需场景下限”，该次运行也不构成证据。
    minimum = 0 if extra else MINIMUM_PG_SCENARIOS
    command = [
        sys.executable, "-m", "pytest",
        "--cloud-backend=postgresql",
        f"--cloud-pg-minimum-scenarios={minimum}",
        f"--junitxml={junit}",
        # 独立 basetemp，避免与并发会话共用系统临时目录。
        f"--basetemp={basetemp}",
        "-p", "no:cacheprovider",
        "-ra",
        *extra,
    ]
    result = subprocess.run(command, cwd=ROOT, env=environment)
    return result.returncode


def redact(text: str, secrets_: Sequence[str]) -> str:
    for secret in secrets_:
        if secret:
            text = text.replace(secret, "***")
    return text


def collect_instance_log(docker: Docker, resources: RunResources, secrets_: Sequence[str], path: Path) -> str:
    """清理前抓取实例日志并脱敏；抓取失败只记录状态，不掩盖原始失败。"""
    try:
        raw = docker.logs(resources.container)
    except HarnessError as error:
        return f"error:{error}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redact(raw, secrets_), encoding="utf-8")
    return "written"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def execute(args: argparse.Namespace) -> int:
    docker = resolve_docker()
    if args.cleanup_run_file:
        code, report = cleanup_from_run_file(docker, Path(args.cleanup_run_file))
        print(json.dumps(report, ensure_ascii=False))
        return code

    lock = load_image_lock()
    ignored = ignored_connection_keys(os.environ)
    if not docker.image_present(lock.reference):
        docker.pull(lock.reference)

    resources = RunResources(run_id=new_run_id(), container="", image_reference=lock.reference)
    resources.container = container_name(resources.run_id)
    admin_password = generate_password()
    summary: dict = {
        "run_id": resources.run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "image": lock.describe(),
        "ignored_environment_variables": ignored,
        "backend": "postgresql",
        "local_execution": True,
    }
    cleanup_status = "not-attempted"
    exit_code = 1
    secret_values: list[str] = [admin_password]
    _install_signal_handlers()
    try:
        resources.container_id = docker.run_container(
            name=resources.container,
            run_id=resources.run_id,
            reference=lock.reference,
            admin_password=admin_password,
        )
        if not resources.container_id:
            raise HarnessError("docker run 未返回容器 ID")
        write_json(Path(args.run_file), resources.to_file_payload())
        details = docker.image_details(lock.reference)
        summary["platform"] = {
            "architecture": details.get("Architecture"),
            "os": details.get("Os"),
            "image_id": details.get("Id"),
            "repo_digests": details.get("RepoDigests", []),
        }
        resolve_host_port(docker, resources)
        wait_until_ready(docker, resources, args.startup_timeout)
        summary["instance"] = source_version("127.0.0.1", resources.host_port, admin_password)
        passwords = bootstrap_roles("127.0.0.1", resources.host_port, admin_password)
        secret_values.extend(passwords.values())
        summary["identities"] = {
            "admin": ADMIN_USER,
            "migration": MIGRATION_USER,
            "application": APP_USER,
        }
        environment = pytest_environment(
            run_id=resources.run_id,
            host="127.0.0.1",
            port=resources.host_port,
            admin_password=admin_password,
            passwords=passwords,
        )
        exit_code = run_pytest(
            environment,
            Path(args.junit),
            Path(args.basetemp) / resources.run_id,
            args.dev_select or [],
        )
        summary["pytest_exit_code"] = exit_code
    except Terminated as error:
        summary["termination"] = str(error)
        exit_code = 130
    except HarnessError as error:
        summary["harness_error"] = str(error)
        exit_code = 2
    finally:
        if exit_code != 0:
            # 清理前抓取，否则失败现场随容器一起消失。
            summary["instance_log"] = collect_instance_log(
                docker, resources, secret_values, Path(args.instance_log)
            )
        cleanup_status = cleanup_container(docker, resources.container, resources.run_id)
        summary["cleanup"] = cleanup_status
        summary["finished_at"] = datetime.now(UTC).isoformat()
        summary["result"] = "passed" if exit_code == 0 and cleanup_status in {"removed", "absent"} else "failed"
        write_json(Path(args.summary), summary)
        if cleanup_status.startswith(("refused", "removed:unverified")):
            # 清理异常必须显式暴露，不能用测试通过掩盖残留。
            exit_code = exit_code or 3
    print(json.dumps({k: summary[k] for k in ("run_id", "result", "cleanup")}, ensure_ascii=False))
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="专用 PostgreSQL 17 验证编排；不接受任何外部数据库地址",
        allow_abbrev=False,
    )
    parser.add_argument("--junit", default=str(DEFAULT_JUNIT), help="JUnit XML 输出路径")
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY), help="脱敏运行摘要输出路径")
    parser.add_argument("--run-file", default=str(DEFAULT_RUN_FILE), help="本次容器记录，供 CI 兜底清理")
    parser.add_argument("--basetemp", default=str(ROOT / "var" / "pytest-pg"), help="pytest 临时根目录")
    parser.add_argument(
        "--instance-log", default=str(DEFAULT_INSTANCE_LOG), help="失败时脱敏实例日志输出路径"
    )
    parser.add_argument("--startup-timeout", type=float, default=120.0, help="实例就绪等待秒数")
    parser.add_argument(
        "--cleanup-run-file",
        default=None,
        help="按记录文件精确清理本次容器（CI always 步骤用）",
    )
    parser.add_argument(
        "--dev-select",
        nargs=argparse.REMAINDER,
        default=None,
        help="仅供本机迭代选择用例；使用后不构成验证证据",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    return execute(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
