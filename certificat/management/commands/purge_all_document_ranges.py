from django.core.management.base import BaseCommand, CommandError

from certificat.models import DocumentRange


class Command(BaseCommand):
    help = "Delete ALL rows from DocumentRange (plajele vechi). Use --yes to confirm."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Confirm deletion")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted")

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        confirmed = options.get("yes", False)

        qs = DocumentRange.objects.all()
        count = qs.count()
        if count == 0:
            self.stdout.write(self.style.WARNING("No DocumentRange rows to delete."))
            return

        self.stdout.write(self.style.WARNING(f"Will delete {count} DocumentRange rows."))

        if dry_run or not confirmed:
            for dr in qs.select_related("gestiune", "tipologie").iterator():
                gest = dr.gestiune.nume if dr.gestiune else "(n/a)"
                tip = dr.tipologie.nume if dr.tipologie else "(n/a)"
                self.stdout.write(f"[DRY-RUN] id={dr.id} | gestiune='{gest}' | tipologie='{tip}' | start='{dr.numar_inceput}' | curent='{dr.numar_curent}' | final='{dr.numar_final}'")
            if not confirmed:
                self.stdout.write(self.style.WARNING("Run again with --yes to confirm deletion."))
            return

        deleted, _ = qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} rows from DocumentRange."))


