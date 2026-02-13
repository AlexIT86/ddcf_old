import os
import re
import json
from datetime import datetime
from typing import Optional, Tuple

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from django.conf import settings
from django.utils import timezone

from certificat.models import GeneratedDocument, SerieExtraData


FILENAME_PATTERNS = [
    # Examples observed in media/generated_docs: document_538699_Cereale_part1.pdf
    re.compile(r"^document_(?P<docid>\d+)_(?P<tipologie>[\w-]+)_(?P<part>part\d+)\.pdf$", re.IGNORECASE),
    # document_542765_Cereale_part1.pdf
    # document_419126_VN001242_Oleaginoase_regenerat_20250506103653.pdf
    re.compile(r"^document_(?P<docid>\d+)_(?P<aviz>[A-Z0-9]+)_(?P<tipologie>[\w-]+)_regenerat_(?P<ts>\d{14})\.pdf$", re.IGNORECASE),
    # document_550322_5TM001128_Cereale_regenerat_20250506052931.pdf
    re.compile(r"^document_(?P<docid>\d+)_(?P<aviz>[A-Z0-9]+)_(?P<tipologie>[\w-]+)_(?P<suffix>\w+)_(?P<ts>\d{14})\.pdf$", re.IGNORECASE),
]

# Acceptable document series pattern like IL162574, VN123456, etc.
# Accept both formats: IL162574 and 5TM002583 (digits+letters+digits)
SERIES_RE = re.compile(r"^(?:[A-Z]{1,4}\d{4,8}|\d{1,3}[A-Z]{1,4}\d{3,8})$")


def parse_filename(filename: str) -> dict:
    name = os.path.basename(filename)
    for pattern in FILENAME_PATTERNS:
        m = pattern.match(name)
        if m:
            data = m.groupdict()
            # Normalize fields to our GeneratedDocument model context
            aviz_token = data.get("aviz")
            docid_token = data.get("docid")
            # If the token that regex named 'aviz' actually looks like a series (e.g. 5TM002590),
            # then use the numeric docid as aviz_number instead to avoid mixing them up on regenerated files.
            if aviz_token and SERIES_RE.match(aviz_token) and docid_token:
                aviz_value = docid_token
            else:
                aviz_value = aviz_token or docid_token

            result = {
                "aviz_number": aviz_value,
                "document_series": None,
                "partner": None,
                "status": "finalizat",
                "regenerated": bool(data.get("ts")),
            }
            if data.get("ts"):
                try:
                    result["regenerated_at"] = datetime.strptime(data["ts"], "%Y%m%d%H%M%S")
                except Exception:
                    pass
            # Try to derive a document_series hint ONLY if it looks like a real series
            # Avoid values like 'part1', 'regenerat', tipologii etc.
            hint = data.get("part") or data.get("suffix")
            if hint and SERIES_RE.match(hint):
                result["document_series"] = hint
            return result
    # Fallback simple pattern: something_like AVIZ in the name
    simple = re.search(r"([A-Z]{2,}\d{3,})", name)
    return {
        "aviz_number": simple.group(1) if simple else os.path.splitext(name)[0],
        "document_series": None,
        "partner": None,
        "status": "finalizat",
        "regenerated": False,
    }


