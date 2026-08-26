"""Wasabi S3 capability preflight and approval-gated setup execution."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from .wasabi import ReconcileAction, WasabiSetupPlan, reconcile_plan


class WasabiSetupError(RuntimeError):
    pass


class S3ControlClient(Protocol):
    def list_buckets(self) -> dict[str, Any]: ...
    def get_bucket_location(self, *, Bucket: str) -> dict[str, Any]: ...
    def get_bucket_acl(self, *, Bucket: str) -> dict[str, Any]: ...
    def get_bucket_versioning(self, *, Bucket: str) -> dict[str, Any]: ...
    def create_bucket(self, **kwargs: Any) -> dict[str, Any]: ...
    def put_bucket_versioning(self, **kwargs: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class WasabiPreflight:
    endpoint: str
    region: str
    credential_fingerprint: str
    can_list_buckets: bool
    discovered: dict[str, dict[str, Any]]
    actions: tuple[ReconcileAction, ...]
    errors: tuple[str, ...]
    plan_digest: str

    @property
    def applicable(self) -> bool:
        return self.can_list_buckets and not self.errors and not any(
            action.destructive for action in self.actions
        )


def _public_from_acl(value: dict[str, Any]) -> bool:
    for grant in value.get("Grants", []):
        grantee = grant.get("Grantee", {})
        uri = grantee.get("URI", "")
        if uri.endswith(("/AllUsers", "/AuthenticatedUsers")):
            return True
    return False


def run_preflight(
    client: S3ControlClient, *, plan: WasabiSetupPlan, access_key_id: str,
) -> WasabiPreflight:
    fingerprint = access_key_id[-4:].rjust(8, "*") if access_key_id else "missing"
    try:
        names = {item["Name"] for item in client.list_buckets().get("Buckets", [])}
    except Exception as error:  # noqa: BLE001 - provider SDK exceptions are optional imports
        return WasabiPreflight(
            plan.endpoint, plan.region, fingerprint, False, {}, (),
            (f"list-buckets denied or unavailable: {type(error).__name__}",), plan.digest,
        )
    desired_names = {bucket.name for bucket in plan.buckets}
    discovered: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for name in sorted(names & desired_names):
        try:
            location = client.get_bucket_location(Bucket=name).get("LocationConstraint")
            acl = client.get_bucket_acl(Bucket=name)
            versioning = client.get_bucket_versioning(Bucket=name).get("Status")
            discovered[name] = {
                "region": location or "us-east-1",
                "public": _public_from_acl(acl),
                "versioning": versioning,
            }
        except Exception as error:  # noqa: BLE001 - provider SDK exceptions are optional imports
            errors.append(f"cannot inspect {name}: {type(error).__name__}")
    actions = reconcile_plan(plan, discovered)
    if not getattr(plan, "provisioning_enabled", True):
        restricted = []
        for action in actions:
            if action.action == "create-private-bucket":
                restricted.append(
                    ReconcileAction(
                        "block-missing-existing-bucket",
                        action.bucket,
                        {"reason": "provisioning-disabled"},
                        True,
                    )
                )
            elif action.bucket in discovered:
                restricted.append(
                    ReconcileAction(
                        "block-provider-policy-drift",
                        action.bucket,
                        {"required_action": action.action},
                        True,
                    )
                )
        actions = tuple(restricted)
    return WasabiPreflight(
        plan.endpoint, plan.region, fingerprint, True, discovered, actions,
        tuple(errors), plan.digest,
    )


@dataclass(frozen=True)
class SetupApproval:
    plan_digest: str
    administrator_id: str
    approved_at: datetime
    expires_at: datetime
    confirmation: str

    def __post_init__(self) -> None:
        if not self.administrator_id or self.confirmation != "CREATE PRIVATE STORAGE BUCKETS":
            raise ValueError("explicit object-storage setup confirmation is required")
        if any(value.tzinfo is None or value.utcoffset() is None for value in (self.approved_at, self.expires_at)):
            raise ValueError("approval timestamps must be timezone-aware")
        if self.expires_at <= self.approved_at:
            raise ValueError("approval expiry must follow approval time")


def apply_setup(
    client: S3ControlClient, *, plan: WasabiSetupPlan,
    preflight: WasabiPreflight, approval: SetupApproval, now: datetime,
) -> tuple[str, ...]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("apply timestamp must be timezone-aware")
    if approval.plan_digest != plan.digest or preflight.plan_digest != plan.digest:
        raise WasabiSetupError("setup plan changed after approval/preflight")
    if now.astimezone(UTC) > approval.expires_at.astimezone(UTC):
        raise WasabiSetupError("setup approval expired")
    if not preflight.applicable:
        raise WasabiSetupError("preflight contains blockers")
    completed: list[str] = []
    for action in preflight.actions:
        if action.action == "create-private-bucket":
            kwargs: dict[str, Any] = {
                "Bucket": action.bucket,
                "CreateBucketConfiguration": {"LocationConstraint": action.details["region"]},
            }
            if action.details.get("object_lock"):
                kwargs["ObjectLockEnabledForBucket"] = True
            client.create_bucket(**kwargs)
        elif action.action == "enable-versioning":
            client.put_bucket_versioning(
                Bucket=action.bucket, VersioningConfiguration={"Status": "Enabled"}
            )
        else:
            raise WasabiSetupError(f"unsupported setup action: {action.action}")
        completed.append(f"{action.action}:{action.bucket}")
    return tuple(completed)


def create_boto3_client(
    *, access_key_id: str, secret_access_key: str, region: str, endpoint: str,
) -> S3ControlClient:
    """Lazy optional dependency factory; credentials are passed directly to the SDK."""

    if not access_key_id or not secret_access_key:
        raise ValueError("Wasabi access key and secret are required")
    try:
        boto3 = importlib.import_module("boto3")
    except ImportError as error:
        raise WasabiSetupError("Install the optional 'wasabi' dependency") from error
    return boto3.client(
        "s3", aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key, region_name=region,
        endpoint_url=endpoint,
    )
