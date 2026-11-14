#!/usr/bin/env python3
"""Run real media transfer acceptance against one disposable pinned RustFS container."""
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "ghcr.io/rustfs/rustfs@sha256:f36a122c886d99206df9a1dc1efcc96543db3ae206718e0527509dbf1b27c662"
EXPECTED_DIGEST = "sha256:f36a122c886d99206df9a1dc1efcc96543db3ae206718e0527509dbf1b27c662"
OWNER = "swim-platform-m3-media-ci"


class HarnessError(RuntimeError):
    pass


def docker(*args: str, check: bool = True):
    result = subprocess.run(["docker", *args], cwd=ROOT, text=True,
                            capture_output=True, check=False, timeout=120)
    if check and result.returncode:
        raise HarnessError(f"docker {' '.join(args[:2])} failed: {result.stderr.strip()[:500]}")
    return result


def inspect_exact(container_id: str) -> dict:
    result = docker("inspect", container_id, check=False)
    if result.returncode:
        if "No such object" in result.stderr or "No such container" in result.stderr:
            raise LookupError(container_id)
        raise HarnessError(f"Docker inspect failed: {result.stderr.strip()[:500]}")
    try:
        return json.loads(result.stdout)[0]
    except (ValueError, IndexError) as exc:
        raise HarnessError("Docker inspect returned invalid container data") from exc


def validate_container(container: dict, *, run_id: str, name: str, image_id: str) -> None:
    labels = container.get("Config", {}).get("Labels", {}) or {}
    expected = {"io.swim-platform.owner": OWNER, "io.swim-platform.run-id": run_id,
                "io.swim-platform.purpose": "isolated-media-test"}
    if container.get("Id") is None or container.get("Name", "").lstrip("/") != name:
        raise HarnessError("container ID/name does not match this isolated run")
    if container.get("Image") != image_id or any(labels.get(k) != v for k, v in expected.items()):
        raise HarnessError("container image or ownership labels do not match this isolated run")


def remove_exact(container_id: str, *, run_id: str, name: str, image_id: str) -> str:
    try:
        container = inspect_exact(container_id)
    except LookupError:
        return "absent"
    validate_container(container, run_id=run_id, name=name, image_id=image_id)
    docker("stop", "--time", "10", container_id)
    docker("rm", "--force", "--volumes", container_id)
    try:
        inspect_exact(container_id)
    except LookupError:
        return "removed"
    raise HarnessError("container remained after exact docker rm")


def private_probe(client, endpoint: str, bucket: str, run_id: str) -> None:
    key = f"private/test/{run_id}/harness/private-probe.txt"
    response = client.put_object(Bucket=bucket, Key=key, Body=b"private")
    version = response.get("VersionId")
    if not version:
        raise HarnessError("RustFS did not return a version ID after versioning was enabled")
    try:
        request = urllib.request.Request(f"{endpoint}/{bucket}/{key}", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=3) as result:
                if 200 <= result.status < 300:
                    raise HarnessError("unsigned GET unexpectedly read a private probe object")
                raise HarnessError(f"unsigned GET returned unexpected HTTP {result.status}")
        except urllib.error.HTTPError as exc:
            if exc.code not in {401, 403}:
                raise HarnessError(f"unsigned GET returned unexpected HTTP {exc.code}") from exc
    finally:
        client.delete_object(Bucket=bucket, Key=key, VersionId=version)
        try:
            client.head_object(Bucket=bucket, Key=key, VersionId=version)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {"NoSuchVersion", "404", "NotFound"}:
                raise HarnessError("private capability probe deletion was not confirmed") from exc
        else:
            raise HarnessError("private capability probe object remained after deletion")


