import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "storage-provider-v1.schema.json").read_text())


def test_storage_provider_configuration_supports_peer_provider_types():
    for provider_type in ["wasabi", "aws-s3", "ontap-s3", "vast-s3", "ootbi-s3"]:
        payload = {
            "schema": "ai.wagvid.storage-provider.v1",
            "provider_id": f"fixture-{provider_type}",
            "provider_type": provider_type,
            "endpoint": "https://storage.example",
            "region": None,
            "credential_ref": f"secret://storage/{provider_type}",
            "ca_bundle_ref": None,
            "tls_required": True,
            "addressing_style": "auto",
            "logical_roles": {"originals": ["originals"]},
            "governance_profile": "evidence",
            "provisioning_enabled": False,
        }
        assert list(Draft202012Validator(SCHEMA).iter_errors(payload)) == []


def test_storage_provider_configuration_rejects_inline_secret():
    payload = {
        "schema": "ai.wagvid.storage-provider.v1",
        "provider_id": "bad",
        "provider_type": "aws-s3",
        "credential_ref": "password=hunter2",
        "tls_required": True,
        "addressing_style": "auto",
        "logical_roles": {},
    }
    assert list(Draft202012Validator(SCHEMA).iter_errors(payload))
