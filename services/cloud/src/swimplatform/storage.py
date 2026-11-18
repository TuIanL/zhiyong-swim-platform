"""Private multipart object storage boundary.

Only this module knows about the S3 SDK. Callers pass server-generated object
identities and never accept a bucket, endpoint, or object key from a client.
"""
from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import BinaryIO, Protocol
from urllib.parse import quote
from uuid import uuid4


class StorageError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ObjectIdentity:
    bucket: str
    key: str
    version_id: str | None = None


class StorageProvider(Protocol):
    """Small provider-neutral contract used by API workers and cleanup."""

    profile: str
    bucket: str

    def check_capabilities(self) -> dict: ...
    def create_multipart(self, key: str, metadata: dict[str, str]) -> str: ...
    def list_parts(self, key: str, upload_id: str, marker: int = 0,
                   max_parts: int = 1000) -> dict: ...
    def sign_part(self, key: str, upload_id: str, part_number: int, expires: int) -> str: ...
    def complete_multipart(self, key: str, upload_id: str, parts: list[dict]) -> dict: ...
    def abort_multipart(self, key: str, upload_id: str) -> None: ...
    def head_object(self, key: str, version_id: str | None = None) -> dict: ...
    def open_object(self, key: str, version_id: str | None = None) -> BinaryIO: ...
    def sign_read(self, key: str, version_id: str, expires: int, *, disposition: str | None = None) -> str: ...
    def delete_object(self, key: str, version_id: str | None = None) -> None: ...
    def list_multipart_uploads(self, prefix: str, key_marker: str | None = None,
                               upload_marker: str | None = None) -> dict: ...
    def list_objects(self, prefix: str, token: str | None = None) -> dict: ...
    def list_object_versions(self, prefix: str, key_marker: str | None = None,
                             version_marker: str | None = None, max_keys: int = 1000) -> dict: ...


