import os
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
import unicodedata

from django.core.management.base import BaseCommand
from django.conf import settings

from certificat.models import GeneratedDocument, SpecieMapping, TipologieProdus, Gestiune, DocumentRange


SERIES_RE = re.compile(r"^(?:[A-Z]{1,4}\d{4,8}|\d{1,3}[A-Z]{1,4}\d{3,8})$")


def _normalize_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    # Lowercase and remove diacritics for robust comparisons
    nfkd = unicodedata.normalize('NFKD', value)
    ascii_only = ''.join([c for c in nfkd if not unicodedata.combining(c)])
    return ascii_only.lower().strip()


def extract_series_and_specia_from_pdf(path: str) -> Tuple[Optional[str], List[str]]:
    try:
        from PyPDF2 import PdfReader  # type: ignore
    except Exception:
        return None
    try:
        reader = PdfReader(path)
        text = []
        for page in reader.pages[:2]:
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            if t:
                text.append(t)
        full = "\n".join(text)
        if not full:
            return None, []
        # Prefer explicit labels
        for pat in [
            r"(?i)\b(?:seria|serie|lot)\s*[:#-]?\s*((?:[A-Z]{1,4}\d{4,8}|\d{1,3}[A-Z]{1,4}\d{3,8}))",
            r"(?i)\b((?:[A-Z]{1,4}\d{5,8}|\d{1,3}[A-Z]{1,4}\d{3,8}))\b",
        ]:
            m = re.search(pat, full)
            if m:
                serie_val = m.group(1).strip()
                break
        else:
            serie_val = None

        # Try to infer species list with pdfplumber tables for accuracy
        species: List[str] = []
        try:
            import pdfplumber  # type: ignore
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages[:2]:
                    tables = page.extract_tables() or []
                    for table in tables:
                        rows = [[(cell or '').strip() for cell in row] for row in table if any((cell or '').strip() for cell in row)]
                        if not rows:
                            continue
                        for row in rows:
                            if row and _normalize_text(row[0] if row[0] else '').startswith('specia'):
                                # collect values from columns 2..n
                                for cell in row[1:]:
                                    val = (cell or '').strip()
                                    if val:
                                        species.append(val)
                                break
                        if species:
                            break
                if not species:
                    # fallback to text-based single capture
                    m = re.search(r"(?is)\bSpecia\b[:\-]?\s*([^\n\r]+)", full)
                    if m:
                        species = [m.group(1).strip()]
        except Exception:
            # Fallback to text if pdfplumber unavailable
            m = re.search(r"(?is)\bSpecia\b[:\-]?\s*([^\n\r]+)", full)
            if m:
                species = [m.group(1).strip()]
        return serie_val, species
    except Exception:
        return None


def split_series(series: str) -> Optional[Tuple[str, int, int]]:
    m = re.search(r"^(.*?)(\d+)$", series)
    if not m:
        return None
    prefix, digits = m.group(1), m.group(2)
    try:
        return prefix, int(digits), len(digits)
    except ValueError:
        return None


SERIES_PREFIX_TO_GESTIUNE = {
    'VN': 'DEPOZIT TISITA, VRANCEA',
    'AB': 'Depozit ALBA-IULIA, ALBA',
    'OT': 'Depozit CARACAL, OLT',
    '5TM': 'Depozit GHIRODA, TIMIS',
    'IL': 'Depozit SLOBOZIA, IALOMITA',
}


