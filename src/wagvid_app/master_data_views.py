"""Organization-scoped master-data administration views.

CRUD/archive/merge operations are kept separate from capture/review views. Every mutation is
permission checked and append-only audited; historical records are deactivated/archived rather
than deleted.
"""

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import GymnastForm
from .master_data_operations import GymnastMergeError, merge_gymnasts
from .models import Gymnast, Level
from .views import active_organization, can_manage_master_data


class LevelForm(forms.ModelForm):
    class Meta:
        model = Level
        fields = ["name", "active"]

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if self.organization:
            matches = self.organization.levels.filter(name__iexact=name)
            if self.instance and self.instance.pk:
                matches = matches.exclude(pk=self.instance.pk)
            if matches.exists():
                raise forms.ValidationError("Der findes allerede et niveau med dette navn.")
        return name


class GymnastMergeForm(forms.Form):
    survivor = forms.ModelChoiceField(
        queryset=Gymnast.objects.none(),
        label="Bevar denne profil",
        help_text="Rutiner og video fra dubletten flyttes til denne aktive profil.",
    )
    reason = forms.CharField(
        label="Begrundelse",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Påkrævet og gemmes i audit-loggen.",
    )

    def __init__(self, *args, organization=None, duplicate=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.duplicate = duplicate
        if organization:
            queryset = organization.gymnasts.filter(archived_at__isnull=True)
            if duplicate is not None:
                queryset = queryset.exclude(pk=duplicate.pk).filter(discipline=duplicate.discipline)
            self.fields["survivor"].queryset = queryset.select_related("level").order_by(
                "display_name"
            )


def _organization(request):
    return active_organization(request)


def _can_manage(request, organization):
    return bool(organization and can_manage_master_data(request, organization))


def _audit(organization, request, action, object_type, object_id, *, reason="", metadata=None):
    organization.audit_events.create(
        actor=request.user,
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        reason=reason,
        metadata=metadata or {},
    )


@login_required
def gymnasts(request):
    organization = _organization(request)
    if not organization:
        return HttpResponseForbidden()
    queryset = organization.gymnasts.filter(archived_at__isnull=True).select_related("level")
    return render(
        request,
        "wagvid/gymnasts.html",
        {
            "organization": organization,
            "gymnasts": queryset,
            "can_manage": _can_manage(request, organization),
        },
    )


@login_required
def gymnast_edit(request, gymnast_id):
    organization = _organization(request)
    if not _can_manage(request, organization):
        return HttpResponseForbidden()
    gymnast = get_object_or_404(Gymnast, pk=gymnast_id, organization=organization)
    form = GymnastForm(request.POST or None, instance=gymnast, organization=organization)
    if request.method == "POST" and form.is_valid():
        changed = sorted(form.changed_data)
        updated = form.save()
        _audit(
            organization,
            request,
            "gymnast.updated",
            "gymnast",
            updated.id,
            metadata={"changed_fields": changed},
        )
        messages.success(request, f"{updated.display_name} er opdateret og audit-logget.")
        return redirect("gymnasts")
    return render(
        request,
        "wagvid/form.html",
        {
            "title": f"Redigér {gymnast.display_name}",
            "form": form,
            "organization": organization,
        },
    )


@login_required
@require_POST
def gymnast_archive(request, gymnast_id):
    organization = _organization(request)
    if not _can_manage(request, organization):
        return HttpResponseForbidden()
    gymnast = get_object_or_404(Gymnast, pk=gymnast_id, organization=organization)
    if gymnast.archived_at is None:
        gymnast.archived_at = timezone.now()
        gymnast.save(update_fields=["archived_at", "updated_at"])
        _audit(
            organization,
            request,
            "gymnast.archived",
            "gymnast",
            gymnast.id,
            reason=request.POST.get("reason", ""),
        )
        messages.success(
            request,
            f"{gymnast.display_name} er arkiveret. Historiske data er bevaret.",
        )
    return redirect("gymnasts")


@login_required
def gymnast_merge(request, gymnast_id):
    organization = _organization(request)
    if not _can_manage(request, organization):
        return HttpResponseForbidden()
    duplicate = get_object_or_404(
        Gymnast.objects.select_related("level"),
        pk=gymnast_id,
        organization=organization,
        archived_at__isnull=True,
    )
    form = GymnastMergeForm(
        request.POST or None,
        organization=organization,
        duplicate=duplicate,
    )
    if request.method == "POST" and form.is_valid():
        survivor = form.cleaned_data["survivor"]
        try:
            result = merge_gymnasts(
                organization=organization,
                survivor_id=survivor.id,
                duplicate_id=duplicate.id,
                actor=request.user,
                reason=form.cleaned_data["reason"],
            )
        except GymnastMergeError as error:
            form.add_error(None, str(error))
        else:
            messages.success(
                request,
                (
                    f"{duplicate.display_name} er flettet ind i {survivor.display_name}. "
                    f"Flyttede {result.routines_moved} rutiner og {result.media_moved} videoer."
                ),
            )
            return redirect("gymnasts")
    return render(
        request,
        "wagvid/gymnast_merge.html",
        {
            "organization": organization,
            "duplicate": duplicate,
            "form": form,
        },
    )


@login_required
def archived_gymnasts(request):
    organization = _organization(request)
    if not organization:
        return HttpResponseForbidden()
    queryset = organization.gymnasts.filter(archived_at__isnull=False).select_related("level")
    return render(
        request,
        "wagvid/archived_gymnasts.html",
        {
            "organization": organization,
            "gymnasts": queryset,
            "can_manage": _can_manage(request, organization),
        },
    )


@login_required
@require_POST
def gymnast_restore(request, gymnast_id):
    organization = _organization(request)
    if not _can_manage(request, organization):
        return HttpResponseForbidden()
    gymnast = get_object_or_404(Gymnast, pk=gymnast_id, organization=organization)
    if gymnast.archived_at is not None:
        gymnast.archived_at = None
        gymnast.save(update_fields=["archived_at", "updated_at"])
        _audit(organization, request, "gymnast.restored", "gymnast", gymnast.id)
        messages.success(request, f"{gymnast.display_name} er gendannet som aktiv profil.")
    return redirect("gymnasts-archived")


@login_required
def levels(request):
    organization = _organization(request)
    if not organization:
        return HttpResponseForbidden()
    return render(
        request,
        "wagvid/levels.html",
        {
            "organization": organization,
            "levels": organization.levels.all(),
            "can_manage": _can_manage(request, organization),
        },
    )


@login_required
def level_create(request):
    organization = _organization(request)
    if not _can_manage(request, organization):
        return HttpResponseForbidden()
    form = LevelForm(request.POST or None, organization=organization)
    if request.method == "POST" and form.is_valid():
        level = form.save(commit=False)
        level.organization = organization
        level.save()
        _audit(organization, request, "level.created", "level", level.id)
        messages.success(request, f"Niveauet {level.name} er oprettet.")
        return redirect("levels")
    return render(
        request,
        "wagvid/master_form.html",
        {
            "title": "Opret niveau",
            "form": form,
            "organization": organization,
            "back_url_name": "levels",
        },
    )


@login_required
def level_edit(request, level_id):
    organization = _organization(request)
    if not _can_manage(request, organization):
        return HttpResponseForbidden()
    level = get_object_or_404(Level, pk=level_id, organization=organization)
    form = LevelForm(request.POST or None, instance=level, organization=organization)
    if request.method == "POST" and form.is_valid():
        changed = sorted(form.changed_data)
        updated = form.save()
        _audit(
            organization,
            request,
            "level.updated",
            "level",
            updated.id,
            metadata={"changed_fields": changed},
        )
        messages.success(request, f"Niveauet {updated.name} er opdateret.")
        return redirect("levels")
    return render(
        request,
        "wagvid/master_form.html",
        {
            "title": f"Redigér niveau: {level.name}",
            "form": form,
            "organization": organization,
            "back_url_name": "levels",
        },
    )


@login_required
@require_POST
def level_archive(request, level_id):
    organization = _organization(request)
    if not _can_manage(request, organization):
        return HttpResponseForbidden()
    level = get_object_or_404(Level, pk=level_id, organization=organization)
    if level.active:
        level.active = False
        level.save(update_fields=["active", "updated_at"])
        _audit(organization, request, "level.archived", "level", level.id)
        messages.success(
            request,
            f"Niveauet {level.name} er deaktiveret; historiske profiler er bevaret.",
        )
    return redirect("levels")
