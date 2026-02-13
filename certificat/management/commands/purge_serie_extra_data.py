from django.core.management.base import BaseCommand, CommandError

from certificat.models import SerieExtraData


class Command(BaseCommand):
    help = "Delete all rows from certificat_serieextradata (SerieExtraData). Use --yes to confirm."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Confirm deletion without prompt")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without performing it")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        confirmed = options["yes"]

        qs = SerieExtraData.objects.all()
        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("SerieExtraData is already empty."))
            return

        self.stdout.write(self.style.WARNING(f"Will delete {total} SerieExtraData rows."))

        if dry_run:
            for row in qs.iterator():
                self.stdout.write(f"[DRY-RUN] Would delete serie='{row.serie}' (id={row.id})")
            return

        if not confirmed:
            raise CommandError("Refusing to delete without --yes. Re-run with --yes to confirm.")

        deleted = total
        qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} SerieExtraData rows."))


