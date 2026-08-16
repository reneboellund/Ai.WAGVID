from django import forms

from .models import Gymnast


class GymnastForm(forms.ModelForm):
    class Meta:
        model = Gymnast
        fields = ["display_name", "license_number", "level", "kiga_id"]

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization:
            self.fields["level"].queryset = organization.levels.filter(active=True)