def create_bucket(client, bucket: str, endpoint: str, run_id: str):
    deadline = time.monotonic() + 60
    last_error = None
    while time.monotonic() < deadline:
        try:
            client.create_bucket(Bucket=bucket)
            break
        except (BotoCoreError, ClientError) as exc:
            last_error = exc
            time.sleep(1)
    else:
        raise HarnessError(f"RustFS S3 endpoint did not become ready: {last_error}")
    client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    client.put_bucket_cors(Bucket=bucket, CORSConfiguration={"CORSRules": [{
        "AllowedOrigins": ["http://localhost:3000"],
        "AllowedMethods": ["GET", "PUT", "HEAD"],
        "AllowedHeaders": ["content-type", "range", "x-amz-*"],
        "ExposeHeaders": ["ETag", "Content-Length", "Content-Range", "Accept-Ranges"],
        "MaxAgeSeconds": 300,
    }]})
    versioning = client.get_bucket_versioning(Bucket=bucket).get("Status")
    if versioning != "Enabled":
        raise HarnessError("bucket versioning capability was not enabled")
    private_probe(client, endpoint, bucket, run_id)


def main() -> int:
    run_id = (os.getenv("GITHUB_RUN_ID", "local") + "-" + uuid4().hex[:12]).lower()
    name = f"swim-rustfs-{uuid4().hex[:12]}"
    bucket = f"swim-m3-{uuid4().hex[:20]}"
    access_key = "SWIMTEST" + secrets.token_hex(6).upper()
    secret_key = secrets.token_urlsafe(36)
    evidence = {
        "run_id": run_id, "owner": OWNER, "image": IMAGE,
        "expected_digest": EXPECTED_DIGEST, "bucket": bucket,
        "container_name": name, "started_at": datetime.now(UTC).isoformat(),
    }
    container_id = None
    image_id = None
    launch_attempted = False
    test_exit = 1
    cleanup = "not_started"
    try:
        docker("pull", IMAGE)
        image_info = json.loads(docker("image", "inspect", IMAGE).stdout)[0]
        image_id = image_info["Id"]
        repo_digests = image_info.get("RepoDigests", [])
        if not any(item.endswith(EXPECTED_DIGEST) for item in repo_digests):
            raise HarnessError("pulled RustFS image digest does not match the approved linux/amd64 digest")
        if image_info.get("Architecture") != "amd64":
            raise HarnessError("RustFS integration image must run as linux/amd64")
        evidence.update({"image_id": image_id, "repo_digests": repo_digests,
                         "architecture": image_info.get("Architecture")})
        launch_attempted = True
        created = docker(
            "run", "--platform", "linux/amd64", "--detach", "--name", name,
            "--label", f"io.swim-platform.owner={OWNER}",
            "--label", f"io.swim-platform.run-id={run_id}",
            "--label", "io.swim-platform.purpose=isolated-media-test",
            "--publish", "127.0.0.1::9000/tcp",
            "--env", f"RUSTFS_ACCESS_KEY={access_key}",
            "--env", f"RUSTFS_SECRET_KEY={secret_key}",
            "--env", "RUSTFS_ADDRESS=:9000",
            "--env", "RUSTFS_CONSOLE_ADDRESS=:9001",
            "--env", "RUSTFS_CONSOLE_ENABLE=false",
            "--env", "RUSTFS_OBS_LOGGER_LEVEL=error",
            IMAGE, "/data",
        )
        container_id = created.stdout.strip()
        container = inspect_exact(container_id)
        validate_container(container, run_id=run_id, name=name, image_id=image_id)
        version = docker("exec", container_id, "rustfs", "--version").stdout.strip()
        if "1.0.5" not in version:
            raise HarnessError("RustFS runtime version does not match the pinned 1.0.5 profile")
        evidence["runtime_version"] = version[:200]
        port = docker("port", container_id, "9000/tcp").stdout.strip().splitlines()[0]
        host, port_number = port.rsplit(":", 1)
        endpoint = f"http://{host}:{port_number}"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(endpoint + "/health", timeout=2) as health:
                    if health.status == 200:
                        break
            except (OSError, urllib.error.URLError):
                time.sleep(1)
        else:
            raise HarnessError("RustFS health endpoint did not become ready")
        client = boto3.client(
            "s3", endpoint_url=endpoint, region_name="us-east-1",
            aws_access_key_id=access_key, aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                          connect_timeout=3, read_timeout=10,
                          retries={"max_attempts": 1, "mode": "standard"}),
        )
        create_bucket(client, bucket, endpoint, run_id)
        evidence.update({"endpoint_host": host, "endpoint_port": int(port_number),
                         "versioning": "Enabled", "private_probe": "denied"})
        env = os.environ.copy()
        env.update({
            "SWIM_MEDIA_ENABLED": "true", "SWIM_MEDIA_ENVIRONMENT": "isolated-test",
            "SWIM_MEDIA_PROFILE": "rustfs-isolated", "SWIM_MEDIA_RUN_ID": run_id,
            "SWIM_MEDIA_ENDPOINT_URL": endpoint, "SWIM_MEDIA_REGION": "us-east-1",
            "SWIM_MEDIA_BUCKET": bucket, "SWIM_MEDIA_ACCESS_KEY": access_key,
            "SWIM_MEDIA_SECRET_KEY": secret_key,
            "SWIM_MEDIA_CLEANUP_ALLOW_EXECUTE": "true",
            "SWIM_MEDIA_PART_SIZE_BYTES": str(16 * 1024 * 1024),
            "SWIM_MEDIA_PART_URL_SECONDS": "300", "SWIM_MEDIA_READ_URL_SECONDS": "60",
            "SWIM_MEDIA_READ_URL_MAX_SECONDS": "300",
        })
        test = subprocess.run(
            [sys.executable, "-m", "pytest", "services/cloud/tests/test_media_transfer_storage.py",
             "--cloud-backend=sqlite", "-q", "--junitxml=var/rustfs-junit.xml"], cwd=ROOT, env=env, text=True,
            capture_output=True, timeout=900,
        )
        test_exit = test.returncode
        output = test.stdout + "\n" + test.stderr
        output = re.sub(r"(?i)(https?://[^?\s]+)\?[^\s\"'<>]+", r"\1?<redacted>", output)
        output = output.replace(access_key, "<redacted-access-key>").replace(secret_key, "<redacted-secret-key>")
        evidence["pytest"] = {"exit_code": test.returncode, "output": output[-12000:]}
    except (HarnessError, OSError, subprocess.SubprocessError, BotoCoreError, ClientError) as exc:
        evidence["harness_error"] = (str(exc).replace(access_key, "<redacted-access-key>")
                                      .replace(secret_key, "<redacted-secret-key>")[:1000])
        test_exit = 1
    finally:
        if launch_attempted and image_id:
            try:
                if not container_id:
                    try:
                        container_id = inspect_exact(name)["Id"]
                    except LookupError:
                        cleanup = "absent"
                        container_id = None
                if container_id:
                    cleanup = remove_exact(container_id, run_id=run_id, name=name, image_id=image_id)
            except (HarnessError, OSError) as exc:
                cleanup = f"error: {exc}"
        evidence["cleanup"] = cleanup
        evidence["finished_at"] = datetime.now(UTC).isoformat()
        evidence["bucket"] = bucket
        evidence.pop("access_key", None)
        evidence.pop("secret_key", None)
        junit = ROOT / "var" / "rustfs-junit.xml"
        if junit.exists():
            junit_text = junit.read_text(errors="replace")
            junit_text = re.sub(r"(?i)(https?://[^?\s]+)\?[^\s\"'<>]+", r"\1?<redacted>", junit_text)
            junit_text = junit_text.replace(access_key, "<redacted-access-key>")
            junit_text = junit_text.replace(secret_key, "<redacted-secret-key>")
            junit.write_text(junit_text)
        artifact = ROOT / "var" / "rustfs-test-evidence.json"
        artifact.parent.mkdir(exist_ok=True)
        artifact.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    if cleanup not in {"removed", "absent", "not_started"}:
        print(f"RustFS precise cleanup failed: {cleanup}", file=sys.stderr)
        return 1
    if test_exit:
        print(evidence.get("pytest", {}).get("output", evidence.get("harness_error", "RustFS test failed")),
              file=sys.stderr)
        return test_exit
    print(json.dumps({"run_id": run_id, "image_digest": EXPECTED_DIGEST,
                      "container_id": container_id, "container_name": name,
                      "bucket": bucket, "cleanup": cleanup,
                      "evidence": str(artifact.relative_to(ROOT))}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
