import re
from typing import Optional, Tuple

from django.core.management.base import BaseCommand

from certificat.models import DocumentRange, GeneratedDocument, Gestiune, TipologieProdus


def split_prefix_and_number(identifier: str) -> Optional[Tuple[str, int, int]]:
    """Return (prefix, number_value, number_width) for trailing digits.

    Example: 'VN000123' -> ('VN', 123, 6)
             '5TM001128' -> ('5TM', 1128, 6)
    Returns None if no trailing digits are found.
    """
    if not identifier:
        return None
    m = re.search(r"^(.*?)(\d+)$", identifier.strip())
    if not m:
        return None
    prefix = m.group(1)
    digits = m.group(2)
    try:
        value = int(digits)
    except ValueError:
        return None
    return prefix, value, len(digits)


class Command(BaseCommand):
    help = (
        "Detect the last used number from GeneratedDocument.aviz_number for each DocumentRange, "
        "and optionally update DocumentRange.numar_curent accordingly."
    )

    def add_arguments(self, parser):
        parser.add_argument("--gestiune-id", type=int, default=None, help="Limit to a specific Gestiune ID")
        parser.add_argument("--tipologie-id", type=int, default=None, help="Limit to a specific TipologieProdus ID")
        parser.add_argument("--apply", action="store_true", help="Write computed values to DocumentRange.numar_curent")
        parser.add_argument("--dry-run", action="store_true", help="Alias for default behavior (no writes)")

    def handle(self, *args, **options):
        gestiune_id = options.get("gestiune_id")
        tipologie_id = options.get("tipologie_id")
        apply_changes = options.get("apply", False)

        qs = DocumentRange.objects.select_related("gestiune", "tipologie").all()
        if gestiune_id:
            qs = qs.filter(gestiune_id=gestiune_id)
        if tipologie_id:
            qs = qs.filter(tipologie_id=tipologie_id)

        if not qs.exists():
            self.stdout.write(self.style.WARNING("No DocumentRange rows match the filter."))
            return

        updated = 0
        inspected = 0
        for dr in qs.order_by("gestiune__nume", "tipologie__nume", "id"):
            inspected += 1
            split = split_prefix_and_number(dr.numar_inceput or dr.numar_curent or dr.numar_final or "")
            if not split:
                self.stdout.write(self.style.WARNING(f"[ID:{dr.id}] Cannot parse numeric suffix from range start/end for gestiune='{dr.gestiune}', tipologie='{dr.tipologie}'. Skipping."))
                continue
            prefix, _, width = split

            # Find all documents whose aviz_number matches the prefix and end with digits
            candidates = list(
                GeneratedDocument.objects.filter(aviz_number__startswith=prefix, is_deleted=False)
                .values_list("aviz_number", flat=True)
            )

            max_value = None
            for aviz in candidates:
                m = re.search(r"^(.*?)(\d+)$", aviz)
                if not m:
                    continue
                aviz_prefix, num_str = m.group(1), m.group(2)
                if aviz_prefix != prefix:
                    continue
                # Respect width to avoid matching other series with different padding
                if len(num_str) != width:
                    continue
                try:
                    num_val = int(num_str)
                except ValueError:
                    continue
                if max_value is None or num_val > max_value:
                    max_value = num_val

            computed_curent = None
            if max_value is not None:
                computed_curent = f"{prefix}{str(max_value).zfill(width)}"

            self.stdout.write(
                f"[ID:{dr.id}] {dr.gestiune.nume} | {dr.tipologie.nume} | prefix='{prefix}', width={width} -> last_used='{computed_curent or '-'}' (current='{dr.numar_curent or '-'}')"
            )

            if apply_changes and computed_curent and computed_curent != dr.numar_curent:
                dr.numar_curent = computed_curent
                dr.save(update_fields=["numar_curent"])
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"Done. inspected={inspected}, updated={updated}"))


