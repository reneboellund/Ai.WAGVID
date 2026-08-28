import json
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from wagvid_app.models import (
    AnalysisDeliverable,
    AnalysisJob,
    AnalysisResult,
    DeductionCandidate,
    Event,
    Gymnast,
    Level,
    MediaAsset,
    Membership,
    Organization,
    Routine,
)
from wagvid_app.pipeline_artifacts import publish_pipeline_artifact
from wagvid_app.reporting import generate_score_verification, plan_event_analysis


def dscore_payload(apparatus="BB"):
    return {
        "schema": "ai.wagvid.dscore-ledger.v1",
        "rulepack_id": "wag-2025",
        "rulepack_digest": "c" * 64,
        "policy_digest": "d" * 64,
        "apparatus": apparatus,
        "units_per_point": 10,
        "outcomes": [],
        "ambiguities": [],
        "possible_total_units": [],
        "resolved_score": None,
        "evaluation_blockers": ["no-accepted-elements"],
    }


def fixture(slug="reports"):
    user = User.objects.create_user(slug, password="secret")
    organization = Organization.objects.create(name=slug, slug=slug)
    Membership.objects.create(user=user, organization=organization, role=Membership.Role.DOMAIN_REVIEWER)
    level = Level.objects.create(organization=organization, name="Senior")
    gymnast = Gymnast.objects.create(organization=organization, display_name="Ada", license_number=f"{slug}-1", level=level)
    event = Event.objects.create(organization=organization, name="Cup", kind=Event.Kind.COMPETITION, starts_at=timezone.now(), external_id=f"event-{slug}")
    routine = Routine.objects.create(organization=organization, event=event, gymnast=gymnast, apparatus=Routine.Apparatus.BEAM, rulepack_id="wag-2025", external_id=f"routine-{slug}", official_d_score=Decimal("5.200"), official_e_score=Decimal("7.900"), official_final_score=Decimal("13.100"), official_frozen_at=timezone.now())
    media = MediaAsset.objects.create(organization=organization, gymnast=gymnast, routine=routine, kind=MediaAsset.Kind.COMPETITION, state=MediaAsset.State.STORED, object_key=f"{slug}/video.mp4", sha256="a" * 64, content_type="video/mp4", size_bytes=1000, recorded_at=timezone.now())
    job = AnalysisJob.objects.create(organization=organization, media=media, state=AnalysisJob.State.COMPLETED, scope="full", rulepack_id="wag-2025", model_profile="validated-profile", revision=1)
    result = AnalysisResult.objects.create(analysis_job=job, state=AnalysisResult.State.FROZEN, proposed_d_score=Decimal("5.200"), proposed_e_score=Decimal("7.800"), proposed_neutral=Decimal("0.000"), proposed_final_score=Decimal("13.000"), score_ledger={"arithmetic": ["5.2 + 7.8 = 13.0"]}, model_run={"model_digest": "b" * 64, "quality": {"status": "usable"}, "camera": {"view": "side"}}, frozen_at=timezone.now())
    DeductionCandidate.objects.create(result=result, criterion="landing-step", rule_reference="WAG-BB-LANDING", start_ms=59000, end_ms=60200, proposed_amount=Decimal("0.100"), model_confidence=Decimal("0.9200"), evidence={"frame": 1475})
    return user, organization, event, routine, job


@pytest.mark.django_db
def test_score_report_requires_freeze_and_is_immutable():
    user, organization, _event, _routine, job = fixture()
    report = generate_score_verification(job=job, actor=user)
    assert report.kind == AnalysisDeliverable.Kind.SCORE_VERIFICATION
    assert report.payload["scores"]["official"]["final"] == "13.100"
    assert report.payload["deductions"][0]["evidence"]["frame"] == 1475
    assert report.payload["unresolved"] == [str(job.result.deductions.get().id)]
    assert len(report.payload_digest) == 64
    assert organization.audit_events.filter(action="report.score-verification-generated").exists()
    report.revision = 2
    with pytest.raises(ValueError, match="immutable"):
        report.save()

    job.result.state = AnalysisResult.State.NEEDS_REVIEW
    job.result.save(update_fields=["state", "updated_at"])
    with pytest.raises(ValueError, match="frozen"):
        generate_score_verification(job=job, actor=user)


