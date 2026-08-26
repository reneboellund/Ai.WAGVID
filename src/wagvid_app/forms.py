from django import forms

from .models import Gymnast, ReviewDecision, ScoreComparisonReview, StorageConnection
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


class WasabiConnectionForm(forms.ModelForm):
    class Meta:
        model = StorageConnection
        fields = [
            "name",
            "project_slug",
            "environment",
            "region",
            "endpoint",
            "account_fingerprint",
            "access_key_secret_ref",
            "secret_key_secret_ref",
            "originals_shards",
            "derivatives_shards",
            "include_audit_bucket",
            "enable_versioning",
            "pricing_model",
            "minimum_storage_days",
        ]
        help_texts = {
            "access_key_secret_ref": "Fx env:WAGVID_WASABI_ACCESS_KEY. Selve nøglen gemmes ikke.",
            "secret_key_secret_ref": "Fx env:WAGVID_WASABI_SECRET_KEY. Selve secret gemmes ikke.",
        }

    def clean(self):
        cleaned = super().clean()
        pricing = cleaned.get("pricing_model")
        days = cleaned.get("minimum_storage_days")
        expected = {StorageConnection.PricingModel.PAY_GO: 90, StorageConnection.PricingModel.RCS: 30}
        if pricing in expected and days != expected[pricing]:
            self.add_error(
                "minimum_storage_days",
                f"{pricing} skal bruge den eksplicitte minimumsperiode på {expected[pricing]} dage.",
            )
        for field in ("access_key_secret_ref", "secret_key_secret_ref"):
            value = cleaned.get(field, "")
            if value and not value.startswith(("env:", "vault:", "secret:")):
                self.add_error(field, "Brug en secret-reference; credentials må ikke gemmes her.")
        region = cleaned.get("region")
        endpoint = cleaned.get("endpoint")
        if region in WASABI_REGION_ENDPOINTS and endpoint != WASABI_REGION_ENDPOINTS[region]:
            self.add_error("endpoint", "Endpoint matcher ikke den valgte officielle Wasabi-region.")
        return cleaned