class S3StorageProvider:
    """boto3 adapter for S3-compatible private buckets."""

    profile = "s3"

    def __init__(self, *, endpoint_url: str, region: str, bucket: str,
                 access_key: str, secret_key: str, profile: str = "s3", connect_timeout: int = 3,
                 read_timeout: int = 20, max_attempts: int = 2):
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - exercised by packaging guard
            raise RuntimeError("S3 transfer requires the locked boto3 dependency") from exc
        self.bucket = bucket
        self.profile = profile
        self.endpoint_url = endpoint_url.rstrip("/")
        self._capabilities = None
        self.client = boto3.client(
            "s3", endpoint_url=endpoint_url, region_name=region,
            aws_access_key_id=access_key, aws_secret_access_key=secret_key,
            config=Config(
                signature_version="s3v4", s3={"addressing_style": "path"},
                connect_timeout=connect_timeout, read_timeout=read_timeout,
                retries={"max_attempts": max_attempts, "mode": "standard"},
            ),
        )

    def _call(self, method: str, **kwargs):
        try:
            return getattr(self.client, method)(**kwargs)
        except Exception as exc:
            response = getattr(exc, "response", {}) or {}
            error = response.get("Error", {})
            code = str(error.get("Code", "storage_error"))
            status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in {"NoSuchKey", "NoSuchVersion", "NoSuchUpload", "NoSuchBucket", "404"}:
                raise StorageError("not_found") from exc
            if code in {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch", "403"} or status == 403:
                raise StorageError("permission_denied") from exc
            if code in {"InvalidPart", "InvalidPartOrder", "EntityTooSmall", "BadDigest"}:
                raise StorageError("invalid_upload") from exc
            if status is not None and status < 500 and status != 429:
                raise StorageError("provider_rejected_request") from exc
            retryable = status is None or status >= 500 or status == 429
            raise StorageError("provider_unavailable" if retryable else "provider_error",
                               retryable=retryable) from exc

    def check_capabilities(self) -> dict:
        if self._capabilities is not None:
            return dict(self._capabilities)
        self._call("head_bucket", Bucket=self.bucket)
        versioning = self._call("get_bucket_versioning", Bucket=self.bucket).get("Status")
        if versioning != "Enabled":
            raise StorageError("versioning_required")
        run_tag = uuid4().hex
        multipart_key = f"private/_capability/{run_tag}/multipart.bin"
        upload_id = None
        try:
            upload_id = self.create_multipart(
                multipart_key, {"owner": "swim-platform", "purpose": "capability-probe"})
            for number, body in ((1, b"first"), (2, b"second")):
                signed_part = self.sign_part(multipart_key, upload_id, number, 60)
                request = urllib.request.Request(signed_part, data=body, method="PUT")
                with urllib.request.urlopen(request, timeout=5) as response:
                    if not 200 <= response.status < 300 or not response.headers.get("ETag"):
                        raise StorageError("multipart_signing_probe_failed")
            first_page = self._call("list_parts", Bucket=self.bucket, Key=multipart_key,
                                    UploadId=upload_id, PartNumberMarker=0, MaxParts=1)
            if not first_page.get("IsTruncated") or first_page.get("NextPartNumberMarker") != 1:
                raise StorageError("multipart_pagination_probe_failed")
            second_page = self._call("list_parts", Bucket=self.bucket, Key=multipart_key,
                                     UploadId=upload_id, PartNumberMarker=1, MaxParts=1)
            if [item.get("PartNumber") for item in second_page.get("Parts", [])] != [2]:
                raise StorageError("multipart_pagination_probe_failed")
        except (StorageError, OSError, urllib.error.URLError) as exc:
            if upload_id:
                try:
                    self.abort_multipart(multipart_key, upload_id)
                except StorageError:
                    pass
            if isinstance(exc, StorageError):
                raise
            raise StorageError("multipart_capability_probe_failed") from exc
        self.abort_multipart(multipart_key, upload_id)
        try:
            self._call("list_parts", Bucket=self.bucket, Key=multipart_key, UploadId=upload_id)
        except StorageError as exc:
            if exc.code != "not_found":
                raise
        else:
            raise StorageError("multipart_abort_unconfirmed")

        probe_key = f"private/_capability/{run_tag}/object.bin"
        probe_version = self._call("put_object", Bucket=self.bucket, Key=probe_key,
                                   Body=b"0123456789", Metadata={"owner": "swim-platform"})
        version_id = probe_version.get("VersionId")
        if not version_id:
            raise StorageError("version_id_missing")
        try:
            listed_versions = self.list_object_versions(f"private/_capability/{run_tag}/", max_keys=1)
            if not any(item.get("Key") == probe_key and item.get("VersionId") == version_id
                       for item in listed_versions["versions"]):
                raise StorageError("version_listing_probe_failed")
            stored = self._call("get_object", Bucket=self.bucket, Key=probe_key, VersionId=version_id)
            try:
                if stored["Body"].read() != b"0123456789":
                    raise StorageError("exact_read_probe_failed")
            finally:
                stored["Body"].close()
            signed = self.sign_read(probe_key, version_id, 60)
            range_request = urllib.request.Request(signed, headers={"Range": "bytes=2-5"})
            with urllib.request.urlopen(range_request, timeout=5) as response:
                if response.status != 206 or response.read() != b"2345":
                    raise StorageError("range_read_probe_failed")
            unauthenticated = urllib.request.Request(
                f"{self.endpoint_url}/{quote(self.bucket, safe='')}/{quote(probe_key, safe='/')}",
                method="GET",
            )
            try:
                with urllib.request.urlopen(unauthenticated, timeout=3) as response:
                    if 200 <= response.status < 300:
                        raise StorageError("bucket_is_public")
                    raise StorageError("private_probe_unexpected_status")
            except urllib.error.HTTPError as exc:
                if exc.code not in {401, 403}:
                    raise StorageError("private_probe_failed") from exc
        finally:
            self._call("delete_object", Bucket=self.bucket, Key=probe_key, VersionId=version_id)
            try:
                self._call("head_object", Bucket=self.bucket, Key=probe_key, VersionId=version_id)
            except StorageError as exc:
                if exc.code != "not_found":
                    raise
            else:
                raise StorageError("capability_probe_cleanup_unconfirmed")
        self._capabilities = {"multipart": True, "multipart_pagination": True, "versioning": True,
                              "private_bucket": True, "range_get": True, "server_side_signing": True}
        return dict(self._capabilities)

    def create_multipart(self, key: str, metadata: dict[str, str]) -> str:
        response = self._call("create_multipart_upload", Bucket=self.bucket, Key=key,
                              ContentType="application/octet-stream", Metadata=metadata)
        upload_id = response.get("UploadId")
        if not upload_id:
            raise StorageError("provider_protocol_error")
        return upload_id

    def list_parts(self, key: str, upload_id: str, marker: int = 0, max_parts: int = 1000) -> dict:
        result = self._call("list_parts", Bucket=self.bucket, Key=key, UploadId=upload_id,
                            PartNumberMarker=marker, MaxParts=max(1, min(max_parts, 1000)))
        return {"parts": result.get("Parts", []), "truncated": result.get("IsTruncated", False),
                "next_marker": result.get("NextPartNumberMarker")}

    def sign_part(self, key: str, upload_id: str, part_number: int, expires: int) -> str:
        try:
            return self.client.generate_presigned_url(
                "upload_part", Params={"Bucket": self.bucket, "Key": key,
                                       "UploadId": upload_id, "PartNumber": part_number},
                ExpiresIn=expires, HttpMethod="PUT",
            )
        except Exception as exc:
            raise StorageError("signing_failed") from exc

    def complete_multipart(self, key: str, upload_id: str, parts: list[dict]) -> dict:
        response = self._call("complete_multipart_upload", Bucket=self.bucket, Key=key,
                              UploadId=upload_id,
                              MultipartUpload={"Parts": [{"PartNumber": p["part_number"],
                                                          "ETag": p["etag"]} for p in parts]})
        return {"version_id": response.get("VersionId"), "etag": response.get("ETag")}

    def abort_multipart(self, key: str, upload_id: str) -> None:
        try:
            self._call("abort_multipart_upload", Bucket=self.bucket, Key=key, UploadId=upload_id)
        except StorageError as exc:
            if exc.code != "not_found":
                raise

    def head_object(self, key: str, version_id: str | None = None) -> dict:
        params = {"Bucket": self.bucket, "Key": key}
        if version_id:
            params["VersionId"] = version_id
        response = self._call("head_object", **params)
        return {"size": response.get("ContentLength"), "version_id": response.get("VersionId"),
                "etag": response.get("ETag"), "metadata": response.get("Metadata", {}),
                "content_type": response.get("ContentType")}

    def open_object(self, key: str, version_id: str | None = None) -> BinaryIO:
        params = {"Bucket": self.bucket, "Key": key}
        if version_id:
            params["VersionId"] = version_id
        response = self._call("get_object", **params)
        return response["Body"]

    def sign_read(self, key: str, version_id: str, expires: int, *, disposition: str | None = None) -> str:
        params = {"Bucket": self.bucket, "Key": key, "VersionId": version_id}
        if disposition:
            params["ResponseContentDisposition"] = disposition
        try:
            return self.client.generate_presigned_url("get_object", Params=params,
                                                       ExpiresIn=expires, HttpMethod="GET")
        except Exception as exc:
            raise StorageError("signing_failed") from exc

    def delete_object(self, key: str, version_id: str | None = None) -> None:
        params = {"Bucket": self.bucket, "Key": key}
        if version_id:
            params["VersionId"] = version_id
        self._call("delete_object", **params)

    def list_multipart_uploads(self, prefix: str, key_marker: str | None = None,
                               upload_marker: str | None = None) -> dict:
        params = {"Bucket": self.bucket, "Prefix": prefix, "MaxUploads": 1000}
        if key_marker:
            params["KeyMarker"] = key_marker
        if upload_marker:
            params["UploadIdMarker"] = upload_marker
        result = self._call("list_multipart_uploads", **params)
        return {"uploads": result.get("Uploads", []), "truncated": result.get("IsTruncated", False),
                "key_marker": result.get("NextKeyMarker"), "upload_marker": result.get("NextUploadIdMarker")}

    def list_objects(self, prefix: str, token: str | None = None) -> dict:
        params = {"Bucket": self.bucket, "Prefix": prefix, "MaxKeys": 1000}
        if token:
            params["ContinuationToken"] = token
        result = self._call("list_objects_v2", **params)
        return {"objects": result.get("Contents", []), "truncated": result.get("IsTruncated", False),
                "next_token": result.get("NextContinuationToken")}

    def list_object_versions(self, prefix: str, key_marker: str | None = None,
                             version_marker: str | None = None, max_keys: int = 1000) -> dict:
        params = {"Bucket": self.bucket, "Prefix": prefix, "MaxKeys": max(1, min(max_keys, 1000))}
        if key_marker:
            params["KeyMarker"] = key_marker
        if version_marker:
            params["VersionIdMarker"] = version_marker
        result = self._call("list_object_versions", **params)
        return {"versions": result.get("Versions", []),
                "truncated": result.get("IsTruncated", False),
                "key_marker": result.get("NextKeyMarker"),
                "version_marker": result.get("NextVersionIdMarker")}
