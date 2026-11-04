"""Reviewer profile: payment information and the passport PDF."""

from pathlib import Path
from typing import Any

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from it42.org.review.models import ReviewerProfile

PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def test_payment_form_saves(make_panel: Any, make_seat: Any, seat_client: Any) -> None:
    seat = make_seat(make_panel(), "r1@example.org")
    client = seat_client(seat)
    assert client.get("/profile/").status_code == 200
    body = {
        "save_profile": "1",
        "address": "Storgatan 1\n111 22 Stockholm",
        "account_holder": "Ingrid Nyström",
        "bank_name": "SEB",
        "iban": "SE3550000000054910000003",
        "bic": "ESSESESS",
        "keywords": "photonics, lasers,, ",
    }
    assert client.post("/profile/", body).status_code == 302
    profile = ReviewerProfile.objects.get(user=seat.user)
    assert profile.iban == "SE3550000000054910000003" and profile.has_payment_info
    assert profile.keyword_list == ["photonics", "lasers"]
    page = client.get("/profile/")
    assert b"SE3550000000054910000003" in page.content


def test_passport_upload_replace_download_delete(
    make_panel: Any, make_seat: Any, seat_client: Any, settings: Any
) -> None:
    seat = make_seat(make_panel(), "r1@example.org")
    client = seat_client(seat)
    bad = client.post(
        "/profile/", {"upload": "1", "passport": SimpleUploadedFile("x.pdf", b"not a pdf")}
    )
    assert bad.status_code == 200 and b"not a PDF" in bad.content
    assert not ReviewerProfile.objects.get(user=seat.user).passport
    ok = client.post("/profile/", {"upload": "1", "passport": SimpleUploadedFile("pass.pdf", PDF)})
    assert ok.status_code == 302
    profile = ReviewerProfile.objects.get(user=seat.user)
    first_path = Path(profile.passport.path)
    assert first_path.exists() and profile.passport_name == "pass.pdf"
    assert profile.passport_size == len(PDF) and profile.passport_uploaded_at is not None
    download = client.get("/profile/passport/")
    assert download.status_code == 200 and b"".join(download.streaming_content) == PDF
    # replacing removes the old file
    client.post("/profile/", {"upload": "1", "passport": SimpleUploadedFile("new.pdf", PDF)})
    profile.refresh_from_db()
    assert not first_path.exists() and profile.passport_name == "new.pdf"
    assert client.post("/profile/passport/delete/").status_code == 302
    profile.refresh_from_db()
    assert not profile.passport and profile.passport_name == "" and profile.passport_size == 0
    assert client.get("/profile/passport/").status_code == 404


def test_passport_is_private_to_its_owner(
    make_panel: Any, make_seat: Any, seat_client: Any
) -> None:
    panel = make_panel()
    owner = make_seat(panel, "r1@example.org")
    other = make_seat(panel, "r2@example.org")
    seat_client(owner).post(
        "/profile/", {"upload": "1", "passport": SimpleUploadedFile("pass.pdf", PDF)}
    )
    assert seat_client(other).get("/profile/passport/").status_code == 404
    assert ReviewerProfile.objects.filter(user=other.user).exists()  # own empty profile only


def test_upload_form_is_the_last_form_on_the_profile_page(
    make_panel: Any, make_seat: Any, seat_client: Any
) -> None:
    """scripts/acceptance.py finds the passport form as the last form on the page."""
    client: Client = seat_client(make_seat(make_panel(), "r1@example.org"))
    html = client.get("/profile/").content.decode()
    assert html.rstrip().rfind('name="upload"') > html.rfind('name="save_profile"')
