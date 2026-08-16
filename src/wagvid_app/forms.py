from django import forms

from .models import Gymnast


class GymnastForm(forms.ModelForm):
    class Meta:
        model = Gymnast
        fields = ("display_name", "license_number", "level", "kiga_id")

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["display_name"].label = "Navn"
        self.fields["display_name"].widget.attrs.update(
            {"placeholder": "Gymnastens fulde navn", "autocomplete": "name"}
        )
        self.fields["license_number"].label = "Licensnummer"
        self.fields["license_number"].widget.attrs.update(
            {"placeholder": "Fx DK-2026-1042", "autocomplete": "off"}
        )
        self.fields["level"].label = "Niveau"
        self.fields["kiga_id"].label = "KIGA-ID"
        self.fields["kiga_id"].widget.attrs.update(
            {"placeholder": "Valgfri ekstern identitet", "autocomplete": "off"}
        )
        if organization:
            self.fields["level"].queryset = organization.levels.filter(active=True)
