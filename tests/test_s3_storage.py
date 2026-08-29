import hashlib
import io

import pytest

from wagvid_app.s3_storage import MIB, S3ObjectStore
from wagvid_app.storage import ObjectIntegrityError
from wagvid_app.storage_contract import run_storage_contract_probe


class MissingObject(Exception):
    response = {"Error": {"Code": "NoSuchKey"}}


class FakeS3Data:
    def __init__(self):
        self.objects = {}
        self.calls = []
        self.fail_part = False

    def head_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise MissingObject
        value = self.objects[(Bucket, Key)]
        return {
            "ContentLength": len(value["body"]), "Metadata": value["metadata"],
            "VersionId": value.get("version", "v1"), "ETag": '"etag"',
        }

    def put_object(self, **kwargs):
        body = kwargs["Body"].read()
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = {
            "body": body, "metadata": kwargs["Metadata"], "version": "v1",
        }
        self.calls.append(("put", kwargs["Key"]))
        return {"VersionId": "v1", "ETag": '"etag"'}

    def create_multipart_upload(self, **kwargs):
        self.pending = {"kwargs": kwargs, "parts": []}
        self.calls.append(("create-multipart", kwargs["Key"]))
        return {"UploadId": "upload-1"}

    def upload_part(self, **kwargs):
        if self.fail_part:
            raise OSError("simulated provider interruption")
        self.pending["parts"].append(kwargs["Body"])
        return {"ETag": f'"part-{kwargs["PartNumber"]}"', "ChecksumSHA256": kwargs["ChecksumSHA256"]}

    def complete_multipart_upload(self, **kwargs):
        initial = self.pending["kwargs"]
        self.objects[(initial["Bucket"], initial["Key"])] = {
            "body": b"".join(self.pending["parts"]),
            "metadata": initial["Metadata"],
            "version": "v2",
        }
        self.calls.append(("complete", initial["Key"]))
        return {"VersionId": "v2", "ETag": '"multipart-etag"'}

    def abort_multipart_upload(self, **kwargs):
        self.calls.append(("abort", kwargs["Key"]))

    def list_parts(self, **kwargs):
        return {
            "Parts": [
                {"PartNumber": number, "ETag": f'"part-{number}"'}
                for number, _ in enumerate(self.pending["parts"], start=1)
            ]
        }

    def get_object(self, **kwargs):
        body = self.objects[(kwargs["Bucket"], kwargs["Key"])]["body"]
        if value := kwargs.get("Range"):
            bounds = value.removeprefix("bytes=").split("-")
            start = int(bounds[0])
            end = int(bounds[1]) if bounds[1] else len(body) - 1
            body = body[start : end + 1]
        return {"Body": io.BytesIO(body)}

    def generate_presigned_url(self, operation, **kwargs):
        return f"https://signed.invalid/{kwargs['Params']['Key']}?ttl={kwargs['ExpiresIn']}"

    def delete_object(self, **kwargs):
        self.calls.append(("delete", kwargs))
        self.objects.pop((kwargs["Bucket"], kwargs["Key"]), None)


def test_small_verified_write_is_immutable_idempotent_and_readable():
    client = FakeS3Data()
    store = S3ObjectStore(client, bucket="wagvid-originals", multipart_threshold=5 * MIB)
    payload = b"verified video"
    digest = hashlib.sha256(payload).hexdigest()
    first = store.put_verified(
        "org/video.mp4", io.BytesIO(payload),
        expected_size=len(payload), expected_sha256=digest, content_type="video/mp4",
    )
    repeated = store.put_verified(
        "org/video.mp4", io.BytesIO(payload), expected_size=len(payload), expected_sha256=digest,
    )
    assert first == repeated
    assert client.calls == [("put", "org/video.mp4")]
    assert store.open_read("org/video.mp4").read() == payload
    assert store.open_range("org/video.mp4", start=2, end=7).read() == payload[2:8]
    assert store.presigned_download("org/video.mp4", expires_seconds=60).endswith("ttl=60")


