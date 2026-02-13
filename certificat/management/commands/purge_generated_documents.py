from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from certificat.models import GeneratedDocument


class Command(BaseCommand):
    help = "Delete all GeneratedDocument records and their PDF files. Use --yes to confirm."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Confirm deletion without prompt")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without performing it")
        parser.add_argument("--date-lte", dest="date_lte", default=None, help="Optional: delete only documents with created_at date <= YYYY-MM-DD")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        confirmed = options["yes"]
        date_lte = options["date_lte"]

        qs = GeneratedDocument.objects.all()
        if date_lte:
            try:
                dt = datetime.strptime(date_lte, "%Y-%m-%d").date()
            except ValueError:
                raise CommandError("--date-lte must be in format YYYY-MM-DD")
            qs = qs.filter(created_at__date__lte=dt)

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("No GeneratedDocument records found for deletion."))
            return

        self.stdout.write(self.style.WARNING(f"Will delete {total} GeneratedDocument records."))

        if dry_run:
            for doc in qs.iterator():
                self.stdout.write(f"[DRY-RUN] Would delete id={doc.id}, aviz={doc.aviz_number}, file={doc.pdf_file.name if doc.pdf_file else '-'}")
            return

        if not confirmed:
            raise CommandError("Refusing to delete without --yes. Re-run with --yes to confirm.")

        # Delete files first, then DB rows
        deleted_files = 0
        for doc in qs.iterator():
            if doc.pdf_file:
                try:
                    storage = doc.pdf_file.storage
                    # If storage supports path(), use safer exists
                    try:
                        if storage.exists(doc.pdf_file.name):
                            doc.pdf_file.delete(save=False)
                            deleted_files += 1
                    except Exception:
                        # Fallback attempt
                        doc.pdf_file.delete(save=False)
                        deleted_files += 1
                except Exception as e:
                    self.stderr.write(f"Failed to delete file for doc id={doc.id}: {e}")

        deleted_objects = total
        qs.delete()

        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_objects} GeneratedDocument rows and {deleted_files} files."))