class Command(BaseCommand):
    help = "Restore GeneratedDocument entries from backup PDFs in a directory."

    def add_arguments(self, parser):
        parser.add_argument("--backup-dir", dest="backup_dir", default=None, help="Directory containing backup PDFs (default: <BASE_DIR>/generated_docs_bkp)")
        parser.add_argument("--user", dest="username", default="restored_import", help="Username to assign as generated_by (created if missing)")
        parser.add_argument("--dry-run", action="store_true", help="Don't write to DB or copy files, just print actions")
        parser.add_argument("--limit", type=int, default=None, help="Process at most N files")
        parser.add_argument("--overwrite", action="store_true", help="Overwrite existing GeneratedDocument records for same aviz+series by creating new ones")

    def handle(self, *args, **options):
        backup_dir = options["backup_dir"] or os.path.join(settings.BASE_DIR, "generated_docs_bkp")
        username = options["username"]
        dry_run = options["dry_run"]
        limit = options["limit"]
        overwrite = options["overwrite"]

        if not os.path.isdir(backup_dir):
            raise CommandError(f"Backup directory not found: {backup_dir}")

        User = get_user_model()
        user = None
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            if dry_run:
                self.stdout.write(self.style.WARNING(f"[DRY-RUN] Would create user '{username}'"))
                user = None
            else:
                # Create user with unusable password (safer, no deprecated API)
                user = User.objects.create(username=username)
                user.set_unusable_password()
                user.save(update_fields=["password"]) 
                self.stdout.write(self.style.SUCCESS(f"Created user '{username}'"))
        # Only require an actual user object when not running in dry-run mode
        if not dry_run and user is None:
            user = User.objects.get(username=username)

        files = [f for f in os.listdir(backup_dir) if f.lower().endswith('.pdf')]
        files.sort()
        if limit:
            files = files[:limit]

        processed = 0
        skipped = 0
        # Try to import PyPDF2 for parsing Aviz/Seria from content
        try:
            from PyPDF2 import PdfReader  # type: ignore
            has_pdf_parser = True
        except Exception:
            PdfReader = None  # type: ignore
            has_pdf_parser = False
            self.stdout.write(self.style.WARNING("PyPDF2 not available. Falling back to filename parsing for aviz/seria."))
        # Optional table extractor
        try:
            import pdfplumber  # type: ignore
            has_table_parser = True
        except Exception:
            pdfplumber = None  # type: ignore
            has_table_parser = False

        def extract_from_pdf(path: str) -> dict:
            if not has_pdf_parser or not os.path.exists(path):
                return {}
            try:
                reader = PdfReader(path)
                text_chunks = []
                for page in reader.pages[:3]:
                    try:
                        text = page.extract_text() or ""
                    except Exception:
                        text = ""
                    if text:
                        text_chunks.append(text)
                full_text = "\n".join(text_chunks)
                if not full_text:
                    return {}
                result = {}
                # Serie / LOT patterns (prefer explicit labels and common formats like "Nr. IL162574" sau "Nr. 5TM002583")
                serie_patterns = [
                    r"(?i)\b(?:seria|serie|lot)\s*[:#-]?\s*((?:[A-Z]{1,4}\d{4,8}|\d{1,3}[A-Z]{1,4}\d{3,8}))",
                    # Avoid generic 'Nr.' which matches aviz; rely on explicit labels or separate detection
                    r"(?i)\b((?:[A-Z]{1,4}\d{5,8}|\d{1,3}[A-Z]{1,4}\d{3,8}))\b",
                ]
                for pat in serie_patterns:
                    m = re.search(pat, full_text)
                    if m:
                        result["document_series"] = m.group(1).strip()
                        break
                # Partner/Beneficiar patterns (optional)
                partner_patterns = [
                    r"(?i)Beneficiar\s*[:\-]?\s*([^\n\r]{3,})",
                    r"(?i)(?:Client|Partener)\s*[:\-]?\s*([^\n\r]{3,})",
                ]
                for pat in partner_patterns:
                    m = re.search(pat, full_text)
                    if m:
                        result["partner"] = m.group(1).strip()
                        break
                # Serie-level extra attributes (LOT metadata)
                series_extra = {}
                field_patterns = {
                    "nr_ambalaje": [r"(?i)\bnr\.?\s*ambalaje\s*[:\-]?\s*([^\n\r]+)"],
                    "doc_oficial": [r"(?i)\bdoc\.?\s*oficial\s*[:\-]?\s*([^\n\r]+)"],
                    "etch_oficiale": [r"(?i)\betch\.?\s*oficiale\s*[:\-]?\s*([^\n\r]+)", r"(?i)etichete\s*oficiale\s*[:\-]?\s*([^\n\r]+)"],
                    "puritate": [r"(?i)\bpuritate\s*[:\-]?\s*([^\n\r%]+%?)"],
                    "sem_straine": [r"(?i)\bsem\.?\s*straine\s*[:\-]?\s*([^\n\r%]+%?)"],
                    "germinatie": [r"(?i)\bgerminatie\s*[:\-]?\s*([^\n\r%]+%?)"],
                    "masa_1000b": [r"(?i)\bmasa\s*1000b\s*[:\-]?\s*([^\n\r]+)"],
                    "stare_sanitara": [r"(?i)\bstare\s*sanitara\s*[:\-]?\s*([^\n\r]+)"],
                    "producator": [r"(?i)\bproducator\s*[:\-]?\s*([^\n\r]+)"],
                    "tara_productie": [r"(?i)\btara\s*(?:de\s*)?productie\s*[:\-]?\s*([^\n\r]+)"],
                    "samanta_tratata": [r"(?i)\bsamanta\s*tratata\s*[:\-]?\s*([^\n\r]+)"],
                    "garantie": [r"(?i)\bgarantie\s*[:\-]?\s*([^\n\r]+)"],
                    "umiditate": [r"(?i)\bumiditate\s*[:\-]?\s*([^\n\r%]+%?)"],
                }
                for field, patterns in field_patterns.items():
                    for pat in patterns:
                        m = re.search(pat, full_text)
                        if m:
                            series_extra[field] = m.group(1).strip()
                            break
                if series_extra:
                    result["series_extra"] = series_extra

                # Extract up to 3 positions from tables if possible
                items = []
                if has_table_parser:
                    try:
                        with pdfplumber.open(path) as pdf:
                            for page in pdf.pages[:2]:
                                tables = page.extract_tables() or []
                                for table in tables:
                                    # Normalize rows: strip cells
                                    rows = [[(cell or '').strip() for cell in row] for row in table if any((cell or '').strip() for cell in row)]
                                    if not rows:
                                        continue
                                    # Identify key rows by first column label
                                    idx_specia = idx_soi = idx_qty = None
                                    idx_lot = None
                                    idx_nr_amb = None
                                    idx_doc_of = None
                                    idx_etch = None
                                    idx_pur = None
                                    idx_sem_str = None
                                    idx_germ = None
                                    idx_mmb = None
                                    idx_stare = None
                                    idx_cold = None
                                    idx_prod = None
                                    idx_tara = None
                                    idx_trat = None
                                    idx_gar = None
                                    idx_umid = None
                                    for idx, row in enumerate(rows):
                                        first = (row[0] if row else '').lower()
                                        if idx_specia is None and 'specia' in first:
                                            idx_specia = idx
                                        if idx_soi is None and ('soiul' in first or 'hibridul' in first or 'articol' in first):
                                            idx_soi = idx
                                        if idx_qty is None and 'cantitatea' in first:
                                            idx_qty = idx
                                        if idx_lot is None and ('referință al lotului' in first or 'referinta al lotului' in first or 'lotului' in first):
                                            idx_lot = idx
                                        if idx_nr_amb is None and ('ambalaje' in first):
                                            idx_nr_amb = idx
                                        if idx_doc_of is None and ('document oficial' in first and 'emitent' in ' '.join(rows[idx]).lower()):
                                            idx_doc_of = idx
                                        if idx_etch is None and ('etichete' in first or 'etichet' in first):
                                            idx_etch = idx
                                        if idx_pur is None and ('puritate fizică' in ' '.join(rows[idx]).lower() or ('puritate' in first and 'fiz' in ' '.join(rows[idx]).lower())):
                                            idx_pur = idx
                                        if idx_sem_str is None and ('semințe străine' in ' '.join(rows[idx]).lower() or 'sem' in first and 'straine' in ' '.join(rows[idx]).lower()):
                                            idx_sem_str = idx
                                        if idx_germ is None and ('germina' in first):
                                            idx_germ = idx
                                        if idx_mmb is None and ('masa a 1000' in ' '.join(rows[idx]).lower() or 'masa 1000' in first):
                                            idx_mmb = idx
                                        if idx_stare is None and ('stare sanitar' in ' '.join(rows[idx]).lower()):
                                            idx_stare = idx
                                        if idx_cold is None and ('cold test' in ' '.join(rows[idx]).lower()):
                                            idx_cold = idx
                                        if idx_prod is None and ('producator' in first or 'producător' in first):
                                            idx_prod = idx
                                        if idx_tara is None and ('tara de productie' in ' '.join(rows[idx]).lower() or 'țara de productie' in ' '.join(rows[idx]).lower()):
                                            idx_tara = idx
                                        if idx_trat is None and ('sămânța tratată' in ' '.join(rows[idx]).lower() or 'samanta tratata' in ' '.join(rows[idx]).lower()):
                                            idx_trat = idx
                                        if idx_gar is None and ('garantie' in ' '.join(rows[idx]).lower() or 'valabilitate' in ' '.join(rows[idx]).lower()):
                                            idx_gar = idx
                                        if idx_umid is None and ('umiditate' in first or '%(h)' in ' '.join(rows[idx]).lower()):
                                            idx_umid = idx
                                    # Need at least specia row to proceed
                                    if idx_specia is None:
                                        continue
                                    # Determine number of positions (columns beyond first)
                                    num_cols = 0
                                    for idx in [idx_specia, idx_soi, idx_qty]:
                                        if idx is not None and len(rows[idx]) - 1 > num_cols:
                                            num_cols = len(rows[idx]) - 1
                                    if num_cols <= 0:
                                        continue

                                    def parse_qty(text: str):
                                        text = (text or '').strip()
                                        m = re.search(r"([0-9]+[\d\.,]*)\s*([A-Za-z%]+)?", text)
                                        if not m:
                                            return None, None
                                        val = m.group(1).replace(',', '.').strip()
                                        try:
                                            val_num = float(val)
                                        except Exception:
                                            val_num = None
                                        unit = (m.group(2) or '').strip() or None
                                        return val_num, unit

                                    # collect series and extras per column
                                    col_series_list = []
                                    series_extras_by_serie = {}
                                    for col in range(1, min(3, num_cols) + 1):
                                        spec = rows[idx_specia][col] if col < len(rows[idx_specia]) else ''
                                        soi = None
                                        if idx_soi is not None and col < len(rows[idx_soi]):
                                            soi = rows[idx_soi][col]
                                        cantitate = None
                                        um = None
                                        if idx_qty is not None and col < len(rows[idx_qty]):
                                            cantitate, um = parse_qty(rows[idx_qty][col])
                                        item = {}
                                        if spec:
                                            item['specia'] = spec
                                        if soi:
                                            item['soi'] = soi
                                        if cantitate is not None:
                                            item['cantitate'] = cantitate
                                        if um:
                                            item['um'] = um
                                        # Map series and its extra fields according to provided mapping
                                        serie_val = None
                                        if idx_lot is not None and col < len(rows[idx_lot]):
                                            serie_val = rows[idx_lot][col].strip()
                                            if serie_val:
                                                col_series_list.append(serie_val)
                                        extra = {}
                                        def set_extra(idx_row, key):
                                            if idx_row is not None and col < len(rows[idx_row]):
                                                val = rows[idx_row][col].strip()
                                                if val:
                                                    extra[key] = val
                                        set_extra(idx_nr_amb, 'nr_ambalaje')
                                        set_extra(idx_doc_of, 'doc_oficial')
                                        set_extra(idx_etch, 'etch_oficiale')
                                        set_extra(idx_pur, 'puritate')
                                        set_extra(idx_sem_str, 'sem_straine')
                                        set_extra(idx_germ, 'germinatie')
                                        set_extra(idx_mmb, 'masa_1000b')
                                        set_extra(idx_stare, 'stare_sanitara')
                                        set_extra(idx_cold, 'cold')
                                        set_extra(idx_prod, 'producator')
                                        set_extra(idx_tara, 'tara_productie')
                                        set_extra(idx_trat, 'samanta_tratata')
                                        set_extra(idx_gar, 'garantie')
                                        set_extra(idx_umid, 'umiditate')

                                        if serie_val and extra:
                                            series_extras_by_serie[serie_val] = extra

                                        if item:
                                            items.append(item)
                                    if items:
                                        # attach series info to result
                                        if col_series_list:
                                            result['series_list'] = col_series_list
                                        if series_extras_by_serie:
                                            result['series_extras_by_serie'] = series_extras_by_serie
                                        break
                                if items:
                                    break
                    except Exception:
                        pass
                # Fallback: simple label-based extraction for pozitie1
                if not items:
                    specia = None
                    soi = None
                    m = re.search(r"(?is)\bSpecia\b[:\-]?\s*([^\n\r]+)", full_text)
                    if m:
                        specia = m.group(1).strip()
                    m = re.search(r"(?is)Soiul\s*\(hibridul\)\s*[:\-]?\s*([^\n\r]+)", full_text)
                    if m:
                        soi = m.group(1).strip()
                    if specia or soi:
                        items.append({"specia": specia, "soi": soi})
                if items:
                    result["items"] = items
                # Document date patterns (e.g., "data 05.05.2025")
                date_patterns = [
                    r"(?i)\bdata\s+([0-3]?\d[./-][01]?\d[./-]\d{4})",
                ]
                for pat in date_patterns:
                    m = re.search(pat, full_text)
                    if m:
                        date_str = m.group(1).strip()
                        # Normalize separators and parse
                        norm = re.sub(r"[/-]", ".", date_str)
                        try:
                            dt = datetime.strptime(norm, "%d.%m.%Y")
                            # Make timezone-aware using project TZ
                            if settings.USE_TZ:
                                dt = timezone.make_aware(dt, timezone.get_current_timezone())
                            result["doc_date"] = dt
                        except Exception:
                            pass
                        break
                return result
            except Exception:
                return {}
        for fname in files:
            src_path = os.path.join(backup_dir, fname)
            meta = parse_filename(fname)
            # Merge with parsed PDF metadata if available
            pdf_meta = extract_from_pdf(src_path)
            # IMPORTANT: Keep aviz from filename; UI 'Serie Document' trebuie să rămână seria din PDF (header),
            # NU numărul de referință al lotului. Deci setăm doar dacă am detectat 'document_series',
            # ignorăm 'series_list' (care reprezintă LOT-urile din tabel).
            if pdf_meta.get("document_series"):
                meta["document_series"] = pdf_meta["document_series"]
            if pdf_meta.get("partner") and not meta.get("partner"):
                meta["partner"] = pdf_meta["partner"]

            aviz_number = meta.get("aviz_number")
            document_series = meta.get("document_series")

            # Decide if we should skip when an identical record exists
            exists_qs = GeneratedDocument.objects.filter(aviz_number=aviz_number)
            if document_series:
                exists_qs = exists_qs.filter(document_series=document_series)
            if exists_qs.exists() and not overwrite:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"Skip existing: {fname} -> aviz={aviz_number}, series={document_series}"))
                continue

            # Destination path in MEDIA (normalize regenerated suffix to avoid duplicates)
            # If filename contains '_regenerat_YYYYMMDDHHMMSS', keep it; otherwise just copy the base name.
            dest_rel = os.path.join("generated_docs", fname)
            if default_storage.exists(dest_rel) and not overwrite:
                self.stdout.write(self.style.WARNING(f"File exists in media, skipping copy: {dest_rel}"))
            else:
                if dry_run:
                    self.stdout.write(f"[DRY-RUN] Would copy to media: {dest_rel}")
                else:
                    with open(src_path, 'rb') as fsrc:
                        default_storage.save(dest_rel, ContentFile(fsrc.read()))

            if dry_run:
                self.stdout.write(f"[DRY-RUN] Would create GeneratedDocument(aviz={aviz_number}, series={document_series}, file={dest_rel})")
                processed += 1
                continue

            with transaction.atomic():
                # Prepare context_json if we parsed any item information
                context_dict = None
                if pdf_meta.get("items"):
                    # Map up to 3 items into pozitie1..3
                    context_dict = {}
                    for idx, item in enumerate(pdf_meta["items"][:3], start=1):
                        context_dict[f"pozitie{idx}"] = item

                doc = GeneratedDocument(
                    aviz_number=aviz_number,
                    pdf_file=dest_rel,
                    generated_by=user,
                    context_json=json.dumps(context_dict) if context_dict else None,
                    partner=meta.get("partner"),
                    document_series=document_series,
                    regenerated=meta.get("regenerated", False),
                    status=meta.get("status", "finalizat"),
                )
                if meta.get("regenerated_at"):
                    doc.regenerated_at = meta["regenerated_at"]
                doc.save()
                # If we have a document date parsed from PDF, override created_at to reflect it
                if pdf_meta.get("doc_date"):
                    GeneratedDocument.objects.filter(id=doc.id).update(created_at=pdf_meta["doc_date"])  # type: ignore
                # Upsert SerieExtraData conform mapării (din tabel)
                # 1) dacă avem series_extras_by_serie (per col), le scriem pe toate
                if pdf_meta.get("series_extras_by_serie"):
                    for serie_key, defaults in pdf_meta["series_extras_by_serie"].items():
                        try:
                            SerieExtraData.objects.update_or_create(serie=serie_key, defaults=defaults)
                        except Exception:
                            continue
                # 2) altfel, dacă avem un unic document_series + series_extra simplu, scriem acela
                elif document_series and pdf_meta.get("series_extra"):
                    SerieExtraData.objects.update_or_create(serie=document_series, defaults=pdf_meta["series_extra"]) 
                # 3) dacă avem doar lista LOT-urilor fără extra, creăm intrările minime
                elif pdf_meta.get("series_list"):
                    for serie_key in pdf_meta["series_list"]:
                        try:
                            SerieExtraData.objects.get_or_create(serie=serie_key)
                        except Exception:
                            continue
                processed += 1
                self.stdout.write(self.style.SUCCESS(f"Restored: {fname} -> id={doc.id}, aviz={aviz_number}, series={document_series}"))

        self.stdout.write(self.style.SUCCESS(f"Done. processed={processed}, skipped={skipped}, dir={backup_dir}"))


