from django import forms

from .models import Gymnast, ReviewDecision, ScoreComparisonReview


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