class Command(BaseCommand):
    help = (
        "Scan backup PDFs and compute last-used document series per gestiune based on the series found in the PDF text. "
        "Outputs next available number as well."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dirs",
            nargs="*",
            default=None,
            help="Directories to scan for PDFs. Defaults to [<BASE_DIR>/generated_docs_bkp, MEDIA/generated_docs]",
        )
        parser.add_argument("--limit", type=int, default=None, help="Limit number of PDFs processed (for testing)")
        parser.add_argument("--apply", action="store_true", help="Create/Update DocumentRange for the computed groups")

    def handle(self, *args, **options):
        base = str(settings.BASE_DIR)
        default_dirs = [os.path.join(base, "generated_docs_bkp"), os.path.join(settings.MEDIA_ROOT, "generated_docs")]
        scan_dirs: List[str] = options["dirs"] or default_dirs
        limit = options["limit"]

        # Map: (gestiune_id or None, tipologie_id or None, prefix, width) -> (max_value, sample_series, sample_aviz)
        aggreg: Dict[Tuple[Optional[int], Optional[int], str, int], Tuple[int, str, Optional[str]]] = {}

        def resolve_gestiune_by_prefix(series: str) -> Optional[int]:
            split = split_series(series)
            if not split:
                return None
            prefix, _, _ = split
            # Longest matching key first
            cand = None
            for pref in sorted(SERIES_PREFIX_TO_GESTIUNE.keys(), key=len, reverse=True):
                if prefix.startswith(pref):
                    cand = SERIES_PREFIX_TO_GESTIUNE[pref]
                    break
            if not cand:
                return None
            try:
                gest = Gestiune.objects.filter(nume=cand).first()
                return gest.id if gest else None
            except Exception:
                return None

        def resolve_tipologie(species: List[str], gest_id: Optional[int]) -> Optional[int]:
            if not species:
                return None
            try:
                # Reguli speciale: Ghiroda (5TM), Slobozia (IL), Alba Iulia (AB) doar 'General'
                if gest_id:
                    gest = Gestiune.objects.filter(id=gest_id).first()
                    if gest and gest.nume in (
                        SERIES_PREFIX_TO_GESTIUNE['5TM'],
                        SERIES_PREFIX_TO_GESTIUNE['IL'],
                        SERIES_PREFIX_TO_GESTIUNE['AB'],
                    ):
                        tip = TipologieProdus.objects.filter(nume__iexact='General').first()
                        return tip.id if tip else None
                # Normalize and try to resolve each species; return a single tipologie if all agree
                tip_ids = set()
                for spec in species:
                    spec_norm = _normalize_text(spec) or ''
                    # Try exact-insensitive
                    m = SpecieMapping.objects.filter(specie__iexact=spec.strip()).select_related('tipologie').first()
                    if not m:
                        # Try icontains on normalized
                        all_maps = SpecieMapping.objects.select_related('tipologie').all()
                        chosen = None
                        for mm in all_maps:
                            if _normalize_text(mm.specie) == spec_norm or (_normalize_text(mm.specie) in spec_norm):
                                chosen = mm
                                break
                        m = chosen
                    if m:
                        tip_ids.add(m.tipologie_id)
                if len(tip_ids) == 1:
                    return tip_ids.pop()
                return None
            except Exception:
                return None

        def update_agg(gest_id: Optional[int], tipologie_id: Optional[int], series: str, aviz: Optional[str]):
            split = split_series(series)
            if not split:
                return
            prefix, value, width = split
            key = (gest_id, tipologie_id, prefix, width)
            cur = aggreg.get(key)
            if cur is None or value > cur[0]:
                aggreg[key] = (value, series, aviz)

        processed = 0
        for directory in scan_dirs:
            if not os.path.isdir(directory):
                continue
            for name in sorted(os.listdir(directory)):
                if limit and processed >= limit:
                    break
                if not name.lower().endswith(".pdf"):
                    continue
                path = os.path.join(directory, name)
                series, species = extract_series_and_specia_from_pdf(path)
                if not series:
                    continue

                # Try to map to a gestiune using existing DB entries (and capture aviz)
                gest_id: Optional[int] = None
                aviz_number: Optional[str] = None
                try:
                    # Match by filename if present in media
                    gd = (
                        GeneratedDocument.objects.filter(pdf_file__endswith=name)
                        .select_related("generated_by__userprofile__gestiune")
                        .first()
                    )
                    if gd and getattr(getattr(gd.generated_by, "userprofile", None), "gestiune", None):
                        gest_id = gd.generated_by.userprofile.gestiune_id
                    if gd:
                        aviz_number = gd.aviz_number
                except Exception:
                    pass

                # If still not known, infer from prefix mapping
                if gest_id is None:
                    gest_id = resolve_gestiune_by_prefix(series)

                tipologie_id: Optional[int] = resolve_tipologie(species, gest_id)

                # Fallback: derive aviz from filename if not found in DB
                if not aviz_number:
                    m = re.match(r"document_(\d+)_([A-Za-z0-9]+)_", name)
                    if m:
                        docid = m.group(1)
                        token = m.group(2)
                        # If token looks like a series, use docid as aviz (consistent cu logica restore)
                        aviz_number = docid if SERIES_RE.match(token or '') else token

                update_agg(gest_id, tipologie_id, series, aviz_number)
                processed += 1

        if not aggreg:
            self.stdout.write(self.style.WARNING("No series found in provided directories."))
            return

        # Print report
        lines = []
        sorted_groups = sorted(aggreg.items(), key=lambda x: ((x[0][0] or 0), (x[0][1] or 0), x[0][2], x[1][0]))
        for (gest_id, tip_id, prefix, width), (max_val, sample_series, sample_aviz) in sorted_groups:
            next_val = max_val + 1
            next_series = f"{prefix}{str(next_val).zfill(width)}"
            gest_name = "(necunoscut)"
            if gest_id:
                try:
                    gest_name = Gestiune.objects.get(id=gest_id).nume
                except Exception:
                    gest_name = f"id={gest_id}"
            tip_name = "(n/a)"
            if tip_id:
                try:
                    tip_name = TipologieProdus.objects.get(id=tip_id).nume
                except Exception:
                    tip_name = f"id={tip_id}"
            base_line = f"Gestiune={gest_name} | Tipologie={tip_name} | prefix='{prefix}' width={width} -> last='{prefix}{str(max_val).zfill(width)}' next='{next_series}'"
            # For Tipologie n/a, append aviz sample if available
            if tip_id is None and sample_aviz:
                base_line += f" | aviz='{sample_aviz}'"
            lines.append(base_line)

        for line in lines:
            self.stdout.write(line)

        # Apply mode: create/update DocumentRange entries
        if options.get("apply"):
            created = 0
            updated = 0
            for (gest_id, tip_id, prefix, width), (max_val, sample_series, sample_aviz) in sorted_groups:
                # Resolve gestiune
                if not gest_id:
                    continue  # Skip unknown
                gest = Gestiune.objects.filter(id=gest_id).first()
                if not gest:
                    continue
                # Resolve tipologie (fallback to General)
                tip = TipologieProdus.objects.filter(id=tip_id).first() if tip_id else None
                if not tip:
                    tip = TipologieProdus.objects.filter(nume__iexact='General').first()
                    if not tip:
                        tip = TipologieProdus.objects.create(nume='General')
                last_series = f"{prefix}{str(max_val).zfill(width)}"
                start_series = f"{prefix}{str(1).zfill(width)}"  # e.g. VN000001
                # Use all 9's with proper width, not zfill of single '9'
                final_series = f"{prefix}{('9'*width)}"  # e.g. VN999999
                dr = DocumentRange.objects.filter(gestiune=gest, tipologie=tip).first()
                if dr:
                    changes = []
                    if dr.numar_inceput != start_series:
                        dr.numar_inceput = start_series; changes.append('start')
                    if dr.numar_final != final_series:
                        dr.numar_final = final_series; changes.append('final')
                    if dr.numar_curent != last_series:
                        dr.numar_curent = last_series; changes.append('curent')
                    if changes:
                        dr.save(update_fields=['numar_inceput','numar_final','numar_curent'])
                        updated += 1
                else:
                    DocumentRange.objects.create(
                        gestiune=gest,
                        tipologie=tip,
                        numar_inceput=start_series,
                        numar_final=final_series,
                        numar_curent=last_series,
                    )
                    created += 1
            self.stdout.write(self.style.SUCCESS(f"Applied: created={created}, updated={updated}"))

        self.stdout.write(self.style.SUCCESS(f"Done. scanned={processed}, groups={len(aggreg)}"))


