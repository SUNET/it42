from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils import timezone

from it42.org.members.models import Membership


class Command(BaseCommand):
    help = "Make an existing user (who has logged in once) the first admin of this org."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--subject", required=True, help="The user's sso_subject (IdP uid)")

    def handle(self, *args: Any, **options: Any) -> None:
        subject: str = options["subject"]
        User = get_user_model()
        try:
            user = User.objects.get(sso_subject=subject)
        except User.DoesNotExist as exc:
            raise CommandError(
                f"No user with sso_subject {subject!r}. They must log in to "
                f"{settings.SITE_URL} once first."
            ) from exc
        _membership, created = Membership.objects.update_or_create(
            user=user,
            defaults={"role": Membership.Role.ADMIN, "approved_at": timezone.now()},
        )
        verb = "Created" if created else "Updated"
        self.stdout.write(f"{verb} admin membership for {user} in {settings.ORG_NAME}.")
