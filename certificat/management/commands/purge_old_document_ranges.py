import re
from typing import Optional, Tuple

from django.core.management.base import BaseCommand, CommandError

from certificat.models import DocumentRange, Gestiune


SERIES_PREFIX_TO_GESTIUNE = {
    'VN': 'DEPOZIT TISITA, VRANCEA',
    'AB': 'Depozit ALBA-IULIA, ALBA',
    'OT': 'Depozit CARACAL, OLT',
    '5TM': 'Depozit GHIRODA, TIMIS',
    'IL': 'Depozit SLOBOZIA, IALOMITA',
}


def split_prefix_and_number(identifier: str) -> Optional[Tuple[str, int, int]]:
    if not identifier:
        return None
    m = re.search(r"^(.*?)(\d+)$", identifier.strip())
    if not m:
        return None
    prefix, digits = m.group(1), m.group(2)
    try:
        return prefix, int(digits), len(digits)
    except ValueError:
        return None


class Command(BaseCommand):
    help = (
        "Purgează plajele vechi din DocumentRange conform regulilor: "
        "(1) Pentru VN: șterge plajele cu lățimea numerică 5 (ex: VN00002). "
        "(2) Pentru AB, IL, 5TM: păstrează DOAR tipologia 'General', șterge restul."
    )

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Confirmă ștergerea")
        parser.add_argument("--dry-run", action="store_true", help="Afișează ce s-ar șterge, fără a modifica DB")

    def handle(self, *args, **options):
        confirmed = options.get("yes", False)
        dry_run = options.get("dry_run", False)

        total = 0
        deleted = 0

        qs = DocumentRange.objects.select_related("gestiune", "tipologie").all()
        if not qs.exists():
            self.stdout.write(self.style.WARNING("Nu există plaje în DocumentRange."))
            return

        to_delete_ids = []

        for dr in qs:
            total += 1
            gest_name = dr.gestiune.nume if dr.gestiune else "(n/a)"
            tip_name = dr.tipologie.nume if dr.tipologie else "(n/a)"

            # Regula 1: VN cu sufix numeric pe 5 cifre => plajă veche
            candidate = dr.numar_inceput or dr.numar_curent or dr.numar_final or ""
            split = split_prefix_and_number(candidate)
            mark_old = False
            if split:
                prefix, _, width = split
                if prefix.startswith("VN") and width == 5:
                    mark_old = True

            # Regula 2: AB/IL/5TM -> păstrăm doar 'General'
            if dr.gestiune and tip_name.lower() != 'general':
                if gest_name in (
                    SERIES_PREFIX_TO_GESTIUNE['AB'],
                    SERIES_PREFIX_TO_GESTIUNE['IL'],
                    SERIES_PREFIX_TO_GESTIUNE['5TM'],
                ):
                    mark_old = True

            if mark_old:
                to_delete_ids.append(dr.id)
                self.stdout.write(f"[DELETE] id={dr.id} | gestiune='{gest_name}' | tipologie='{tip_name}' | start='{dr.numar_inceput}' | curent='{dr.numar_curent}' | final='{dr.numar_final}'")

        if not to_delete_ids:
            self.stdout.write(self.style.SUCCESS("Nicio plajă de șters conform regulilor."))
            return

        if dry_run or not confirmed:
            self.stdout.write(self.style.WARNING(f"Ar fi șterse {len(to_delete_ids)} plaje. Rulează cu --yes pentru a aplica."))
            return

        deleted, _ = DocumentRange.objects.filter(id__in=to_delete_ids).delete()
        self.stdout.write(self.style.SUCCESS(f"Șterse {deleted} plaje vechi."))