@pytest.mark.django_db
def test_competition_batch_control_plan_withholds_identity_and_official_values():
    user, organization, event, _routine, _job = fixture("batch")
    run = plan_event_analysis(event=event, actor=user, analysis_profile_digest="c" * 64)
    assert run.task_count == 1 and run.excluded_count == 0
    encoded = json.dumps(run.control_plan)
    assert "athlete_external_id" not in encoded
    assert "competition_external_id" not in encoded
    assert "official_result" not in encoded
    assert "13.100" not in encoded
    assert run.control_plan["withheld_official_digests"]
    assert organization.audit_events.filter(action="competition.batch-planned").exists()
    repeated = plan_event_analysis(event=event, actor=user, analysis_profile_digest="c" * 64)
    assert repeated.id == run.id


@pytest.mark.django_db
def test_competition_batch_export_is_scoped_and_digest_bound(client):
    user, _organization, event, _routine, _job = fixture("batch-export")
    run = plan_event_analysis(event=event, actor=user, analysis_profile_digest="d" * 64)
    client.force_login(user)
    response = client.get(reverse("competition-batch-json", args=[run.id]))
    assert response.status_code == 200
    assert response["ETag"] == f'"{run.plan_digest}"'
    assert "official_result" not in response.content.decode()

    other, _other_org, _event2, _routine2, _job2 = fixture("batch-export-other")
    client.force_login(other)
    assert client.get(reverse("competition-batch-json", args=[run.id])).status_code == 404


@pytest.mark.django_db
def test_report_routes_are_organization_scoped(client):
    user, _organization, _event, _routine, job = fixture("route")
    report = generate_score_verification(job=job, actor=user)
    client.force_login(user)
    assert client.get(reverse("reports")).status_code == 200
    response = client.get(reverse("report-json", args=[report.id]))
    assert response.status_code == 200
    assert response["ETag"] == f'"{report.payload_digest}"'
    assert response["Cache-Control"] == "private, no-store"

    other, _other_org, _event2, _routine2, _job2 = fixture("other-route")
    client.force_login(other)
    assert client.get(reverse("report-detail", args=[report.id])).status_code == 404
    assert client.get(reverse("report-json", args=[report.id])).status_code == 404


@pytest.mark.django_db
def test_score_report_web_generation_rejects_unfrozen_result(client):
    user, _organization, _event, _routine, job = fixture("unfrozen")
    job.result.state = AnalysisResult.State.NEEDS_REVIEW
    job.result.frozen_at = None
    job.result.save(update_fields=["state", "frozen_at", "updated_at"])
    client.force_login(user)
    response = client.post(reverse("score-report-generate", args=[job.id]), follow=True)
    assert response.status_code == 200
    assert not AnalysisDeliverable.objects.filter(analysis_job=job).exists()


@pytest.mark.django_db
def test_pipeline_artifact_is_schema_validated_provenance_bound_and_idempotent():
    user, organization, _event, _routine, job = fixture("pipeline")
    payload = dscore_payload()
    artifact = publish_pipeline_artifact(
        job=job,
        actor=user,
        payload=payload,
        upstream_digests=("e" * 64, "e" * 64),
    )
    repeated = publish_pipeline_artifact(
        job=job, actor=user, payload=payload, upstream_digests=("e" * 64,)
    )
    assert repeated.id == artifact.id
    assert artifact.kind == AnalysisDeliverable.Kind.DSCORE_LEDGER
    assert artifact.provenance["media_sha256"] == job.media.sha256
    assert artifact.provenance["upstream_digests"] == ["e" * 64]
    assert organization.audit_events.filter(action="analysis.pipeline-artifact-published").exists()


@pytest.mark.django_db
def test_pipeline_artifact_rejects_apparatus_mismatch_and_cross_org_access(client):
    user, _organization, _event, _routine, job = fixture("pipeline-scope")
    with pytest.raises(ValueError, match="routine"):
        publish_pipeline_artifact(job=job, actor=user, payload=dscore_payload("FX"))

    artifact = publish_pipeline_artifact(job=job, actor=user, payload=dscore_payload())
    other, _other_org, _event2, _routine2, _job2 = fixture("pipeline-scope-other")
    client.force_login(other)
    assert client.get(reverse("report-json", args=[artifact.id])).status_code == 404


@pytest.mark.django_db
def test_pipeline_publish_route_freezes_valid_artifact(client):
    user, _organization, _event, _routine, job = fixture("pipeline-route")
    client.force_login(user)
    response = client.post(
        reverse("pipeline-artifact-publish", args=[job.id]),
        {"payload": json.dumps(dscore_payload()), "upstream_digests": "f" * 64},
    )
    assert response.status_code == 302
    artifact = job.deliverables.get(kind=AnalysisDeliverable.Kind.DSCORE_LEDGER)
    assert response.url == reverse("report-detail", args=[artifact.id])
    assert artifact.provenance["upstream_digests"] == ["f" * 64]
