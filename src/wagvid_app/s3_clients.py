"""Lazy provider-aware Boto3 client construction without persisted credentials."""

from __future__ import annotations

import importlib

from .secret_refs import EnvironmentSecretResolver
from .storage_providers import StorageCapability, provider_definition
from .wasabi_provider import WasabiSetupError


def create_profile_client(connection, *, resolver=None):
    resolver = resolver or EnvironmentSecretResolver()
    definition = provider_definition(connection.provider)
    if not connection.tls_verify and connection.environment not in {"dev", "development", "lab", "test"}:
        raise ValueError("TLS verification cannot be disabled outside a lab environment")
    if connection.auth_mode == "workload-identity" and (
        definition.capabilities[StorageCapability.WORKLOAD_IDENTITY].value != "supported"
    ):
        raise ValueError(f"{connection.provider} does not support workload identity")
    try:
        boto3 = importlib.import_module("boto3")
        config_module = importlib.import_module("botocore.config")
    except ImportError as error:
        raise WasabiSetupError("Install the optional 'wasabi' S3 dependency") from error

    kwargs = {
        "region_name": connection.region,
        "endpoint_url": connection.endpoint,
        "verify": resolver.resolve(connection.custom_ca_secret_ref)
        if connection.custom_ca_secret_ref
        else connection.tls_verify,
        "config": config_module.Config(
            signature_version="s3v4",
            s3={"addressing_style": connection.addressing_style},
            retries={"max_attempts": 5, "mode": "standard"},
        ),
    }
    if connection.auth_mode == "access-key":
        kwargs.update(
            aws_access_key_id=resolver.resolve(connection.access_key_secret_ref),
            aws_secret_access_key=resolver.resolve(connection.secret_key_secret_ref),
        )
    elif connection.auth_mode != "workload-identity":
        raise ValueError("unsupported storage authentication mode")
    client = boto3.client("s3", **kwargs)
    if connection.role_arn:
        sts = boto3.client("sts", region_name=connection.region)
        credentials = sts.assume_role(
            RoleArn=connection.role_arn,
            RoleSessionName=f"wagvid-{str(connection.id)[:8]}",
        )["Credentials"]
        kwargs.update(
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
        )
        client = boto3.client("s3", **kwargs)
    return client
