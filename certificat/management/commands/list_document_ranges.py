import re
from django.core.management.base import BaseCommand

from certificat.models import DocumentRange


def split_prefix_and_number(identifier: str):
    if not identifier:
        return None
    m = re.search(r"^(.*?)(\d+)$", identifier.strip())
    if not m:
        return None
    prefix, digits = m.group(1), m.group(2)
    return prefix, len(digits)


class Command(BaseCommand):
    help = "List all DocumentRange entries with parsed prefix/width to help auditing old ranges."

    def add_arguments(self, parser):
        parser.add_argument("--gestiune", default=None, help="Filter by gestiune name contains")
        parser.add_argument("--tipologie", default=None, help="Filter by tipologie name contains")

    def handle(self, *args, **options):
        gest_filter = options.get("gestiune")
        tip_filter = options.get("tipologie")
        qs = DocumentRange.objects.select_related("gestiune", "tipologie").all()
        if gest_filter:
            qs = qs.filter(gestiune__nume__icontains=gest_filter)
        if tip_filter:
            qs = qs.filter(tipologie__nume__icontains=tip_filter)

        if not qs.exists():
            self.stdout.write("No DocumentRange rows.")
            return

        for dr in qs.order_by("gestiune__nume", "tipologie__nume", "id"):
            gest = dr.gestiune.nume if dr.gestiune else "(n/a)"
            tip = dr.tipologie.nume if dr.tipologie else "(n/a)"
            sample = dr.numar_inceput or dr.numar_curent or dr.numar_final or ""
            parsed = split_prefix_and_number(sample)
            prefix, width = parsed if parsed else ("?", 0)
            self.stdout.write(
                f"id={dr.id} | gestiune='{gest}' | tipologie='{tip}' | start='{dr.numar_inceput}' | curent='{dr.numar_curent}' | final='{dr.numar_final}' | prefix='{prefix}' width={width}"
            )