def test_write_validates_before_provider_mutation_and_rejects_key_collision():
    client = FakeS3Data()
    store = S3ObjectStore(client, bucket="wagvid-results", multipart_threshold=5 * MIB)
    payload = b"result"
    with pytest.raises(ObjectIntegrityError, match="size/checksum"):
        store.put_verified(
            "result.json", io.BytesIO(payload), expected_size=999, expected_sha256="a" * 64
        )
    assert client.calls == []
    with pytest.raises(ValueError, match="unsafe"):
        store.put_verified(
            "../escape", io.BytesIO(payload), expected_size=len(payload),
            expected_sha256=hashlib.sha256(payload).hexdigest(),
        )
    digest = hashlib.sha256(payload).hexdigest()
    store.put_verified(
        "result.json", io.BytesIO(payload), expected_size=len(payload), expected_sha256=digest
    )
    with pytest.raises(ObjectIntegrityError, match="different content"):
        store.put_verified(
            "result.json", io.BytesIO(b"other"), expected_size=5,
            expected_sha256=hashlib.sha256(b"other").hexdigest(),
        )


def test_large_write_uses_multipart_and_aborts_provider_failure():
    payload = b"x" * (6 * MIB)
    digest = hashlib.sha256(payload).hexdigest()
    client = FakeS3Data()
    store = S3ObjectStore(
        client, bucket="wagvid-originals", multipart_threshold=5 * MIB, part_size=5 * MIB
    )
    stored = store.put_verified(
        "large.mp4", io.BytesIO(payload), expected_size=len(payload), expected_sha256=digest
    )
    assert stored.version_id == "v2"
    assert client.objects[("wagvid-originals", "large.mp4")]["body"] == payload
    assert client.calls == [("create-multipart", "large.mp4"), ("complete", "large.mp4")]

    failing = FakeS3Data()
    failing.fail_part = True
    with pytest.raises(OSError, match="interruption"):
        S3ObjectStore(
            failing, bucket="wagvid-originals", multipart_threshold=5 * MIB, part_size=5 * MIB
        ).put_verified(
            "failed.mp4", io.BytesIO(payload), expected_size=len(payload), expected_sha256=digest
        )
    assert failing.calls[-1] == ("abort", "failed.mp4")


def test_physical_delete_requires_an_explicit_version():
    client = FakeS3Data()
    store = S3ObjectStore(client, bucket="wagvid-originals")
    with pytest.raises(ValueError, match="explicit object version"):
        store.delete_version("video.mp4", version_id="")
    store.delete_version("video.mp4", version_id="version-7")
    assert client.calls[-1][1]["VersionId"] == "version-7"


def test_multipart_session_can_list_and_resume_before_completion():
    client = FakeS3Data()
    store = S3ObjectStore(client, bucket="wagvid-originals")
    payload = b"x" * (5 * MIB)
    session = store.start_multipart("resume.mp4", sha256=hashlib.sha256(payload).hexdigest())
    first = store.upload_part(session, number=1, payload=payload)
    assert store.list_uploaded_parts(session)[0]["PartNumber"] == 1
    response = store.complete_multipart(session, parts=[first])
    assert response["VersionId"] == "v2"


def test_opt_in_provider_contract_validates_object_range_and_multipart_operations():
    client = FakeS3Data()
    with pytest.raises(PermissionError, match="explicit mutation"):
        run_storage_contract_probe(
            client,
            provider_id="aws-s3",
            governance_profile="standard",
            bucket="contract-bucket",
            test_prefix="wagvid-tests",
            allow_mutation=False,
        )
    report = run_storage_contract_probe(
        client,
        provider_id="aws-s3",
        governance_profile="standard",
        bucket="contract-bucket",
        test_prefix="wagvid-tests",
        allow_mutation=True,
    )
    assert report.support_state == "validated"
    assert {"put", "head", "get", "range-get", "multipart-list"} <= set(report.checks)
