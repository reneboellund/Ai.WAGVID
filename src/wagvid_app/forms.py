from django import forms

from .models import Gymnast, ReviewDecision, ScoreComparisonReview, StorageConnection
from .storage_providers import StorageCapability, provider_definition
from .storage_types import BucketRole
from .wasabi import WASABI_REGION_ENDPOINTS


class GymnastForm(forms.ModelForm):
    class Meta:
        model = Gymnast
        fields = ["display_name", "license_number", "discipline", "level", "kiga_id"]

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            self.fields["level"].queryset = organization.levels.filter(active=True)


class GymnastImportForm(forms.Form):
    csv_file = forms.FileField(label="Gymnast-CSV")

    def clean_csv_file(self):
        upload = self.cleaned_data["csv_file"]
        if upload.size > 2 * 1024 * 1024:
            raise forms.ValidationError("CSV-filen må højst være 2 MB.")
        try:
            upload.seek(0)
            upload.decoded_text = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise forms.ValidationError("CSV-filen skal være UTF-8.") from exc
        return upload


class KigaImportForm(forms.Form):
    json_file = forms.FileField(label="KIGA competition-video JSON")

    def clean_json_file(self):
        upload = self.cleaned_data["json_file"]
        if upload.size > 5 * 1024 * 1024:
            raise forms.ValidationError("KIGA JSON-filen må højst være 5 MB.")
        try:
            upload.seek(0)
            upload.decoded_text = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise forms.ValidationError("KIGA JSON-filen skal være UTF-8.") from exc
        return upload


class ReviewDecisionForm(forms.ModelForm):
    class Meta:
        model = ReviewDecision
        fields = ["decision", "accepted_amount", "notes"]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == ReviewDecision.Decision.CORRECT_AI and cleaned.get(
            "accepted_amount"
        ) is None:
            self.add_error("accepted_amount", "Angiv det korrigerede fradrag.")
        return cleaned


class ScoreComparisonReviewForm(forms.ModelForm):
    class Meta:
        model = ScoreComparisonReview
        fields = [
            "decision",
            "accepted_d_score",
            "accepted_e_score",
            "accepted_neutral",
            "accepted_final_score",
            "notes",
        ]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == ScoreComparisonReview.Decision.CORRECTED_LABELS:
            for field in (
                "accepted_d_score",
                "accepted_e_score",
                "accepted_neutral",
                "accepted_final_score",
            ):
                if cleaned.get(field) is None:
                    self.add_error(field, "Alle korrigerede scorefelter skal udfyldes.")
        return cleaned


class StorageConnectionForm(forms.ModelForm):
    class Meta:
        model = StorageConnection
        fields = [
            "name",
            "provider",
            "project_slug",
            "environment",
            "region",
            "endpoint",
            "tls_verify",
            "custom_ca_secret_ref",
            "addressing_style",
            "auth_mode",
            "role_arn",
            "account_fingerprint",
            "access_key_secret_ref",
            "secret_key_secret_ref",
            "originals_shards",
            "derivatives_shards",
            "include_audit_bucket",
            "enable_versioning",
            "governance_profile",
            "provisioning_enabled",
            "existing_bucket_map",
            "pricing_model",
            "minimum_storage_days",
        ]
        help_texts = {
            "access_key_secret_ref": "Fx env:WAGVID_WASABI_ACCESS_KEY. Selve nøglen gemmes ikke.",
            "secret_key_secret_ref": "Fx env:WAGVID_WASABI_SECRET_KEY. Selve secret gemmes ikke.",
            "custom_ca_secret_ref": "Valgfri reference til CA bundle, fx env:WAGVID_STORAGE_CA.",
            "existing_bucket_map": (
                'JSON mapping, fx {"originals":["bucket-a"],"results":["bucket-b"]}.'
            ),
        }

    def clean(self):
        cleaned = super().clean()
        pricing = cleaned.get("pricing_model")
        days = cleaned.get("minimum_storage_days")
        provider_id = cleaned.get("provider")
        definition = provider_definition(provider_id) if provider_id else None
        expected = {StorageConnection.PricingModel.PAY_GO: 90, StorageConnection.PricingModel.RCS: 30}
        if pricing in expected and days != expected[pricing]:
            self.add_error(
                "minimum_storage_days",
                f"{pricing} skal bruge den eksplicitte minimumsperiode på {expected[pricing]} dage.",
            )
        if pricing == StorageConnection.PricingModel.NONE and days != 0:
            self.add_error("minimum_storage_days", "Ingen minimumsperiode skal bruge 0 dage.")
        if provider_id != StorageConnection.Provider.WASABI and pricing in expected:
            self.add_error("pricing_model", "Wasabi Pay-Go/RCS kan kun vælges for Wasabi.")
        if provider_id == StorageConnection.Provider.WASABI and pricing == StorageConnection.PricingModel.NONE:
            self.add_error("pricing_model", "Vælg Wasabis faktiske pris-/minimumsmodel.")
        for field in (
            "access_key_secret_ref",
            "secret_key_secret_ref",
            "custom_ca_secret_ref",
        ):
            value = cleaned.get(field, "")
            if value and not value.startswith(("env:", "vault:", "secret:")):
                self.add_error(field, "Brug en secret-reference; credentials må ikke gemmes her.")
        auth_mode = cleaned.get("auth_mode")
        if auth_mode == "access-key":
            for field in ("access_key_secret_ref", "secret_key_secret_ref"):
                if not cleaned.get(field):
                    self.add_error(field, "Access-key login kræver begge secret-referencer.")
        elif definition and definition.capabilities[StorageCapability.WORKLOAD_IDENTITY].value != "supported":
            self.add_error("auth_mode", f"{definition.label} understøtter ikke workload identity.")
        environment = cleaned.get("environment")
        endpoint = cleaned.get("endpoint", "")
        if endpoint and not endpoint.startswith("https://") and environment not in {
            "dev", "development", "lab", "test"
        }:
            self.add_error("endpoint", "HTTPS er påkrævet uden for et eksplicit labmiljø.")
        if not cleaned.get("tls_verify") and environment not in {"dev", "development", "lab", "test"}:
            self.add_error("tls_verify", "TLS-verifikation kan kun slås fra i lab/test.")
        if definition and definition.existing_bucket_only and cleaned.get("provisioning_enabled"):
            self.add_error("provisioning_enabled", f"{definition.label} bruger existing-bucket mode.")
        region = cleaned.get("region")
        endpoint = cleaned.get("endpoint")
        if (
            provider_id == StorageConnection.Provider.WASABI
            and region in WASABI_REGION_ENDPOINTS
            and endpoint != WASABI_REGION_ENDPOINTS[region]
        ):
            self.add_error("endpoint", "Endpoint matcher ikke den valgte officielle Wasabi-region.")
        return cleaned


# Compatibility import for code using the milestone-1 Wasabi-specific name.
WasabiConnectionForm = StorageConnectionForm


class StorageRoleAssignmentForm(forms.Form):
    role = forms.ChoiceField(choices=[(role.value, role.value.title()) for role in BucketRole])
    connection = forms.ModelChoiceField(queryset=StorageConnection.objects.none())

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["connection"].queryset = organization.storage_connections.filter(active=True)
