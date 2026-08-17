import base64
import json

import pytest

from wagvid_app.ontap_rest import (
    OntapResponse,
    OntapRestClient,
    extract_s3_user_credentials,
)


def test_ontap_rest_client_requires_https():
    with pytest.raises(ValueError, match="HTTPS"):
        OntapRestClient(
            base_url="http://ontap.example",
            username="api-user",
            password="password",
        )


def test_injected_transport_receives_rest_request_and_client_repr_is_redacted():
    calls = []

    def transport(method, path, body, headers):
        calls.append((method, path, body, headers))
        return OntapResponse(200, {"records": []})

    client = OntapRestClient(
        base_url="https://ontap.example",
        username="svc-wagvid",
        password="top-secret",
        transport=transport,
    )
    response = client.post("/api/protocols/s3/services", {"enabled": True})
    assert response.status == 200
    method, path, body, headers = calls[0]
    assert method == "POST"
    assert path == "/api/protocols/s3/services"
    assert json.loads(body) == {"enabled": True}
    encoded = headers["Authorization"].split(" ", 1)[1]
    assert base64.b64decode(encoded).decode() == "svc-wagvid:top-secret"
    assert "top-secret" not in repr(client)


def test_rest_path_must_stay_inside_ontap_api_namespace():
    client = OntapRestClient(
        base_url="https://ontap.example",
        username="user",
        password="password",
        transport=lambda *args: OntapResponse(200, {}),
    )
    with pytest.raises(ValueError, match="/api/"):
        client.get("/private/unsupported")


def test_s3_user_secret_is_redacted_from_repr_and_summary():
    material = extract_s3_user_credentials(
        {
            "access_key": "ONTAPACCESS1234",
            "secret_key": "super-secret-material",
            "key_expiry_time": "2027-01-01T00:00:00Z",
        }
    )
    assert material.fingerprint.endswith("1234")
    assert "super-secret-material" not in repr(material)
    assert "super-secret-material" not in repr(material.redacted_summary())
    assert material.secret_key == "super-secret-material"


def test_s3_user_secret_extractor_accepts_records_wrapper():
    material = extract_s3_user_credentials(
        {"records": [{"access_key": "ACCESS0001", "secret_key": "secret-value"}]}
    )
    assert material.access_key == "ACCESS0001"


def test_s3_user_secret_extractor_fails_closed_when_secret_missing():
    with pytest.raises(ValueError, match="did not contain"):
        extract_s3_user_credentials({"access_key": "only-access"})
