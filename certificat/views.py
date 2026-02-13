import os
import json
import re
import tempfile
import traceback
import random
import platform  # Import pentru detectarea OS-ului
import subprocess # Import pentru verificarea LibreOffice
from io import BytesIO
from collections import defaultdict
from datetime import datetime, timedelta
import requests
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.http import HttpResponse, JsonResponse, Http404
from django.contrib.auth.models import User
from django.contrib.auth import logout, login # Adaugă login dacă folosești autentificare
from django.shortcuts import render, get_object_or_404, redirect
from django.db.models import Count, Sum, F, Q
from django.db.models.functions import TruncMonth, TruncWeek
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.conf import settings
from django.contrib import messages
from django.utils import timezone
from django.forms import modelformset_factory
from django.forms.models import model_to_dict
from django.core.files.base import ContentFile
from urllib.parse import urlencode # Pentru bulk_delete_serie_data redirect
# Docx template library
from docxtpl import DocxTemplate
# Importurile pentru modele
from .models import (
    UserProfile, DocumentRange, Role, ActivityLog, UserManual,
    GeneratedDocument, SerieExtraData, SpecieMapping, Gestiune, TipologieProdus # Ensure all models are here
)
# Importurile pentru formulare (dacă sunt folosite în view-uri)
from .forms import (
    UserForm, RoleForm, GestiuneForm, TipologieProdusForm, DocumentRangeForm,
    UserProfileForm,  SpecieMappingForm, SpecieMappingManualForm, UserManualForm,
    SerieExtraDataForm # Ensure SerieExtraDataForm is imported
    )
# Import pentru funcții utilitare
from .utils import StandardMessages, log_activity


# --- Configurare Conversie PDF Condiționată ---
PDF_CONVERSION_ENABLED = True # Presupunem că e activat inițial
COMError = Exception # Definim un fallback generic

if platform.system() == "Windows":
    try:
        import pywintypes
        import pythoncom
        from docx2pdf import convert # Folosim docx2pdf și pe Windows
        COMError = pywintypes.com_error
        print("INFO: Detectat Windows. Se va încerca folosirea MS Word (via COM) pentru conversie PDF.")
        # Aici ai putea adăuga o verificare mai complexă dacă Word e instalat,
        # dar de obicei docx2pdf face o treabă decentă.
    except ImportError:
        print("AVERTISMENT: pywin32 nu este instalat. Conversia PDF pe Windows via MS Word NU va funcționa.")
        PDF_CONVERSION_ENABLED = False
        # Definim un placeholder pentru convert dacă nu e importat
        def convert(input_path, output_path):
            raise RuntimeError("docx2pdf (mod Windows/COM) nu este disponibil (pywin32 lipsă).")
elif platform.system() == "Linux":
    try:
        # Pe Linux, docx2pdf folosește LibreOffice. Doar importăm funcția.
        from docx2pdf import convert

        # Verificăm dacă LibreOffice pare a fi instalat și accesibil
        try:
            # Verificăm mai multe căi posibile pentru soffice
            possible_commands = ['soffice', 'libreoffice', '/usr/bin/soffice', '/usr/bin/libreoffice']
            soffice_command = None

            for cmd in possible_commands:
                try:
                    result = subprocess.run(
                        [cmd, '--version'],
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=10
                    )
                    soffice_command = cmd
                    print(
                        f"INFO: Detectat Linux și LibreOffice ({cmd}). Output version check: {result.stdout.decode()}")
                    break
                except (FileNotFoundError, subprocess.SubprocessError):
                    continue

            if soffice_command is None:
                print("AVERTISMENT: Comanda LibreOffice nu a fost găsită în PATH. Conversia PDF pe Linux va eșua.")
                PDF_CONVERSION_ENABLED = False


                def convert(input_path, output_path):
                    raise RuntimeError("LibreOffice nu este disponibil pentru conversia PDF")
            else:
                # Definim funcția noastră convert care folosește explicit LibreOffice
                def convert(input_path, output_path):
                    # Asigură-te că directorul de ieșire există
                    output_dir = os.path.dirname(output_path)
                    if not os.path.exists(output_dir):
                        os.makedirs(output_dir)

                    cmd = [
                        soffice_command,
                        '--headless',
                        '--convert-to', 'pdf',
                        '--outdir', output_dir,
                        input_path
                    ]
                    result = subprocess.run(cmd, check=True, timeout=60)

                    # LibreOffice generează fișierul cu același nume dar extensie .pdf
                    # Trebuie să redenumim fișierul dacă e necesar
                    generated_pdf = os.path.splitext(os.path.basename(input_path))[0] + '.pdf'
                    generated_pdf_path = os.path.join(output_dir, generated_pdf)

                    if generated_pdf_path != output_path and os.path.exists(generated_pdf_path):
                        os.rename(generated_pdf_path, output_path)
        except Exception as e:
            print(f"AVERTISMENT: Eroare la configurarea LibreOffice: {e}. Conversia PDF pe Linux va eșua.")
            PDF_CONVERSION_ENABLED = False


            def convert(input_path, output_path):
                raise RuntimeError(f"Eroare configurare LibreOffice: {e}")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"AVERTISMENT: Eroare la verificarea 'soffice --version': {e}. Conversia PDF pe Linux ar putea eșua.")
            # Nu setăm PDF_CONVERSION_ENABLED pe False aici, lăsăm docx2pdf să încerce
    except ImportError:
        print("AVERTISMENT: Biblioteca docx2pdf nu este instalată. Conversia PDF va eșua.")
        PDF_CONVERSION_ENABLED = False
        def convert(input_path, output_path):
            raise RuntimeError("docx2pdf nu este instalat.")
else:
    # Alte sisteme de operare (macOS etc.) - docx2pdf ar putea funcționa cu LibreOffice/MS Word
     print(f"INFO: Detectat OS: {platform.system()}. Se va încerca folosirea docx2pdf (backend necunoscut a priori).")
     try:
        from docx2pdf import convert
        # Poți adăuga verificări specifice aici dacă știi că rulezi și pe macOS
     except ImportError:
        print(f"AVERTISMENT: docx2pdf nu este instalat. Conversia PDF pe {platform.system()} va eșua.")
        PDF_CONVERSION_ENABLED = False
        def convert(input_path, output_path):
             raise RuntimeError("docx2pdf nu este instalat.")

# --- Restul Codului (View-uri etc.) ---

FAMOUS_QUOTES = [
    {"text": "Singura modalitate de a face lucruri minunate este să iubești ceea ce faci.", "author": "Steve Jobs"},
    # ... (restul citatelor) ...
]


@login_required(login_url='/login/')
def serie_extra_data_details_ajax(request, pk):
    """
    View AJAX pentru a prelua și actualiza detaliile unui SerieExtraData.
    Doar Superadmin.
    """
    user_profile = getattr(request.user, 'userprofile', None)
    if not (user_profile and user_profile.role and user_profile.role.name.lower() == 'superadmin'):
        return JsonResponse({'status': 'error', 'message': 'Acces nepermis.'}, status=403)

    try:
        serie_instance = get_object_or_404(SerieExtraData, pk=pk)
    except (Http404, ValueError):
        return JsonResponse({'status': 'error', 'message': 'Înregistrarea nu a fost găsită.'}, status=404)

    if request.method == 'POST':
        form = SerieExtraDataForm(request.POST, instance=serie_instance)
        if form.is_valid():
            try:
                updated_instance = form.save()
                log_activity(request.user, "SERIE_DATA_EDIT_AJAX",
                             f"Datele extra pentru seria '{updated_instance.serie}' (PK: {pk}) au fost actualizate via AJAX.")
                # Returnăm datele actualizate pentru a putea reîmprospăta UI-ul dacă e necesar
                return JsonResponse({
                    'status': 'success',
                    'message': 'Datele au fost actualizate cu succes!',
                    'serie_data': model_to_dict(updated_instance)  # Trimitem înapoi datele actualizate
                })
            except Exception as e:
                log_activity(request.user, "SERIE_DATA_EDIT_AJAX_FAIL",
                             f"Eroare AJAX la actualizarea seriei PK {pk}. Eroare: {e}")
                return JsonResponse({'status': 'error', 'message': f'Eroare la salvare: {str(e)}'}, status=500)
        else:
            # Colectează erorile formularului pentru a le trimite înapoi
            errors_dict = {field: [error for error in errors] for field, errors in form.errors.items()}
            return JsonResponse({'status': 'error', 'message': 'Date invalide.', 'errors': errors_dict}, status=400)
    else:  # GET request
        # Pregătim datele pentru a fi trimise ca JSON, inclusiv pentru a popula formularul
        # Sau, mai bine, trimitem direct HTML-ul formularului pre-populat?
        # Pentru simplitate inițială, trimitem datele ca JSON. Clientul va popula formularul.
        # Alternativ, putem randa un fragment de template cu formularul.

        # Opțiunea 1: Trimitem datele ca JSON
        data_for_form = model_to_dict(serie_instance)
        # Poți adăuga și alte informații dacă e necesar, de ex., URL-ul pentru POST
        data_for_form['post_url'] = reverse('serie_extra_data_details_ajax', kwargs={'pk': pk})

        return JsonResponse({
            'status': 'success',
            'serie_data': data_for_form
        })

"""Helper function to get the next document number across all ranges for a gestiune+tipologie.
Selectează prima plajă disponibilă (ne-epuizată) în ordinea creării și returnează următorul număr.
Dacă preview_only=False, alocă și salvează numărul pe plaja respectivă.
"""
def get_next_document_number(gestiune, tipologie_obj, preview_only=False):  # Adăugat preview_only
    pattern = re.compile(r'^(.*?)(\d+)$')

    def compute_candidate_for_range(r):
        if r.numar_curent:
            m = pattern.match(r.numar_curent)
            if not m:
                return None, None, ""
            prefix, num_str = m.groups()
            num_len = len(num_str)
            try:
                next_int = int(num_str) + 1
            except ValueError:
                return None, None, ""
        else:
            m = pattern.match(r.numar_inceput)
            if not m:
                return None, None, ""
            prefix, num_str = m.groups()
            num_len = len(num_str)
            try:
                next_int = int(num_str)
            except ValueError:
                return None, None, ""

        m_final = pattern.match(r.numar_final)
        if not m_final:
            return None, None, ""
        prefix_final, final_num_str = m_final.groups()

        if prefix != prefix_final or num_len == 0:
            return None, None, "Format incompatibil"

        try:
            final_int = int(final_num_str)
        except ValueError:
            return None, None, ""

        if next_int > final_int:
            return None, None, "Range epuizat"

        candidate = prefix + str(next_int).zfill(num_len)
        return candidate, (prefix, num_len, next_int, final_int), None

    # 1) Încearcă pe tipologia specifică
    ranges_qs = DocumentRange.objects.filter(gestiune=gestiune, tipologie=tipologie_obj).order_by('id')
    # 2) Fallback pe "General" dacă nu există nicio plajă pe tipologia dată
    if not ranges_qs.exists():
        fallback_tip = TipologieProdus.objects.filter(nume__iexact="General").first()
        if fallback_tip:
            ranges_qs = DocumentRange.objects.filter(gestiune=gestiune, tipologie=fallback_tip).order_by('id')
    if not ranges_qs.exists():
        return ""

    last_error_message = None
    for r in ranges_qs:
        candidate, details, error = compute_candidate_for_range(r)
        if error:
            # Ținem minte ultimul mesaj de eroare pentru context, dar continuăm spre următoarea plajă
            last_error_message = error
            continue

        if candidate:
            if preview_only:
                return candidate
            # Alocare efectivă: setăm numar_curent pe plaja selectată
            r.numar_curent = candidate
            r.save()
            return candidate

    # Dacă am parcurs toate plajele și nu am găsit candidat, returnăm ultimul mesaj util
    return last_error_message or ""


# Helper specific: calculează următorul număr pentru O PLAJĂ anume (fără a considera alte plaje)
def get_next_document_number_for_range(doc_range):
    pattern = re.compile(r'^(.*?)(\d+)$')

    if doc_range.numar_curent:
        m = pattern.match(doc_range.numar_curent)
        if not m:
            return ""
        prefix, num_str = m.groups()
        num_len = len(num_str)
        try:
            next_int = int(num_str) + 1
        except ValueError:
            return ""
    else:
        m = pattern.match(doc_range.numar_inceput)
        if not m:
            return ""
        prefix, num_str = m.groups()
        num_len = len(num_str)
        try:
            next_int = int(num_str)
        except ValueError:
            return ""

    m_final = pattern.match(doc_range.numar_final)
    if not m_final:
        return ""
    prefix_final, final_num_str = m_final.groups()

    if prefix != prefix_final or num_len == 0:
        return "Format incompatibil"

    try:
        final_int = int(final_num_str)
    except ValueError:
        return ""

    if next_int > final_int:
        return "Range epuizat"

    return prefix + str(next_int).zfill(num_len)

# --- View home (rămâne la fel) ---
@login_required(login_url='/login/')
def home(request):
    """View pentru pagina principală cu statistici de business."""
    # ... (codul existent pentru home view) ...
    current_date = timezone.now()
    quotes = [
        {"text": "Drumul către succes este mereu în construcție.", "author": "Lily Tomlin"},
        {"text": "Nu contează cât de încet mergi, atâta timp cât nu te oprești.", "author": "Confucius"},
        {"text": "Succesul constă în a cădea de nouă ori și a te ridica de zece ori.", "author": "Jon Bon Jovi"},
        # ... (restul citatelor)
    ]
    quote = random.choice(quotes)
    total_finalized_documents = GeneratedDocument.objects.filter(status='finalizat').count()
    my_distinct_avize = GeneratedDocument.objects.filter(generated_by=request.user).values('aviz_number').distinct().count()
    recent_date = timezone.now() - timedelta(days=30)
    recent_avize = GeneratedDocument.objects.filter(created_at__gte=recent_date).values('aviz_number').distinct().count()

    # Statistici tipologii recente
    recent_tipologies = []
    try:
        tipologie_counts = defaultdict(int)
        recent_docs_json = GeneratedDocument.objects.filter(
            created_at__gte=recent_date, context_json__isnull=False
        ).values_list('context_json', flat=True)

        for context_json_str in recent_docs_json:
            try:
                context_data = json.loads(context_json_str)
                for i in range(1, 4):
                    pos_key = f"pozitie{i}"
                    if pos_key in context_data and isinstance(context_data[pos_key], dict):
                        tipologie = context_data[pos_key].get('tipologie')
                        if tipologie:
                            tipologie_counts[tipologie] += 1
            except (json.JSONDecodeError, KeyError, TypeError):
                continue # Ignorăm JSON invalid sau structură neașteptată

        recent_tipologies = sorted(
            [{"name": name, "count": count} for name, count in tipologie_counts.items()],
            key=lambda x: x["count"], reverse=True
        )
    except Exception as e:
        print(f"Eroare la calculul statisticilor recente pe tipologii: {e}")
        # Fallback data
        recent_tipologies = [{"name": "Cereale", "count": 12}, {"name": "Leguminoase", "count": 8}]

    # Statistici gestiuni
    gestiune_stats = []
    try:
        gestiune_counts = GeneratedDocument.objects.values(
            gestiune_name=F('generated_by__userprofile__gestiune__nume')
        ).annotate(count=Count('id')).order_by('-count')
        gestiune_stats = [
            {"name": item['gestiune_name'] or "Nespecificată", "count": item['count']}
            for item in gestiune_counts if item['count'] > 0 # Afișăm doar cele cu documente
        ]
    except Exception as e:
        print(f"Eroare la calculul statisticilor pe gestiuni: {e}")
        # Fallback data
        gestiune_stats = [{"name": "Gestiune 1", "count": 35}, {"name": "Gestiune 2", "count": 22}]

    # Distribuție statusuri
    status_counts = dict(GeneratedDocument.objects.values_list('status').annotate(count=Count('id')))
    status_labels = dict(GeneratedDocument.STATUS_CHOICES)
    status_data = [{'status': status_labels.get(status, status), 'count': count} for status, count in status_counts.items()]

    # Documente lunare (ultimele 6 luni)
    six_months_ago = timezone.now() - timedelta(days=180)
    monthly_data_qs = (
        GeneratedDocument.objects
        .filter(created_at__gte=six_months_ago)
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(count=Count('id'))
        .order_by('month')
    )
    months_list = [{'month': entry['month'].strftime('%b %Y'), 'count': entry['count']} for entry in monthly_data_qs]

    # Distribuție tipologii (Top 5 total)
    tipologii_data = []
    try:
        tipologie_counts_total = defaultdict(int)
        all_docs_json = GeneratedDocument.objects.filter(context_json__isnull=False).values_list('context_json', flat=True)
        for context_json_str in all_docs_json:
             try:
                context_data = json.loads(context_json_str)
                for i in range(1, 4):
                    pos_key = f"pozitie{i}"
                    if pos_key in context_data and isinstance(context_data[pos_key], dict):
                        tipologie = context_data[pos_key].get('tipologie')
                        if tipologie: tipologie_counts_total[tipologie] += 1
             except (json.JSONDecodeError, KeyError, TypeError): continue

        top_tipologii = sorted(tipologie_counts_total.items(), key=lambda x: x[1], reverse=True)[:5]
        tipologii_data = [{"name": name, "value": count} for name, count in top_tipologii]
    except Exception as e:
        print(f"Eroare la obținerea datelor despre tipologii (total): {e}")
        # Fallback
        tipologii_data = [{"name": "Cereale", "value": 50}, {"name": "Leguminoase", "value": 30}]

    # Date simulate dacă nu există date reale
    if not months_list:
        now = timezone.now()
        months_list = [{'month': (now - timedelta(days=30 * i)).strftime('%b %Y'), 'count': random.randint(5, 30)} for i in range(6, 0, -1)]
    if not status_data:
        status_data = [{'status': 'Salvat', 'count': 10}, {'status': 'Finalizat', 'count': 20}, {'status': 'In procesare', 'count': 5}]
    if not tipologii_data:
         tipologii_data = [{"name": "Simulat1", "value": 15}, {"name": "Simulat2", "value": 10}]


    context = {
        'current_date': current_date,
        'quote': quote,
        'total_finalized_documents': total_finalized_documents,
        'my_distinct_avize': my_distinct_avize,
        'recent_avize': recent_avize,
        'recent_tipologies': recent_tipologies,
        'gestiune_stats': gestiune_stats,
        'monthly_data': json.dumps(months_list),
        'status_data': json.dumps(status_data),
        'tipologii_data': json.dumps(tipologii_data)
    }
    return render(request, "home.html", context)

# --- View raportare (rămâne la fel) ---
@login_required(login_url='/login/')
def raportare(request):
    # Verifică permisiunea ok_raportare
    user_profile = getattr(request.user, 'userprofile', None)
    if not user_profile or not user_profile.ok_raportare:
        StandardMessages.access_denied(request)
        log_activity(request.user, "RAPORTARE_DENIED", "Încercare acces raportare fără permisiune ok_raportare.")
        return redirect('home')
    
    log_activity(request.user, "ACCESS_REPORT", "A accesat pagina de raportare.")
    return render(request, "certificat/raportare.html")

# --- View logout_view (rămâne la fel) ---
def logout_view(request):
    user = request.user # Get user before logout for logging if needed (signals handle this)
    logout(request)
    # log_activity is handled by signal user_logged_out
    return redirect('login')

# --- View edit_extra_data (nefolosit, rămâne la fel dar cu logare) ---
@login_required(login_url='/login/')
def edit_extra_data(request):
    serie_val = request.GET.get("serie", "").strip()
    if request.method == "POST":
        form = SerieExtraDataForm(request.POST)
        if form.is_valid():
            extra_data, created = SerieExtraData.objects.update_or_create(
                serie=form.cleaned_data["serie"],
                defaults=form.cleaned_data
            )
            action_desc = 'creată' if created else 'actualizată'
            log_activity(
                request.user,
                "LEGACY_EXTRA_DATA_SAVE",
                f"Datele extra (formular vechi) pentru seria '{form.cleaned_data['serie']}' au fost {action_desc}."
            )
            if created: StandardMessages.item_created(request, "Datele extra pentru serie")
            else: StandardMessages.item_updated(request, "Datele extra pentru serie")
            # Redirect to appropriate page, maybe document list or admin?
            return redirect("administrare") # Presupunând că admin e locul potrivit
        else:
            StandardMessages.operation_failed(request, "salvarea datelor extra", "Verifică datele introduse")
            log_activity(request.user, "LEGACY_EXTRA_DATA_FAIL", f"Salvare date extra (vechi) eșuată. Seria: {serie_val}. Erori: {form.errors.as_json()}")
    else:
        try:
            extra_data = SerieExtraData.objects.get(serie=serie_val)
            form = SerieExtraDataForm(instance=extra_data)
            log_activity(request.user, "ACCESS_LEGACY_EXTRA_DATA_EDIT", f"Accesat form editare (vechi) pt seria: {serie_val}")
        except SerieExtraData.DoesNotExist:
            form = SerieExtraDataForm(initial={"serie": serie_val})
            log_activity(request.user, "ACCESS_LEGACY_EXTRA_DATA_NEW", f"Accesat form creare (vechi) pt seria: {serie_val}")
        except Exception as e:
            StandardMessages.operation_failed(request, "încărcarea formularului", str(e))
            log_activity(request.user, "ACCESS_LEGACY_EXTRA_DATA_ERROR", f"Eroare acces form (vechi) pt seria: {serie_val}. Eroare: {e}")
            form = SerieExtraDataForm(initial={"serie": serie_val}) # Afișăm un form gol

    return render(request, "certificat/extra_data_form.html", {"form": form})

# --- View generate_docx (nefolosit, rămâne la fel dar cu logare) ---
def generate_docx(request):
    # Acest view pare să fie înlocuit de generate_docx_aviz
    # Adaugă logare dacă este încă utilizat
    log_activity(request.user, "ACCESS_LEGACY_FORM", "A accesat formularul vechi de generare (generate_docx).")
    messages.warning(request, "Acest formular este învechit. Folosiți funcția 'Generare Document'.")
    return render(request, "certificat/form_aviz.html") # Probabil ar trebui să redirecționeze


# --- Document Operations ---
@login_required(login_url='/login/')
def generate_docx_aviz(request):
    # Verifică permisiunea ok_aviz
    user_profile = getattr(request.user, 'userprofile', None)
    if not user_profile or not user_profile.ok_aviz:
        StandardMessages.access_denied(request)
        log_activity(request.user, "GENERATE_AVIZ_DENIED", "Încercare acces generare aviz fără permisiune ok_aviz.")
        return redirect('home')
    
    if request.method == "POST":
        aviz_input = request.POST.get("aviz_number", "").strip()
        action = request.POST.get("action", "generate").strip().lower()  # Normalizăm la lowercase
        status = "finalizat" if action == "generate" else "in procesare"
        generated_docs_info = []  # Colectăm informații pentru log

        log_activity(
            request.user,
            "AVIZ_PROCESS_START",
            f"Procesare începută pentru Aviz '{aviz_input}', Acțiune: {action}."
        )

        # --- Validări Inițiale ---
        if not aviz_input:
            StandardMessages.operation_failed(request, "generare document", "Numărul de aviz este obligatoriu.")
            log_activity(request.user, "AVIZ_PROCESS_FAIL", f"Procesare eșuată. Motiv: Aviz gol.")
            return redirect("generate_docx_aviz")
        try:
            aviz_input_numeric = float(aviz_input)
            # Poți adăuga validări suplimentare aici (ex: > 0)
        except ValueError:
            StandardMessages.operation_failed(request, "generare document",
                                              "Valoarea introdusă pentru aviz nu este un număr valid.")
            log_activity(request.user, "AVIZ_PROCESS_FAIL",
                         f"Procesare eșuată Aviz '{aviz_input}'. Motiv: Număr aviz invalid.")
            return redirect("generate_docx_aviz")

        # Verifică dacă există deja documente PENTRU ACEST UTILIZATOR (dacă nu e admin)
        user_profile = getattr(request.user, 'userprofile', None)
        is_admin_or_super = user_profile and user_profile.role and user_profile.role.name.lower() in ['admin',
                                                                                                      'superadmin']

        # Verifică dacă există deja documente NEȘTERSE pentru acest aviz
        existing_docs_query = GeneratedDocument.objects.filter(aviz_number=aviz_input, is_deleted=False)

        if existing_docs_query.exists():
            StandardMessages.duplicate_warning(request, "document pentru avizul", aviz_input)
            log_activity(request.user, "AVIZ_PROCESS_FAIL",
                         f"Procesare eșuată Aviz '{aviz_input}'. Motiv: Documente existente.")
            return redirect("generate_docx_aviz")

        # --- Logică Gestiune ---
        gestiune = None
        if user_profile:
            if is_admin_or_super:
                selected_gestiune_id = request.POST.get("gestiune_id")
                if selected_gestiune_id:
                    try:
                        gestiune = get_object_or_404(Gestiune, pk=selected_gestiune_id)
                    except (ValueError, Http404):
                        StandardMessages.operation_failed(request, "generare document",
                                                          "Gestiunea selectată este invalidă.")
                        log_activity(request.user, "AVIZ_PROCESS_FAIL",
                                     f"Procesare eșuată Aviz '{aviz_input}'. Motiv: Gestiune ID invalid ({selected_gestiune_id}).")
                        return redirect("generate_docx_aviz")
                else:
                    gestiune = user_profile.gestiune
                    if not gestiune:
                        StandardMessages.operation_failed(request, "generare document",
                                                          "Admin/Superadmin trebuie să selecteze o gestiune sau să aibă una asignată.")
                        log_activity(request.user, "AVIZ_PROCESS_FAIL",
                                     f"Procesare eșuată Aviz '{aviz_input}'. Motiv: Admin/Superadmin fără gestiune selectată/asignată.")
                        return redirect("generate_docx_aviz")

            else:  # Utilizator normal
                gestiune = user_profile.gestiune
                if not gestiune:
                    StandardMessages.operation_failed(request, "generare document",
                                                      "Utilizatorul nu are o gestiune asignată.")
                    log_activity(request.user, "AVIZ_PROCESS_FAIL",
                                 f"Procesare eșuată Aviz '{aviz_input}'. Motiv: User fără gestiune.")
                    return redirect("generate_docx_aviz")
        else:
            StandardMessages.operation_failed(request, "generare document",
                                              "Profilul utilizatorului nu a putut fi încărcat.")
            log_activity(request.user, "AVIZ_PROCESS_FAIL",
                         f"Procesare eșuată Aviz '{aviz_input}'. Motiv: User fără profil.")
            return redirect("generate_docx_aviz")

        # --- Procesare Câmpuri Extra din Modal ---
        extra_data_forms = {}
        pattern_extra = re.compile(r"extra-(\d+)-(.+)")
        for key, value in request.POST.items():
            match = pattern_extra.match(key)
            if match:
                idx = match.group(1)
                field_name = match.group(2)
                if idx not in extra_data_forms:
                    extra_data_forms[idx] = {}
                extra_data_forms[idx][field_name] = value.strip()

        for idx, data in extra_data_forms.items():
            serie_val = data.get("serie", "").strip()
            if serie_val:
                defaults_data = {k: v for k, v in data.items() if k != 'serie'}
                try:
                    extra_obj, created = SerieExtraData.objects.update_or_create(
                        serie=serie_val,
                        defaults=defaults_data
                    )
                    action_desc = 'create' if created else 'actualizate'
                    log_activity(
                        request.user,
                        "SERIE_DATA_SAVE",
                        f"Datele extra pentru seria '{serie_val}' (Aviz: {aviz_input}) au fost {action_desc}."
                    )
                except Exception as e_save_extra:
                    print(f"ERROR: Nu s-au putut salva datele extra pentru seria {serie_val}. Eroare: {e_save_extra}")
                    messages.error(request,
                                   f"A apărut o eroare la salvarea datelor pentru seria {serie_val}. Verificați datele introduse.")
                    log_activity(request.user, "SERIE_DATA_SAVE_FAIL",
                                 f"Salvare date extra eșuată Seria '{serie_val}' (Aviz: {aviz_input}). Eroare: {e_save_extra}")
                    return redirect("generate_docx_aviz")

        # --- Preluare și Procesare Date JSON ---
        json_url = "https://moldova.info-media.ro/surse/WebFormExportDate.aspx?token=wme_avize_serii_cant"
        try:
            response = requests.get(json_url, timeout=20)
            response.raise_for_status()
            data_list = response.json()
        except requests.exceptions.Timeout:
            StandardMessages.operation_failed(request, "preluare date", "Serverul extern nu a răspuns în timp util.")
            log_activity(request.user, "AVIZ_PROCESS_FAIL",
                         f"Procesare eșuată Aviz '{aviz_input}'. Motiv: Timeout JSON API.")
            return redirect("generate_docx_aviz")
        except requests.exceptions.RequestException as e_req:
            StandardMessages.operation_failed(request, "preluare date", f"Eroare de rețea: {str(e_req)}")
            log_activity(request.user, "AVIZ_PROCESS_FAIL",
                         f"Procesare eșuată Aviz '{aviz_input}'. Motiv: Eroare rețea JSON API ({e_req}).")
            return redirect("generate_docx_aviz")
        except json.JSONDecodeError as e_json:
            StandardMessages.operation_failed(request, "preluare date",
                                              "Datele primite de la serverul extern sunt invalide.")
            log_activity(request.user, "AVIZ_PROCESS_FAIL",
                         f"Procesare eșuată Aviz '{aviz_input}'. Motiv: Eroare parsare JSON ({e_json}).")
            return redirect("generate_docx_aviz")
        except Exception as e:
            StandardMessages.operation_failed(request, "preluare date", f"Eroare neașteptată: {str(e)}")
            log_activity(request.user, "AVIZ_PROCESS_FAIL",
                         f"Procesare eșuată Aviz '{aviz_input}'. Motiv: Eroare necunoscută JSON API ({e}).")
            return redirect("generate_docx_aviz")

        aviz_records = []
        try:
            aviz_records = [item for item in data_list if int(float(item.get("AVIZ", 0))) == int(aviz_input_numeric)]
        except (ValueError, TypeError) as e_filter:
            StandardMessages.operation_failed(request, "procesare date",
                                              f"Eroare la filtrarea datelor primite (format invalid?). {e_filter}")
            log_activity(request.user, "AVIZ_PROCESS_FAIL",
                         f"Procesare eșuată Aviz '{aviz_input}'. Motiv: Eroare filtrare date JSON ({e_filter}).")
            return redirect("generate_docx_aviz")

        if not aviz_records:
            StandardMessages.item_not_found(request, f"date pentru avizul cu numărul {aviz_input}")
            log_activity(request.user, "AVIZ_PROCESS_FAIL",
                         f"Procesare eșuată Aviz '{aviz_input}'. Motiv: Aviz negăsit în JSON API.")
            return redirect("generate_docx_aviz")

        groups = {}
        partner_name = aviz_records[0].get("PARTENER", "N/A")
        for record in aviz_records:
            articol = record.get("ARTICOL", "").strip()
            serie = record.get("SERIE", "").strip()
            try:
                cantitate = float(record.get("CANT", 0))
            except (ValueError, TypeError):
                cantitate = 0
            specie = record.get("SPECIE", "").strip()
            um = record.get("UM", "").strip()
            soi = record.get("soi", "").strip() or articol
            nr_referinta = record.get("nr_referinta", "").strip() or serie

            key = (articol, serie)
            if key not in groups:
                groups[key] = {
                    "articol": articol, "serie": serie, "cantitate": 0,
                    "specia": specie, "um": um, "soi": soi,
                    "nr_referinta": nr_referinta
                }
            groups[key]["cantitate"] += cantitate

        tipologie_groups = defaultdict(list)
        general_tipologie = TipologieProdus.objects.filter(nume__iexact="General").first()

        for group_data in groups.values():
            mapping = SpecieMapping.objects.filter(specie__iexact=group_data["specia"]).select_related(
                'tipologie').first()
            tipologie_obj = mapping.tipologie if mapping and mapping.tipologie else general_tipologie
            tipologie_name = tipologie_obj.nume if tipologie_obj else "General"
            group_data["tipologie"] = tipologie_name
            tipologie_groups[tipologie_name].append(group_data)

        nrinreg = gestiune.cod_inregistrare if gestiune and gestiune.cod_inregistrare else ""
        current_date_str = timezone.now().strftime("%d.%m.%Y")
        gestiune_placeholder = gestiune.nume if gestiune else "Necunoscută"

        for tipologie_name, groups_list in tipologie_groups.items():
            groups_list = sorted(groups_list, key=lambda x: (x["articol"], x["serie"]))
            tip_obj = TipologieProdus.objects.filter(nume__iexact=tipologie_name).first()
            if not tip_obj:
                print(f"WARN: Tipologia '{tipologie_name}' nu a fost găsită în DB. Se va folosi range-ul 'General'.")
                tip_obj = general_tipologie

            chunks = [groups_list[i:i + 3] for i in range(0, len(groups_list), 3)]

            for part_index, chunk in enumerate(chunks, start=1):
                seria_placeholder = get_next_document_number(gestiune, tip_obj)
                if not seria_placeholder or seria_placeholder in ["Range epuizat", "Prefix/format incompatibil"]:
                    error_msg = f"Nu s-a putut obține un număr valid din plaja pentru Gestiune '{gestiune.nume}' / Tipologie '{tipologie_name}'. Motiv: {seria_placeholder or 'Range negăsit'}."
                    StandardMessages.operation_failed(request, "generare document", error_msg)
                    log_activity(request.user, "AVIZ_PROCESS_FAIL", f"Procesare Aviz '{aviz_input}'. {error_msg}")
                    return redirect("generate_docx_aviz")

                safe_tipologie_name = re.sub(r'[^\w\-]+', '_', tipologie_name)

                context_doc = {
                    "nrinreg": nrinreg, "aviz": aviz_input, "data_gen": current_date_str,
                    "beneficiar": partner_name, "seria": seria_placeholder,
                    "date": current_date_str, "gestiune": gestiune_placeholder,
                    "pozitie1": chunk[0] if len(chunk) > 0 else {},
                    "pozitie2": chunk[1] if len(chunk) > 1 else {},
                    "pozitie3": chunk[2] if len(chunk) > 2 else {}
                }
                for i in range(1, 4):
                    pos_key = f"pozitie{i}";
                    extra_key = f"extra{i}"
                    serie_in_pos = context_doc[pos_key].get("serie") if isinstance(context_doc.get(pos_key),
                                                                                   dict) else None
                    if serie_in_pos:
                        try:
                            extra_obj = SerieExtraData.objects.get(serie=serie_in_pos)
                            context_doc[extra_key] = model_to_dict(extra_obj, exclude=['id', 'serie'])
                        except SerieExtraData.DoesNotExist:
                            context_doc[extra_key] = {}
                        except Exception as e_get_extra:
                            print(
                                f"ERROR: Eroare la preluarea datelor extra pentru seria {serie_in_pos}: {e_get_extra}")
                            context_doc[extra_key] = {"error": "Date indisponibile"}
                    else:
                        context_doc[extra_key] = {}

                try:
                    context_json_str = json.dumps(context_doc, ensure_ascii=False)
                except TypeError as e_json_dump:
                    StandardMessages.operation_failed(request, "salvare document",
                                                      f"Eroare la pregătirea datelor pentru salvare: {e_json_dump}")
                    log_activity(request.user, "AVIZ_PROCESS_FAIL",
                                 f"Procesare Aviz '{aviz_input}'. Motiv: Eroare serializare JSON ({e_json_dump}). Context: {str(context_doc)[:200]}")
                    return redirect("generate_docx_aviz")

                gen_doc = GeneratedDocument(
                    aviz_number=aviz_input,
                    generated_by=request.user,
                    status=status,
                    partner=partner_name,
                    document_series=seria_placeholder,
                    context_json=context_json_str
                )

                pdf_content = None
                fname = None
                if action == "generate":
                    if not PDF_CONVERSION_ENABLED:
                        StandardMessages.operation_failed(request,
                                                          f"generarea PDF pt {tipologie_name} Partea {part_index}",
                                                          "Conversia PDF nu este configurată corect pe server.")
                        log_activity(request.user, "DOC_GENERATE_FAIL_SETUP",
                                     f"Generare PDF eșuată Aviz {aviz_input}. Motiv: PDF Conversion Disabled/Misconfigured.")
                        gen_doc.status = 'in procesare'
                    else:
                        try:
                            template_path = os.path.join(settings.BASE_DIR, "certificat", "template.docx")
                            if not os.path.exists(template_path):
                                raise FileNotFoundError(f"Template-ul DOCX nu a fost găsit la calea: {template_path}")

                            doc_template = DocxTemplate(template_path)
                            doc_template.render(context_doc)

                            temp_docx_path, temp_pdf_path = None, None
                            try:
                                with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp_docx, \
                                        tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
                                    temp_docx_path = tmp_docx.name
                                    temp_pdf_path = tmp_pdf.name
                                    doc_template.save(temp_docx_path)

                                conversion_success = False
                                if platform.system() == "Windows":
                                    pythoncom.CoInitialize()
                                try:
                                    print(f"DEBUG ({platform.system()}): Attempting DOCX -> PDF conversion...")
                                    convert(temp_docx_path, temp_pdf_path)
                                    print(
                                        f"DEBUG ({platform.system()}): Conversion potentially successful. PDF at {temp_pdf_path}")

                                    if os.path.exists(temp_pdf_path) and os.path.getsize(temp_pdf_path) > 0:
                                        with open(temp_pdf_path, "rb") as pdf_file:
                                            pdf_content = pdf_file.read()
                                            if pdf_content:
                                                conversion_success = True
                                            else:
                                                print(
                                                    f"WARN ({platform.system()}): PDF file is empty after conversion: {temp_pdf_path}")
                                    else:
                                        print(
                                            f"WARN ({platform.system()}): PDF file not found or empty after conversion attempt: {temp_pdf_path}")

                                except Exception as e_conv:
                                    error_type = "Unknown"
                                    user_msg = f"Eroare în timpul conversiei: {e_conv}"
                                    if platform.system() == "Windows" and isinstance(e_conv, COMError):
                                        error_type = f"COM Error ({e_conv.hresult})"
                                        if e_conv.hresult == -2147023170:
                                            user_msg = "Serviciul Microsoft Word nu a putut fi contactat."
                                        else:
                                            user_msg = f"Eroare internă de conversie (COM: {e_conv.hresult})."
                                    elif platform.system() == "Linux" and isinstance(e_conv, (FileNotFoundError,
                                                                                              subprocess.CalledProcessError,
                                                                                              subprocess.TimeoutExpired,
                                                                                              RuntimeError)):
                                        error_type = "LibreOffice/Subprocess Error"
                                        if isinstance(e_conv, subprocess.TimeoutExpired):
                                            user_msg = "Conversia PDF a durat prea mult (timeout). Resurse server insuficiente?"
                                        elif isinstance(e_conv, FileNotFoundError):
                                            user_msg = "Eroare conversie: Comanda 'soffice' (LibreOffice) nu a fost găsită."
                                        else:
                                            user_msg = "Eroare la conversia cu LibreOffice. Verificați instalarea și resursele serverului."
                                    elif 'docx2pdf' in str(type(e_conv)):
                                        error_type = "docx2pdf Library Error"
                                        user_msg = f"Eroare internă în biblioteca de conversie: {e_conv}"

                                    print(
                                        f"ERROR ({platform.system()}): Conversion failed: {error_type} - {e_conv}\n{traceback.format_exc()}")
                                    log_activity(
                                        request.user,
                                        "DOC_GENERATE_FAIL_CONVERT",
                                        f"Generare PDF eșuată Aviz {aviz_input} ({seria_placeholder}). {error_type}: {e_conv}"
                                    )
                                    StandardMessages.operation_failed(request,
                                                                      f"generarea PDF pt {tipologie_name} Partea {part_index}",
                                                                      user_msg)
                                    gen_doc.status = 'in procesare'

                                finally:
                                    if platform.system() == "Windows":
                                        try:
                                            pythoncom.CoUninitialize()
                                        except Exception as e_uninit:
                                            print(f"WARN: Eroare la CoUninitialize: {e_uninit}")

                            finally:
                                for path in [temp_docx_path, temp_pdf_path]:
                                    if path and os.path.exists(path):
                                        try:
                                            os.remove(path)
                                        except OSError as e_rem:
                                            print(f"WARN: Nu s-a putut șterge fișierul temporar {path}: {e_rem}")

                            if conversion_success and pdf_content:
                                fname_base = f"document_{gen_doc.aviz_number}"
                                fname_suffix = f"{safe_tipologie_name}_part{part_index}"
                                fname = f"{fname_base}_{fname_suffix}.pdf"
                                gen_doc.pdf_file.save(fname, ContentFile(pdf_content), save=False)
                                gen_doc.status = 'finalizat'

                        except FileNotFoundError as e_fnf:
                            StandardMessages.operation_failed(request, f"generarea documentului",
                                                              f"Eroare de configurare: {e_fnf}")
                            log_activity(request.user, "DOC_GENERATE_FAIL_SETUP",
                                         f"Generare eșuată Aviz {aviz_input}. Motiv: Template DOCX lipsă.")
                            return redirect("generate_docx_aviz")
                        except Exception as e_gen:
                            StandardMessages.operation_failed(request,
                                                              f"generarea documentului pt {tipologie_name} Partea {part_index}",
                                                              str(e_gen))
                            log_activity(request.user, "DOC_GENERATE_FAIL",
                                         f"Generare eșuată (pre-conversie) Aviz {aviz_input} ({seria_placeholder}). Eroare: {e_gen}\n{traceback.format_exc()}")
                            gen_doc.status = 'in procesare'

                try:
                    gen_doc.save()
                    if action == "generate":
                        if gen_doc.status == 'finalizat' and fname:
                            log_activity(request.user, "DOC_GENERATE_SUCCESS",
                                         f"Document generat Aviz {gen_doc.aviz_number} (Serie Doc: {gen_doc.document_series}, Tipologie: {safe_tipologie_name}, Parte: {part_index}). PDF: {fname}")
                            generated_docs_info.append(f"Serie: {gen_doc.document_series} (PDF: {fname})")
                        else:
                            log_activity(request.user, "DOC_GENERATE_PARTIAL",
                                         f"Document salvat (fără PDF/eroare) Aviz {gen_doc.aviz_number} (Serie Doc: {gen_doc.document_series}, Tipologie: {safe_tipologie_name}, Parte: {part_index}). Status: {gen_doc.status}")
                            generated_docs_info.append(f"Serie: {gen_doc.document_series} (Status: {gen_doc.status})")
                    elif action == "save":
                        log_activity(request.user, "DOC_SAVE_SUCCESS",
                                     f"Document rezervat Aviz {gen_doc.aviz_number} (Serie Doc: {gen_doc.document_series}, Tipologie: {safe_tipologie_name}, Parte: {part_index}). Status: {gen_doc.status}.")
                        generated_docs_info.append(f"Serie: {gen_doc.document_series} (Rezervat)")
                except Exception as e_save_db:
                    StandardMessages.operation_failed(request, "salvare document",
                                                      f"Eroare critică la salvarea în baza de date: {e_save_db}")
                    log_activity(request.user, "DOC_SAVE_DB_FAIL",
                                 f"Salvare DB eșuată Aviz {gen_doc.aviz_number} ({seria_placeholder}). Eroare: {e_save_db}\n{traceback.format_exc()}")
                    return redirect("generate_docx_aviz")

        if action == "generate":
            if any('(PDF:' in info for info in generated_docs_info):
                StandardMessages.document_generated(request)
                log_activity(request.user, "AVIZ_PROCESS_SUCCESS",
                             f"Procesare Aviz '{aviz_input}' finalizată (Generare). Documente: {'; '.join(generated_docs_info)}")
                return redirect("document_preview", aviz=aviz_input)
            elif generated_docs_info:
                messages.warning(request,
                                 "Documentele au fost salvate în sistem, dar generarea PDF a eșuat pentru toate părțile. Le puteți edita și regenera ulterior.")
                log_activity(request.user, "AVIZ_PROCESS_PARTIAL_FAIL",
                             f"Procesare Aviz '{aviz_input}' finalizată (Generare), dar FĂRĂ PDF-uri. Documente: {'; '.join(generated_docs_info)}")
                return redirect("generated_documents_list")
            else:
                log_activity(request.user, "AVIZ_PROCESS_COMPLETE_FAIL",
                             f"Procesare Aviz '{aviz_input}' eșuată complet (Generare), niciun document salvat.")
                return redirect("generate_docx_aviz")

        elif action == "save":
            if generated_docs_info:
                StandardMessages.document_reserved(request)
                log_activity(request.user, "AVIZ_PROCESS_SUCCESS",
                             f"Procesare Aviz '{aviz_input}' finalizată (Salvare). Documente rezervate: {'; '.join(generated_docs_info)}")
                return redirect("generated_documents_list")
            else:
                log_activity(request.user, "AVIZ_PROCESS_COMPLETE_FAIL",
                             f"Procesare Aviz '{aviz_input}' eșuată complet (Salvare), niciun document salvat.")
                return redirect("generate_docx_aviz")

        log_activity(request.user, "AVIZ_PROCESS_UNHANDLED",
                     f"Caz neacoperit la finalul procesării Aviz '{aviz_input}'. Action: {action}")
        return redirect("generate_docx_aviz")

    else:
        context = {}
        user_profile = getattr(request.user, 'userprofile', None)
        is_admin_or_superadmin = user_profile and user_profile.role and user_profile.role.name.lower() in ["admin",
                                                                                                           "superadmin"]

        if is_admin_or_superadmin:
            try:
                context["gestiuni"] = Gestiune.objects.all().order_by('nume')
            except Exception as e:
                context["gestiuni"] = Gestiune.objects.none()

        aviz_param = request.GET.get("aviz_number", "").strip()
        context["series_list"] = []
        context["series_info"] = {}
        context["extra_data_mapping"] = {}

        if aviz_param:
            try:
                aviz_param_int = int(float(aviz_param))
                json_url = "https://moldova.info-media.ro/surse/WebFormExportDate.aspx?token=wme_avize_serii_cant"
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept': 'application/json, text/plain, */*',
                    'Accept-Language': 'ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7',
                    'Referer': 'https://moldova.info-media.ro/'
                }
                response = requests.get(json_url, headers=headers, timeout=15, verify=True)
                response.raise_for_status()
                data_list = response.json()

                series_set = set()
                series_info_temp = {}
                relevant_items_count = 0

                for item in data_list:
                    try:
                        item_aviz_str = item.get("AVIZ", "0")
                        item_aviz_float = float(item_aviz_str)
                        if int(item_aviz_float) == aviz_param_int:
                            relevant_items_count += 1
                            serie = str(item.get("SERIE", "")).strip()
                            articol_fields = ["ARTICOL", "soi", "SPECIE"]
                            articol = next((str(item.get(f, "")).strip() for f in articol_fields if item.get(f)), "N/A")

                            try:
                                cantitate_item = float(item.get("CANT", 0))
                            except (ValueError, TypeError):
                                cantitate_item = 0
                            um_item = str(item.get("UM", "")).strip()

                            if serie:
                                series_set.add(serie)
                                if serie not in series_info_temp:
                                    series_info_temp[serie] = {
                                        'articol': articol,
                                        'cantitate': 0.0,
                                        'um': um_item if um_item else ""
                                    }
                                if articol != "N/A" and (
                                        series_info_temp[serie]['articol'] == "N/A" or not series_info_temp[serie][
                                    'articol']):
                                    series_info_temp[serie]['articol'] = articol
                                if not series_info_temp[serie]['um'] and um_item:
                                    series_info_temp[serie]['um'] = um_item

                                series_info_temp[serie]['cantitate'] += cantitate_item

                    except (ValueError, TypeError, AttributeError) as e_item:
                        print(
                            f"DEBUG (GET): Eroare la procesarea unui item din JSON: {e_item} - Item: {str(item)[:100]}")
                        continue

                context["series_list"] = sorted(list(series_set))
                context["series_info"] = series_info_temp

                extra_data_mapping_temp = {}
                if context["series_list"]:
                    db_extra_data = SerieExtraData.objects.filter(serie__in=context["series_list"])
                    for extra_obj in db_extra_data:
                        extra_data_mapping_temp[extra_obj.serie] = model_to_dict(extra_obj, exclude=['id', 'serie'])
                for serie in context["series_list"]:
                    if serie not in extra_data_mapping_temp:
                        extra_data_mapping_temp[serie] = {}
                context["extra_data_mapping"] = extra_data_mapping_temp

            except requests.exceptions.Timeout:
                messages.error(request, "Eroare: Serverul extern nu a răspuns în timp util.")
            except requests.exceptions.RequestException as e_req:
                messages.error(request, f"Eroare de rețea la preluarea datelor externe: {e_req}")
            except json.JSONDecodeError as e_json:
                messages.error(request, "Eroare: Datele primite de la serverul extern sunt invalide.")
            except ValueError as e_val:
                messages.error(request,
                               f"Numărul de aviz '{aviz_param}' nu este valid sau datele primite conțin erori.")
            except Exception as e:
                messages.error(request, f"A apărut o eroare neașteptată la preluarea detaliilor: {e}")
            finally:
                if "error" in [m.level_tag for m in messages.get_messages(request)]:
                    context["series_list"], context["series_info"], context["extra_data_mapping"] = [], {}, {}

        context["extra_data_form"] = SerieExtraDataForm()
        return render(request, "certificat/form_aviz.html", context)


# --- VIEW edit_generated_document ---
def edit_generated_document(request, doc_id):
    """
    Gestionează editarea detaliilor unui document generat și opțional regenerarea PDF-ului.
    """
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    print(f"DEBUG (edit view): doc_id={doc_id}, Method={request.method}, is_ajax={is_ajax}")

    # --- Obține Documentul și Verifică Permisiunile ---
    try:
        doc = get_object_or_404(
            GeneratedDocument.objects.select_related('generated_by__userprofile__role'),
            id=doc_id
        )
    except (Http404, ValueError):  # Prinde ValueError dacă doc_id nu este un int
        log_activity(request.user, "EDIT_DOC_NOT_FOUND",
                     f"Încercare de acces pentru editare document inexistent/invalid ID: {doc_id}.")
        StandardMessages.item_not_found(request, "Documentul")
        return redirect("generated_documents_list")

    # Verifică dacă documentul este șters
    if doc.is_deleted:
        log_activity(request.user, "EDIT_DOC_DELETED",
                     f"Încercare de editare a unui document șters. ID: {doc_id}, Aviz: {doc.aviz_number}")
        messages.error(request, "Nu puteți edita un document care a fost șters.")
        return redirect("generated_documents_list")

    log_base_info = f"(ID: {doc.id}, Aviz: {doc.aviz_number}, Serie Doc: {doc.document_series})"

    # Verifică permisiuni
    user_profile = getattr(request.user, 'userprofile', None)
    is_owner = doc.generated_by_id == request.user.id
    is_admin_or_super = user_profile and user_profile.role and user_profile.role.name.lower() in ['admin', 'superadmin']

    if not (is_owner or is_admin_or_super):
        log_activity(request.user, "EDIT_DOC_DENIED",
                     f"Încercare neautorizată de acces pentru editare doc {log_base_info}.")
        StandardMessages.access_denied(request)
        return redirect("generated_documents_list")

    # --- Extrage Datele Inițiale și Pregătește FormSet ---
    series_list = []
    series_info = {}  # MODIFICAT: Va stoca {'serie': {'articol': ..., 'cantitate': ..., 'um': ...}}
    context_dict_initial = {}
    try:
        if doc.context_json:
            context_dict_initial = json.loads(doc.context_json)
            if not isinstance(context_dict_initial, dict):
                raise json.JSONDecodeError("Structură JSON invalidă", doc.context_json, 0)

            pattern = re.compile(r"pozitie(\d+)")
            for key, pos_data in context_dict_initial.items():
                match = pattern.match(key)
                if match and isinstance(pos_data, dict):
                    serie_val = str(pos_data.get("serie", "")).strip()
                    articol_fields = ["articol", "ARTICOL", "soi", "specia", "tipologie"]
                    articol_val = next((str(pos_data.get(k, "")).strip() for k in articol_fields if pos_data.get(k)),
                                       "N/A")

                    cantitate_val = pos_data.get("cantitate", "")
                    um_val = pos_data.get("um", "")

                    if serie_val:
                        if serie_val not in series_list:
                            series_list.append(serie_val)
                        series_info[serie_val] = {
                            'articol': articol_val,
                            'cantitate': cantitate_val,
                            'um': um_val
                        }
    except json.JSONDecodeError as e:
        log_activity(request.user, "EDIT_DOC_JSON_ERROR",
                     f"Eroare parsare JSON pentru doc {log_base_info}. Eroare: {e}")
        messages.error(request, f"Eroare la citirea detaliilor salvate (JSON invalid).")
    except Exception as e:
        log_activity(request.user, "EDIT_DOC_DATA_ERROR",
                     f"Eroare la extragerea datelor pentru doc {log_base_info}. Eroare: {e}")
        messages.error(request, f"Eroare neașteptată la citirea detaliilor documentului.")

    SerieExtraDataFormSet = modelformset_factory(SerieExtraData, form=SerieExtraDataForm, extra=0,
                                                 can_delete=False)
    queryset_formset = SerieExtraData.objects.filter(serie__in=series_list)

    if request.method == 'POST':
        action = request.POST.get("action", "").strip().lower()
        formset = SerieExtraDataFormSet(request.POST, queryset=queryset_formset,
                                        prefix='form')

        if formset.is_valid():
            print(f"DEBUG (edit view): Formset este valid. Acțiune: {action}")

            if action == "save":
                try:
                    instances = formset.save()
                    saved_series = [inst.serie for inst in instances]
                    log_activity(request.user, "DOC_DETAILS_SAVE",
                                 f"Detalii salvate {log_base_info} ({len(instances)} instanțe pentru seriile: {saved_series}).")
                    if is_ajax:
                        return JsonResponse({'status': 'success', 'message': 'Datele au fost salvate cu succes.'})
                    else:
                        StandardMessages.document_saved(request)
                        return redirect("document_preview", aviz=doc.aviz_number)
                except Exception as e:
                    error_message = f"Eroare la salvarea datelor: {e}"
                    print(f"ERROR (edit view): Salvare eșuată {log_base_info}. Eroare: {e}\n{traceback.format_exc()}")
                    log_activity(request.user, "DOC_DETAILS_SAVE_FAIL", f"Salvare eșuată {log_base_info}. Eroare: {e}")
                    if is_ajax:
                        return JsonResponse({'status': 'error', 'message': error_message}, status=500)
                    else:
                        messages.error(request, error_message)
                        # MODIFICAT: Asigură-te că series_info e în context la re-render
                        context = {"aviz": doc.aviz_number, "doc": doc, "formset": formset, "series_info": series_info,
                                   "prefix": 'form'}
                        return render(request, "certificat/edit_generated_document.html", context)


            elif action == "generate":
                print(f"DEBUG (edit view): Inițiere regenerare pentru {log_base_info}")

                all_fields_filled = True
                empty_field_details = []
                try:
                    required_fields = [name for name, field in SerieExtraDataForm.base_fields.items() if field.required]
                except Exception:
                    required_fields = ['nr_ambalaje', 'doc_oficial', 'etch_oficiale', 'puritate', 'sem_straine',
                                       'umiditate', 'germinatie', 'masa_1000b', 'stare_sanitara', 'cold', 'producator',
                                       'tara_productie', 'samanta_tratata', 'garantie']

                for form_data_item in formset.cleaned_data:  # Renamed form_data to form_data_item
                    if not form_data_item or form_data_item.get('DELETE'):
                        continue
                    serie_current = form_data_item.get('serie', 'N/A')
                    for field_name in required_fields:
                        value = form_data_item.get(field_name)
                        if value is None or (isinstance(value, str) and not value.strip()):
                            all_fields_filled = False
                            try:
                                field_label = SerieExtraDataForm.base_fields[field_name].label or field_name
                            except KeyError:
                                field_label = field_name.replace('_', ' ').title()
                            empty_field_details.append(f"'{field_label}' (Serie: {serie_current})")

                if not all_fields_filled:
                    error_message = "Generarea a eșuat. Următoarele câmpuri obligatorii sunt necompletate: " + "; ".join(
                        sorted(list(set(empty_field_details))))
                    print(
                        f"ERROR (edit view): Validare eșuată {log_base_info}. Lipsesc: {'; '.join(empty_field_details)}")
                    log_activity(request.user, "DOC_REGENERATE_FAIL_EMPTY",
                                 f"Regenerare eșuată {log_base_info}. Motiv: Câmpuri goale server-side.")
                    messages.error(request, error_message)
                    context = {"aviz": doc.aviz_number, "doc": doc, "formset": formset, "series_info": series_info,
                               "prefix": 'form'}
                    return render(request, "certificat/edit_generated_document.html", context)

                if doc.status == 'finalizat':
                    messages.warning(request,
                                     f"Documentul pentru avizul {doc.aviz_number} / seria {doc.document_series} este deja finalizat. Regenerarea va crea o nouă versiune PDF.")
                    log_activity(request.user, "DOC_REGENERATE_WARNING",
                                 f"Avertisment regenerare {log_base_info}. Motiv: Document finalizat în curs de regenerare.")

                pdf_content = None
                fname = "document_generare_esuata.pdf"
                try:
                    instances = formset.save()
                    print(f"DEBUG (edit view): Formset salvat înainte de generare ({len(instances)} instanțe).")

                    updated_context_for_render = json.loads(
                        doc.context_json or '{}')  # Renamed updated_context to updated_context_for_render
                    document_tipologie = "Necunoscuta"
                    aviz_number = doc.aviz_number

                    # Extragem seriile din contextul actualizat
                    # Nu mai este nevoie să extragem series_list aici, îl avem deja populat global
                    # series_list_from_context = [] # Renamed series_list to series_list_from_context
                    # for i in range(1, 4):
                    #     pos_key = f"pozitie{i}"
                    #     if pos_key in updated_context_for_render and isinstance(updated_context_for_render[pos_key], dict):
                    #         serie = updated_context_for_render[pos_key].get("serie", "")
                    #         if serie:
                    #             series_list_from_context.append(serie)

                    external_data_updated = False
                    if series_list:  # Folosim series_list global
                        try:
                            json_url = "https://moldova.info-media.ro/surse/WebFormExportDate.aspx?token=wme_avize_serii_cant"
                            response = requests.get(json_url, timeout=20)
                            response.raise_for_status()
                            data_list_api = response.json()  # Renamed data_list to data_list_api

                            aviz_records = [item for item in data_list_api if
                                            int(float(item.get("AVIZ", 0))) == int(float(aviz_number))]

                            if aviz_records:
                                updated_data_api = {}  # Renamed updated_data to updated_data_api
                                for record in aviz_records:
                                    serie_api = record.get("SERIE", "").strip()  # Renamed serie to serie_api
                                    if serie_api in series_list:  # Folosim series_list global
                                        if serie_api not in updated_data_api:
                                            updated_data_api[serie_api] = {
                                                "serie": serie_api,
                                                "articol": record.get("ARTICOL", "").strip(),
                                                "cantitate": float(record.get("CANT", 0)),
                                                "specia": record.get("SPECIE", "").strip(),
                                                "um": record.get("UM", "").strip(),
                                                "soi": record.get("soi", "").strip() or record.get("ARTICOL",
                                                                                                   "").strip(),
                                                "nr_referinta": record.get("nr_referinta", "").strip() or serie_api
                                            }
                                        else:
                                            updated_data_api[serie_api]["cantitate"] += float(record.get("CANT", 0))

                                if updated_data_api:
                                    for i in range(1, 4):
                                        pos_key = f"pozitie{i}"
                                        if pos_key in updated_context_for_render and isinstance(
                                                updated_context_for_render[pos_key], dict):
                                            serie_in_pos = updated_context_for_render[pos_key].get("serie",
                                                                                                   "")  # Renamed serie to serie_in_pos
                                            if serie_in_pos in updated_data_api:
                                                updated_context_for_render[pos_key].update(
                                                    updated_data_api[serie_in_pos])
                                                external_data_updated = True
                                                if document_tipologie == "Necunoscuta" and "tipologie" in \
                                                        updated_context_for_render[pos_key]:
                                                    document_tipologie = updated_context_for_render[pos_key][
                                                        "tipologie"]
                                if external_data_updated:
                                    print(f"DEBUG (edit view): Actualizare date din sursa externă reușită")
                        except Exception as e_api:
                            print(f"WARN (edit view): Nu s-au putut actualiza datele din sursa externă: {e_api}")

                    extra_data_map_updated = {obj.serie: model_to_dict(obj, exclude=['id', 'serie'])
                                              for obj in SerieExtraData.objects.filter(
                            serie__in=series_list)}  # Folosim series_list global

                    for i in range(1, 4):
                        pos_key = f"pozitie{i}";
                        extra_key = f"extra{i}"
                        position_data = updated_context_for_render.get(pos_key)
                        if isinstance(position_data, dict):
                            serie_val_pos = position_data.get("serie")  # Renamed serie_val to serie_val_pos
                            if serie_val_pos:
                                extra_obj_data = extra_data_map_updated.get(serie_val_pos)
                                updated_context_for_render[extra_key] = {k: (v.strip() if isinstance(v, str) else v) for
                                                                         k, v in
                                                                         extra_obj_data.items()} if extra_obj_data else {}
                                if document_tipologie == "Necunoscuta":
                                    if 'tipologie' in position_data and position_data['tipologie']:
                                        document_tipologie = position_data['tipologie']
                                    elif 'specia' in position_data:
                                        mapping = SpecieMapping.objects.filter(
                                            specie__iexact=position_data['specia']).select_related('tipologie').first()
                                        if mapping and mapping.tipologie: document_tipologie = mapping.tipologie.nume
                            else:
                                updated_context_for_render[extra_key] = {}

                    if document_tipologie == "Necunoscuta": document_tipologie = "General"
                    safe_tipologie_name = re.sub(r'[^\w\-]+', '_', document_tipologie)
                    print(
                        f"DEBUG (edit view): Context reconstruit pentru template DOCX. Tipologie: {document_tipologie}")

                    if not PDF_CONVERSION_ENABLED:
                        raise RuntimeError("Conversia PDF nu este configurată/activată pe server.")

                    temp_docx_path, temp_pdf_path = None, None
                    conversion_success = False
                    try:
                        template_path = os.path.join(settings.BASE_DIR, "certificat", "template.docx")
                        if not os.path.exists(template_path):
                            raise FileNotFoundError(f"Fișierul template nu a fost găsit: {template_path}")

                        doc_template = DocxTemplate(template_path)
                        doc_template.render(updated_context_for_render)  # Folosim contextul actualizat
                        print(f"DEBUG (edit view): Template DOCX generat.")

                        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp_docx, \
                                tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
                            temp_docx_path = tmp_docx.name
                            temp_pdf_path = tmp_pdf.name
                            doc_template.save(temp_docx_path)
                        print(f"DEBUG (edit view): DOCX temporar salvat la {temp_docx_path}")

                        if platform.system() == "Windows":
                            pythoncom.CoInitialize()
                        try:
                            print(
                                f"DEBUG ({platform.system()}): Se încearcă conversia DOCX -> PDF pentru regenerare...")
                            convert(temp_docx_path, temp_pdf_path)
                            print(f"DEBUG ({platform.system()}): Conversie potențial reușită. PDF la {temp_pdf_path}")

                            if os.path.exists(temp_pdf_path) and os.path.getsize(temp_pdf_path) > 0:
                                with open(temp_pdf_path, "rb") as pdf_file:
                                    pdf_content = pdf_file.read()
                                    if pdf_content:
                                        conversion_success = True
                                    else:
                                        print(
                                            f"WARN ({platform.system()}): Fișier PDF gol după conversie: {temp_pdf_path}")
                            else:
                                print(
                                    f"WARN ({platform.system()}): Fișier PDF negăsit/gol după conversie: {temp_pdf_path}")

                        except Exception as e_conv:
                            error_type = "Necunoscută"
                            user_msg = f"Eroare în timpul conversiei: {e_conv}"
                            if platform.system() == "Windows" and isinstance(e_conv, COMError):
                                error_type = f"Eroare COM ({e_conv.hresult})"
                                if e_conv.hresult == -2147023170:
                                    user_msg = "Serviciul Microsoft Word nu a putut fi contactat."
                                else:
                                    user_msg = f"Eroare internă de conversie (COM: {e_conv.hresult})."
                            elif platform.system() == "Linux" and isinstance(e_conv, (FileNotFoundError,
                                                                                      subprocess.CalledProcessError,
                                                                                      subprocess.TimeoutExpired,
                                                                                      RuntimeError)):
                                error_type = "Eroare LibreOffice/Subprocess"
                                if isinstance(e_conv, subprocess.TimeoutExpired):
                                    user_msg = "Conversia PDF a durat prea mult (timeout)."
                                elif isinstance(e_conv, FileNotFoundError):
                                    user_msg = "Eroare conversie: Comanda 'soffice' (LibreOffice) nu a fost găsită."
                                else:
                                    user_msg = "Eroare la conversia cu LibreOffice."
                            elif 'docx2pdf' in str(type(e_conv)):
                                error_type = "Eroare bibliotecă docx2pdf"
                                user_msg = f"Eroare internă în biblioteca de conversie: {e_conv}"
                            print(
                                f"ERROR ({platform.system()}): Conversie regenerare eșuată: {error_type} - {e_conv}\n{traceback.format_exc()}")
                            log_activity(request.user, "DOC_REGENERATE_FAIL_CONVERT",
                                         f"Regenerare eșuată {log_base_info}. {error_type}: {e_conv}")
                            messages.error(request, f"Generarea PDF a eșuat: {user_msg}")
                        finally:
                            if platform.system() == "Windows":
                                try:
                                    pythoncom.CoUninitialize()
                                except Exception as e_uninit:
                                    print(f"WARN: Eroare la CoUninitialize: {e_uninit}")
                    finally:
                        for path in [temp_docx_path, temp_pdf_path]:
                            if path and os.path.exists(path):
                                try:
                                    os.remove(path)
                                    print(f"DEBUG (edit view): Șters fișier temporar {path}")
                                except OSError as e_rem:
                                    print(f"WARN (edit view): Nu s-a putut șterge fișierul temporar {path}: {e_rem}")

                    if conversion_success and pdf_content:
                        target_doc = doc
                        had_previous_pdf = bool(target_doc.pdf_file)
                        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
                        fname_base = f"document_{target_doc.aviz_number}_{target_doc.document_series or 'NA'}"
                        fname_suffix = f"{safe_tipologie_name}_regenerat_{timestamp}"
                        fname = f"{fname_base}_{fname_suffix}.pdf"

                        if target_doc.pdf_file:
                            try:
                                if target_doc.pdf_file.storage.exists(target_doc.pdf_file.name):
                                    target_doc.pdf_file.delete(save=False)
                                    print(f"DEBUG: Fișier PDF vechi șters: {target_doc.pdf_file.name}")
                            except Exception as e_del:
                                print(
                                    f"WARN (edit view): Nu s-a putut șterge fișierul PDF vechi {target_doc.pdf_file.name}: {e_del}")

                        target_doc.pdf_file.save(fname, ContentFile(pdf_content), save=False)
                        target_doc.status = "finalizat"
                        target_doc.context_json = json.dumps(updated_context_for_render, ensure_ascii=False,
                                                             indent=2)  # Folosim contextul actualizat
                        if had_previous_pdf:
                            target_doc.regenerated = True
                            target_doc.regenerated_at = timezone.now()
                            target_doc.regeneration_count = F('regeneration_count') + 1
                        else:
                            target_doc.regenerated = False
                            target_doc.regeneration_count = 0
                        target_doc.save()
                        target_doc.refresh_from_db(fields=['regeneration_count'])
                        print(
                            f"DEBUG (edit view): Obiect GeneratedDocument actualizat. Nou PDF: {fname}, Contor Regen: {target_doc.regeneration_count}")
                        log_activity(request.user, "DOC_REGENERATE_SUCCESS",
                                     f"Regenerat {log_base_info}. PDF: {fname}. Contor Regen: {target_doc.regeneration_count}.")
                        StandardMessages.document_generated(request)
                        return redirect("document_preview", aviz=target_doc.aviz_number)
                    else:
                        print(
                            f"WARN (edit view): Generare PDF eșuată pentru regenerare {log_base_info}, reafișăm formularul.")
                except FileNotFoundError as e_fnf:
                    error_message = f"Eroare de configurare: {e_fnf}"
                    print(f"ERROR (edit view): Eroare FileNotFoundError la regenerare {log_base_info}. Eroare: {e_fnf}")
                    log_activity(request.user, "DOC_REGENERATE_FAIL_SETUP",
                                 f"Regenerare eșuată {log_base_info}. Eroare: {e_fnf}")
                    messages.error(request, error_message)
                except Exception as e_gen:
                    error_message = f"A apărut o eroare neașteptată la generarea documentului: {e_gen}"
                    print(
                        f"ERROR (edit view): Eroare generică la regenerare {log_base_info}. Eroare: {e_gen}\n{traceback.format_exc()}")
                    log_activity(request.user, "DOC_REGENERATE_FAIL",
                                 f"Regenerare eșuată {log_base_info}. Eroare: {e_gen}")
                    messages.error(request, error_message)

                # MODIFICAT: Asigură-te că series_info e în context la re-render
                context = {"aviz": doc.aviz_number, "doc": doc, "formset": formset, "series_info": series_info,
                           "prefix": 'form'}
                return render(request, "certificat/edit_generated_document.html", context)
            else:
                print(f"WARN (edit view): Acțiune necunoscută '{action}' primită pentru {log_base_info}.")
                messages.warning(request, "Acțiune necunoscută specificată.")
                # MODIFICAT: Asigură-te că series_info e în context la re-render
                context = {"aviz": doc.aviz_number, "doc": doc, "formset": formset, "series_info": series_info,
                           "prefix": 'form'}
                return render(request, "certificat/edit_generated_document.html", context)
        else:
            error_message = "Eroare la validarea datelor. Verificați câmpurile marcate."
            print(f"ERROR (edit view): Formset invalid {log_base_info}. Acțiune: {action}. Erori: {formset.errors}")
            log_activity(request.user, "DOC_FORMSET_INVALID",
                         f"Formular invalid {log_base_info}. Acțiune: {action}. Erori: {formset.errors.as_json()}")
            if is_ajax and action == "save":
                simple_errors = {}
                for i, form_errors in enumerate(formset.errors):
                    if form_errors:
                        simple_errors[f"form-{i}"] = {k: v[0] for k, v in form_errors.items()}
                return JsonResponse({'status': 'error', 'message': error_message, 'errors': simple_errors}, status=400)
            else:
                messages.error(request, error_message)
                for form_error in formset.errors:
                    if form_error: messages.error(request, f"Detalii erori: {form_error}")
                # MODIFICAT: Asigură-te că series_info e în context la re-render
                context = {"aviz": doc.aviz_number, "doc": doc, "formset": formset, "series_info": series_info,
                           "prefix": 'form'}
                return render(request, "certificat/edit_generated_document.html", context)

    if request.method == 'GET':
        formset = SerieExtraDataFormSet(queryset=queryset_formset, prefix='form')
        log_activity(request.user, "ACCESS_EDIT_DOC_FORM", f"Accesat formular de editare pentru doc {log_base_info}.")

    context = {
        "aviz": doc.aviz_number,
        "doc": doc,
        "formset": formset,
        "series_info": series_info,
        "prefix": 'form'
    }

    if is_ajax and request.method == 'GET':
        print(f"DEBUG (edit view): Randăm template PARȚIAL pentru AJAX GET.")
        template_name = "certificat/partial_edit_generated_document.html"
    else:
        print(f"DEBUG (edit view): Randăm template COMPLET (Metoda: {request.method}, is_ajax: {is_ajax}).")
        template_name = "certificat/edit_generated_document.html"
    return render(request, template_name, context)


# --- delete_generated_document (rămâne dezactivat) ---
@login_required(login_url='/login/')
def delete_generated_document(request, doc_id):
    # Verifică dacă utilizatorul este superadmin
    user_profile = getattr(request.user, 'userprofile', None)
    is_superadmin = user_profile and user_profile.role and user_profile.role.name.lower() == 'superadmin'

    if not is_superadmin:
        messages.error(request, "Doar superadminii pot șterge documente.")
        log_activity(request.user, "DELETE_DOC_DENIED",
                     f"Încercare ștergere document ID: {doc_id}. Operațiune nepermisă pentru acest utilizator.")
        return redirect('generated_documents_list')

    try:
        doc = get_object_or_404(GeneratedDocument, id=doc_id)

        # Marchează documentul ca șters (soft delete)
        doc.is_deleted = True
        doc.deleted_at = timezone.now()
        doc.deleted_by = request.user
        doc.save()

        log_activity(request.user, "DELETE_DOC_SUCCESS",
                     f"Document ID: {doc_id} (Aviz: {doc.aviz_number}, Serie: {doc.document_series}) marcat ca șters.")
        StandardMessages.operation_success(request,
                                           f"Documentul pentru avizul {doc.aviz_number} a fost marcat ca șters.")

    except Http404:
        StandardMessages.item_not_found(request, "Documentul")
        log_activity(request.user, "DELETE_DOC_NOT_FOUND", f"Document ID: {doc_id} negăsit pentru ștergere.")
    except Exception as e:
        StandardMessages.operation_failed(request, "ștergerea documentului", str(e))
        log_activity(request.user, "DELETE_DOC_ERROR", f"Eroare la ștergerea documentului ID: {doc_id}. Eroare: {e}")

    return redirect('generated_documents_list')


# --- document_preview (rămâne la fel) ---
@login_required(login_url='/login/')
def document_preview(request, aviz):
    log_activity(request.user, "ACCESS_DOC_PREVIEW", f"A accesat preview pentru Aviz {aviz}.")
    user_profile = getattr(request.user, 'userprofile', None)
    is_admin_or_super = user_profile and user_profile.role and user_profile.role.name.lower() in ['admin', 'superadmin']

    if is_admin_or_super:
        docs = GeneratedDocument.objects.filter(aviz_number=aviz).order_by('document_series', 'created_at')
    else:
        docs = GeneratedDocument.objects.filter(aviz_number=aviz, generated_by=request.user).order_by('document_series', 'created_at')

    if not docs.exists():
        StandardMessages.item_not_found(request, f"documente generate pentru avizul {aviz}")
        # Unde redirectăm? La generare sau la listă? Lista pare mai logică.
        return redirect("generated_documents_list")

    # Colectăm URL-urile și ID-urile documentelor
    doc_data = []
    has_pdf = False
    for doc in docs:
        pdf_url = None
        if doc.pdf_file and doc.pdf_file.name:
             try:
                 pdf_url = doc.pdf_file.url
                 has_pdf = True
             except Exception as e:
                 print(f"Eroare la obținerea URL pentru {doc.pdf_file.name}: {e}")
        doc_data.append({'id': doc.id, 'series': doc.document_series, 'url': pdf_url, 'status': doc.get_status_display()})

    if not has_pdf:
        StandardMessages.info_message(request,
                                      "Documentele au fost rezervate dar încă nu au fost generate (sau generarea PDF a eșuat). Folosiți butonul Editează pentru a le genera/regenera.")
        # Redirecționează la lista de documente
        return redirect("generated_documents_list")

    return render(request, "certificat/document_preview.html", {"aviz": aviz, "doc_data": doc_data})


# --- User Management (administrare) ---
@login_required(login_url='/login/')
def administrare(request):
    user_profile = getattr(request.user, 'userprofile', None)
    
    # Verifică permisiunea ok_administrare
    if not user_profile or not user_profile.ok_administrare:
        StandardMessages.access_denied(request)
        log_activity(request.user, "ADMINISTRARE_DENIED", "Încercare acces administrare fără permisiune ok_administrare.")
        return redirect('home')
    
    is_superadmin = user_profile and user_profile.role and user_profile.role.name.lower() == 'superadmin'
    log_activity(request.user, "ACCESS_ADMIN_PAGE", f"A accesat pagina de administrare (Superadmin: {is_superadmin}).")

    # Inițializare Formulare
    form_prefixes = {
        'user': UserForm, 'role': RoleForm, 'gestiune': GestiuneForm,
        'tipologie': TipologieProdusForm, 'speciemapping': SpecieMappingManualForm,
        'usermanual': UserManualForm, 'documentrange': DocumentRangeForm
    }
    forms = {prefix: None for prefix in form_prefixes}

    # Preluare Liste
    users = User.objects.select_related('userprofile__gestiune', 'userprofile__role').order_by('username')
    speciemapping_list = SpecieMapping.objects.select_related('tipologie').order_by('specie')
    roles = Role.objects.all().order_by('name')
    gestiuni = Gestiune.objects.all().order_by('nume')
    tipologii = TipologieProdus.objects.all().order_by('nume')
    manual_list = UserManual.objects.all().order_by('-upload_date')[:5]

    # --- MODIFICARE PENTRU PLAJE NUMERE ---
    document_ranges_qs = DocumentRange.objects.none()
    if is_superadmin:
        document_ranges_qs = DocumentRange.objects.select_related('gestiune', 'tipologie').order_by('gestiune__nume',
                                                                                                    'tipologie__nume')
    elif user_profile and user_profile.gestiune:
        # Utilizatorii non-superadmin cu gestiune asignată văd doar plajele lor
        document_ranges_qs = DocumentRange.objects.select_related('gestiune', 'tipologie').filter(
            gestiune=user_profile.gestiune).order_by('tipologie__nume')
    # else: document_ranges_qs rămâne DocumentRange.objects.none() (pt non-superadmin fără gestiune)

    # Adăugăm următorul număr pentru afișare în template-ul de administrare
    document_ranges_list_for_template = []
    for r in document_ranges_qs:
        # Afișarea per-plajă trebuie să calculeze următorul număr STRICT pentru plaja respectivă
        next_number_preview = get_next_document_number_for_range(r)
        document_ranges_list_for_template.append({
            'id': r.id,
            'gestiune': r.gestiune,  # Trimitem obiectul pentru a accesa .nume în template
            'tipologie': r.tipologie,  # Trimitem obiectul pentru a accesa .nume în template
            'numar_inceput': r.numar_inceput,
            'numar_final': r.numar_final,
            'numar_curent': r.numar_curent,
            'urmatorul_numar': next_number_preview,
            'obj': r  # Obiectul original, util pentru link-uri de editare/ștergere care folosesc pk
        })
    # --- SFÂRȘIT MODIFICARE PLAJE NUMERE ---

    activity_logs = ActivityLog.objects.none()
    if is_superadmin:
        activity_logs = ActivityLog.objects.select_related('user').order_by('-timestamp')[:100]

    submitted_form_prefix = None
    if request.method == 'POST':
        print(f"DEBUG ADMIN POST: Data: {request.POST}, Files: {request.FILES}")
        for prefix in form_prefixes.keys():
            if f'submit_{prefix}' in request.POST:
                submitted_form_prefix = prefix
                break
        print(f"DEBUG ADMIN POST: Submitted form prefix: {submitted_form_prefix}")

        if submitted_form_prefix:
            restricted_prefixes = ['user', 'role', 'gestiune', 'tipologie', 'speciemapping', 'usermanual']
            if submitted_form_prefix in restricted_prefixes and not is_superadmin:
                log_activity(request.user, "ADMIN_ACTION_DENIED",
                             f"Încercare acțiune '{submitted_form_prefix}' nepermisă (non-superadmin).")
                StandardMessages.access_denied(request)
                return redirect('administrare')

            FormClass = form_prefixes[submitted_form_prefix]
            form_kwargs = {'prefix': submitted_form_prefix}
            if submitted_form_prefix == 'documentrange':
                form_kwargs['user'] = request.user
            if submitted_form_prefix == 'usermanual':
                forms[submitted_form_prefix] = FormClass(request.POST, request.FILES, **form_kwargs)
            else:
                forms[submitted_form_prefix] = FormClass(request.POST, **form_kwargs)

            form_instance = forms[submitted_form_prefix]

            if form_instance.is_valid():
                try:
                    if submitted_form_prefix == 'user':
                        user = form_instance.save(commit=False)
                        user.set_password(form_instance.cleaned_data['password'])
                        user.save()
                        role = form_instance.cleaned_data.get('role')
                        gestiune_user = form_instance.cleaned_data.get('gestiune')
                        UserProfile.objects.update_or_create(user=user,
                                                             defaults={'role': role, 'gestiune': gestiune_user})
                        log_activity(request.user, "USER_CREATE",
                                     f"Utilizator '{user.username}' creat (Rol: {role}, Gestiune: {gestiune_user}).")
                        StandardMessages.item_created(request, "Utilizatorul")
                        # Important: Nu facem redirect aici pentru user, ca să nu se piardă mesajele de eroare/succes dacă sunt
                        # sau dacă utilizatorul vrea să adauge alt user imediat.
                        # Consideră un redirect la sfârșitul if form_instance.is_valid() dacă e preferat

                    elif submitted_form_prefix == 'documentrange':
                        gestiune_selectata = form_instance.cleaned_data.get('gestiune')
                        if not is_superadmin and user_profile and user_profile.gestiune and gestiune_selectata != user_profile.gestiune:
                            messages.error(request, "Eroare: Nu puteți selecta o altă gestiune.")
                            log_activity(request.user, "RANGE_CREATE_FAIL",
                                         f"Creare plajă eșuată. Motiv: Gestiune invalidă ({gestiune_selectata}).")
                        else:
                            instance = form_instance.save()
                            log_activity(request.user, "RANGE_CREATE",
                                         f"Plajă numere creată (ID: {instance.pk}, Gest: {instance.gestiune}, Tip: {instance.tipologie}).")
                            StandardMessages.item_created(request, "Plaja de numere")
                            return redirect('administrare')  # Redirect pentru a reîmprospăta lista

                    elif submitted_form_prefix == 'usermanual':
                        manual = form_instance.save()
                        log_activity(request.user, "MANUAL_UPLOAD",
                                     f"Manual '{manual.title}' (v{manual.version}) încărcat.")
                        StandardMessages.item_created(request, "Manualul de utilizare")
                        return redirect('administrare')

                    else:
                        instance = form_instance.save()
                        item_name = submitted_form_prefix.capitalize()
                        log_activity(request.user, f"{item_name.upper()}_CREATE",
                                     f"{item_name} '{str(instance)}' creat.")  # Folosim str(instance)
                        StandardMessages.item_created(request, item_name)
                        return redirect('administrare')

                    # După o salvare cu succes (dacă nu s-a făcut redirect), re-inițializăm formularul gol
                    if submitted_form_prefix == 'user':  # Sau alte formulare care nu redirectează imediat
                        form_kwargs_reinit = {'prefix': submitted_form_prefix}
                        if submitted_form_prefix == 'documentrange': form_kwargs_reinit['user'] = request.user
                        forms[submitted_form_prefix] = form_prefixes[submitted_form_prefix](**form_kwargs_reinit)


                except Exception as e_save:
                    error_msg = f"Eroare la salvarea '{submitted_form_prefix}': {e_save}"
                    print(f"ERROR ADMIN SAVE ({submitted_form_prefix}): {error_msg}\n{traceback.format_exc()}")
                    messages.error(request,
                                   f"A apărut o eroare la salvare: {e_save}. Verificați datele (posibil duplicate?).")
                    log_activity(request.user, f"{submitted_form_prefix.upper()}_CREATE_FAIL",
                                 f"Salvare {submitted_form_prefix} eșuată. Eroare: {e_save}")
            else:
                StandardMessages.operation_failed(request, f"crearea/modificarea '{submitted_form_prefix}'",
                                                  "Verifică datele introduse.")
                log_activity(request.user, f"{submitted_form_prefix.upper()}_FORM_INVALID",
                             f"Formular {submitted_form_prefix} invalid. Erori: {form_instance.errors.as_json()}")
                for field, errors in form_instance.errors.items():
                    for error in errors:
                        messages.error(request,
                                       f"Eroare câmp '{form_instance.fields[field].label if field in form_instance.fields else field}': {error}")

    for prefix, FormClass in form_prefixes.items():
        if forms[prefix] is None:
            form_kwargs = {'prefix': prefix}
            if prefix == 'documentrange':
                form_kwargs['user'] = request.user
                initial_data = {}
                if not is_superadmin and user_profile and user_profile.gestiune:
                    initial_data['gestiune'] = user_profile.gestiune
                    form_kwargs['initial'] = initial_data
            forms[prefix] = FormClass(**form_kwargs)

    context = {
        'users': users, 'speciemapping_list': speciemapping_list, 'roles': roles,
        'gestiuni': gestiuni, 'tipologii': tipologii,
        'document_ranges': document_ranges_list_for_template,  # Folosim lista procesată
        'activity_logs': activity_logs, 'manual_list': manual_list,
        'is_superadmin': is_superadmin
    }
    context.update({f'{prefix}_form': forms[prefix] for prefix in form_prefixes})

    return render(request, 'certificat/administrare.html', context)


# --- edit_user_profile (rămâne la fel) ---
@login_required(login_url='/login/')
def edit_user_profile(request, user_id):
    target_user = get_object_or_404(User, id=user_id)
    # Asigurăm-ne că obținem sau creăm profilul dacă lipsește
    user_profile, created = UserProfile.objects.get_or_create(user=target_user)

    # Adăugăm relațiile pentru a avea acces direct la nume și alte detalii
    user_profile = UserProfile.objects.select_related('user', 'role', 'gestiune').get(user=target_user)

    current_user_profile = getattr(request.user, 'userprofile', None)

    # Doar superadmin poate edita
    if not (
            current_user_profile and current_user_profile.role and current_user_profile.role.name.lower() == 'superadmin'):
        log_activity(request.user, "EDIT_PROFILE_DENIED",
                     f"Încercare acces editare profil pt '{target_user.username}' (neautorizat).")
        StandardMessages.access_denied(request)
        return redirect('administrare')

    if request.method == "POST":
        form = UserProfileForm(request.POST, instance=user_profile)
        if form.is_valid():
            form.save()
            log_activity(request.user, "PROFILE_EDIT",
                         f"Profilul utilizatorului '{target_user.username}' a fost actualizat.")
            StandardMessages.item_updated(request, f"Profilul utilizatorului {target_user.username}")
            return redirect('administrare')
        else:
            StandardMessages.operation_failed(request, "actualizarea profilului", "Verifică datele introduse")
            log_activity(request.user, "PROFILE_EDIT_FAIL",
                         f"Actualizare profil eșuată pt '{target_user.username}'. Erori: {form.errors.as_json()}")
    else:
        form = UserProfileForm(instance=user_profile)
        log_activity(request.user, "ACCESS_PROFILE_EDIT_FORM",
                     f"Accesat formular editare profil pt '{target_user.username}'.")

    # Adăugăm print-uri pentru debugging
    print(f"DEBUG - target_user: {target_user.username}, email: {target_user.email}")
    print(f"DEBUG - user_profile.role: {user_profile.role}, user_profile.gestiune: {user_profile.gestiune}")

    return render(request, 'certificat/edit_user_profile.html', {
        'form': form,
        'user_profile': user_profile,
        'target_user': target_user
    })


# --- delete_user (rămâne la fel) ---
@login_required(login_url='/login/')
def delete_user(request, user_id):
    current_user_profile = getattr(request.user, 'userprofile', None)
    # Doar superadmin poate șterge
    if not (current_user_profile and current_user_profile.role and current_user_profile.role.name.lower() == 'superadmin'):
        log_activity(request.user, "DELETE_USER_DENIED", f"Încercare ștergere utilizator ID: {user_id} (neautorizat).")
        StandardMessages.access_denied(request); return redirect('administrare')
    # Nu permite ștergerea propriului cont
    if request.user.id == user_id:
        messages.error(request, "Nu vă puteți șterge propriul cont.")
        log_activity(request.user, "DELETE_USER_FAIL_SELF", "Încercare eșuată ștergere propriu cont.")
        return redirect('administrare')

    try:
        user_to_delete = get_object_or_404(User, id=user_id)
        # Verificare suplimentară - nu șterge alți superadmini? (Opțional)
        # if hasattr(user_to_delete, 'userprofile') and user_to_delete.userprofile.role.name.lower() == 'superadmin':
        #     messages.error(request, "Nu puteți șterge alt utilizator Superadmin.")
        #     log_activity(request.user, "DELETE_USER_FAIL_SUPERADMIN", f"Încercare eșuată ștergere superadmin '{user_to_delete.username}'.")
        #     return redirect('administrare')

        username = user_to_delete.username
        user_to_delete.delete() # Ștergerea userului șterge și profilul (cascade)
        log_activity(request.user, "USER_DELETE", f"Utilizatorul '{username}' (ID: {user_id}) a fost șters.")
        StandardMessages.item_deleted(request, f"Utilizatorul {username}")
    except Http404:
         StandardMessages.item_not_found(request, "Utilizatorul")
         log_activity(request.user, "DELETE_USER_FAIL_NOT_FOUND", f"Încercare ștergere utilizator ID: {user_id} (negăsit).")
    except Exception as e: # Prinde alte erori (ex: protecție ForeignKey)
        StandardMessages.operation_failed(request, "ștergerea utilizatorului", str(e))
        log_activity(request.user, "DELETE_USER_FAIL_ERROR", f"Ștergere utilizator ID: {user_id} eșuată. Eroare: {e}")
    return redirect('administrare')


# --- edit_role ---
@login_required(login_url='/login/')
def edit_role(request, role_id):
    """View pentru editarea rolurilor și sincronizarea permisiunilor cu utilizatorii."""
    role = get_object_or_404(Role, id=role_id)
    user_profile = getattr(request.user, 'userprofile', None)
    
    # Doar superadmin poate edita roluri
    if not (user_profile and user_profile.role and user_profile.role.name.lower() == 'superadmin'):
        StandardMessages.access_denied(request)
        log_activity(request.user, "EDIT_ROLE_DENIED", f"Încercare acces editare rol '{role.name}' (neautorizat).")
        return redirect('administrare')
    
    if request.method == "POST":
        form = RoleForm(request.POST, instance=role)
        if form.is_valid():
            # Salvează rolul cu noile permisiuni
            updated_role = form.save()
            
            # Sincronizează permisiunile cu toți utilizatorii care au acest rol
            users_with_role = UserProfile.objects.filter(role=updated_role)
            updated_count = 0
            
            for user_profile_iter in users_with_role:
                # Copiază toate permisiunile din rol în profil
                user_profile_iter.ok_raportare = updated_role.ok_raportare
                user_profile_iter.ok_administrare = updated_role.ok_administrare
                user_profile_iter.ok_aviz = updated_role.ok_aviz
                user_profile_iter.ok_plaje = updated_role.ok_plaje
                user_profile_iter.ok_gestiuni = updated_role.ok_gestiuni
                user_profile_iter.ok_tipologii = updated_role.ok_tipologii
                user_profile_iter.ok_doc_generate = updated_role.ok_doc_generate
                user_profile_iter.vede_toate_documentele = updated_role.vede_toate_documentele
                user_profile_iter.save()
                updated_count += 1
            
            log_activity(
                request.user, 
                "ROLE_UPDATED", 
                f"Rolul '{role.name}' actualizat. Permisiuni sincronizate cu {updated_count} utilizatori."
            )
            StandardMessages.operation_success(
                request, 
                f"Rolul '{role.name}' a fost actualizat și permisiunile au fost sincronizate cu {updated_count} utilizatori."
            )
            return redirect('administrare')
        else:
            StandardMessages.operation_failed(request, "actualizarea rolului", "Verifică datele introduse")
            log_activity(
                request.user, 
                "ROLE_UPDATE_FAIL", 
                f"Actualizare rol '{role.name}' eșuată. Erori: {form.errors.as_json()}"
            )
    else:
        form = RoleForm(instance=role)
        log_activity(request.user, "ACCESS_EDIT_ROLE", f"Accesat formular editare rol '{role.name}'.")
    
    # Numără câți utilizatori au acest rol
    users_count = UserProfile.objects.filter(role=role).count()
    
    return render(request, 'certificat/edit_role.html', {
        'form': form,
        'role': role,
        'users_count': users_count
    })


# --- DocumentRange operations (List, Delete, Edit) ---
@login_required(login_url='/login/')
def my_document_ranges(request):
    user_profile = getattr(request.user, 'userprofile', None)
    
    # Verifică permisiunea ok_plaje
    if not user_profile or not user_profile.ok_plaje:
        StandardMessages.access_denied(request)
        log_activity(request.user, "PLAJE_DENIED", "Încercare acces plaje numere fără permisiune ok_plaje.")
        return redirect('home')
    
    log_activity(request.user, "ACCESS_RANGE_LIST", "A accesat lista de plaje numere.")
    is_superadmin = user_profile and user_profile.role and user_profile.role.name.lower() == 'superadmin'

    base_ranges_qs = DocumentRange.objects.none()
    if is_superadmin:
        base_ranges_qs = DocumentRange.objects.select_related('gestiune', 'tipologie').order_by('gestiune__nume', 'tipologie__nume')
    elif user_profile and user_profile.gestiune:
        base_ranges_qs = DocumentRange.objects.select_related('gestiune', 'tipologie').filter(gestiune=user_profile.gestiune).order_by('tipologie__nume')
    else:
        if not is_superadmin: messages.warning(request, "Nu aveți o gestiune asignată pentru a vedea plaje de numere.")

    # Pregătim lista de afișat cu informația extra
    ranges_with_next_number = []
    for r in base_ranges_qs:
        # Afișare per-plajă pe această listă
        next_number_preview = get_next_document_number_for_range(r)
        ranges_with_next_number.append({
            'id': r.id, # pk
            'gestiune_nume': r.gestiune.nume,
            'tipologie_nume': r.tipologie.nume,
            'numar_inceput': r.numar_inceput,
            'numar_final': r.numar_final,
            'numar_curent': r.numar_curent,
            'urmatorul_numar': next_number_preview
        })

    context = {'ranges_list': ranges_with_next_number, 'is_superadmin': is_superadmin} # Am schimbat 'ranges' in 'ranges_list'
    return render(request, 'certificat/documentrange_list.html', context)


@require_POST # Folosim POST pentru acțiuni de ștergere
@login_required(login_url='/login/')
def delete_document_range(request, pk):
    user_profile = getattr(request.user, 'userprofile', None)
    
    # Verifică permisiunea ok_plaje
    if not user_profile or not user_profile.ok_plaje:
        StandardMessages.access_denied(request)
        log_activity(request.user, "DELETE_RANGE_DENIED", f"Încercare ștergere plajă ID: {pk} (lipsă permisiune ok_plaje).")
        return redirect('documentrange_list')
    
    try:
        doc_range = get_object_or_404(DocumentRange, pk=pk)
        is_superadmin = user_profile and user_profile.role and user_profile.role.name.lower() == 'superadmin'

        # Verificare permisiune (gestiune)
        can_delete = is_superadmin or (user_profile and doc_range.gestiune == user_profile.gestiune)
        if not can_delete:
            log_activity(request.user, "DELETE_RANGE_DENIED", f"Încercare ștergere plajă ID: {pk} (neautorizat/altă gestiune).")
            StandardMessages.access_denied(request)
            return redirect('documentrange_list')

        log_details = f"Plajă numere ștearsă (ID: {doc_range.pk}, Gest: {doc_range.gestiune}, Tip: {doc_range.tipologie}, Range: {doc_range.numar_inceput}-{doc_range.numar_final}, Curent: {doc_range.numar_curent})."
        doc_range.delete()
        log_activity(request.user, "RANGE_DELETE", log_details)
        StandardMessages.item_deleted(request, "Plaja de numere")
    except Http404:
         StandardMessages.item_not_found(request, "Plaja de numere")
         log_activity(request.user, "DELETE_RANGE_FAIL_NOT_FOUND", f"Încercare ștergere plajă ID: {pk} (negăsit).")
    except Exception as e:
        StandardMessages.operation_failed(request, "ștergerea plajei de numere", str(e))
        log_activity(request.user, "DELETE_RANGE_FAIL_ERROR", f"Ștergere plajă ID: {pk} eșuată. Eroare: {e}")

    return redirect('documentrange_list')


@login_required(login_url='/login/')
def edit_document_range(request, pk):
    user_profile = getattr(request.user, 'userprofile', None)
    
    # Verifică permisiunea ok_plaje
    if not user_profile or not user_profile.ok_plaje:
        StandardMessages.access_denied(request)
        log_activity(request.user, "EDIT_RANGE_DENIED", f"Încercare acces editare plajă ID: {pk} (lipsă permisiune ok_plaje).")
        return redirect('documentrange_list')
    
    doc_range = get_object_or_404(DocumentRange, pk=pk)
    is_superadmin = user_profile and user_profile.role and user_profile.role.name.lower() == 'superadmin'

    # Verificare permisiune (gestiune)
    can_edit = is_superadmin or (user_profile and doc_range.gestiune == user_profile.gestiune)
    if not can_edit:
        log_activity(request.user, "EDIT_RANGE_DENIED", f"Încercare acces editare plajă ID: {pk} (neautorizat/altă gestiune).")
        StandardMessages.access_denied(request)
        return redirect('documentrange_list')

    initial_data_str = f"Început: {doc_range.numar_inceput}, Final: {doc_range.numar_final}, Curent: {doc_range.numar_curent}"

    if request.method == "POST":
        # Trecem user-ul la formular pentru validare gestiune
        form = DocumentRangeForm(request.POST, instance=doc_range, user=request.user)
        if form.is_valid():
            try:
                updated_range = form.save()
                final_data_str = f"Început: {updated_range.numar_inceput}, Final: {updated_range.numar_final}, Curent: {updated_range.numar_curent}"
                log_activity(request.user, "RANGE_EDIT", f"Plajă numere (ID: {pk}) modificată. Inițial: [{initial_data_str}] -> Final: [{final_data_str}].")
                StandardMessages.item_updated(request, "Plaja de numere")
                return redirect('documentrange_list')
            except Exception as e_save:
                 StandardMessages.operation_failed(request, "actualizarea plajei de numere", str(e_save))
                 log_activity(request.user, "EDIT_RANGE_FAIL_SAVE", f"Editare plajă ID: {pk} eșuată la salvare. Eroare: {e_save}")
        else:
            StandardMessages.operation_failed(request, "actualizarea plajei de numere", "Verifică datele introduse.")
            log_activity(request.user, "EDIT_RANGE_FAIL_INVALID", f"Editare plajă ID: {pk} eșuată. Formular invalid. Erori: {form.errors.as_json()}")
    else: # GET
        form = DocumentRangeForm(instance=doc_range, user=request.user)
        log_activity(request.user, "ACCESS_EDIT_RANGE_FORM", f"A accesat formular editare plajă ID: {pk}.")

    return render(request, 'certificat/edit_document_range.html', {'form': form, 'doc_range': doc_range})


# --- Gestiune operations (Doar Superadmin) ---
@login_required(login_url='/login/')
def list_gestiuni(request):
    user_profile = getattr(request.user, 'userprofile', None)
    
    # Verifică permisiunea ok_gestiuni
    if not user_profile or not user_profile.ok_gestiuni:
        StandardMessages.access_denied(request)
        log_activity(request.user, "ACCESS_GESTIUNI_DENIED", "Acces neautorizat la lista gestiuni (lipsă permisiune ok_gestiuni).")
        return redirect('administrare')
    
    gestiuni = Gestiune.objects.all().order_by('nume')
    log_activity(request.user, "ACCESS_GESTIUNI_LIST", "A accesat lista gestiuni.")
    return render(request, 'certificat/gestiuni_list.html', {'gestiuni': gestiuni})

@require_POST
@login_required(login_url='/login/')
def delete_gestiune(request, pk):
    user_profile = getattr(request.user, 'userprofile', None)
    
    # Verifică permisiunea ok_gestiuni
    if not user_profile or not user_profile.ok_gestiuni:
        StandardMessages.access_denied(request)
        log_activity(request.user, "DELETE_GESTIUNE_DENIED", f"Încercare ștergere gestiune ID: {pk} (lipsă permisiune ok_gestiuni).")
        return redirect('gestiuni_list')
    try:
        gestiune = get_object_or_404(Gestiune, pk=pk)
        nume_gestiune = gestiune.nume
        # Verifică dacă gestiunea e folosită înainte de a șterge (opțional, dar recomandat)
        if UserProfile.objects.filter(gestiune=gestiune).exists() or DocumentRange.objects.filter(gestiune=gestiune).exists():
             messages.error(request, f"Gestiunea '{nume_gestiune}' nu poate fi ștearsă deoarece este utilizată de profiluri sau plaje de numere.")
             log_activity(request.user, "DELETE_GESTIUNE_FAIL_USED", f"Ștergere gestiune '{nume_gestiune}' (ID: {pk}) eșuată (în uz).")
             return redirect('gestiuni_list')

        gestiune.delete()
        log_activity(request.user, "GESTIUNE_DELETE", f"Gestiunea '{nume_gestiune}' (ID: {pk}) a fost ștearsă.")
        StandardMessages.item_deleted(request, "Gestiunea")
    except Http404:
         StandardMessages.item_not_found(request, "Gestiunea")
         log_activity(request.user, "DELETE_GESTIUNE_FAIL_NOT_FOUND", f"Încercare ștergere gestiune ID: {pk} (negăsit).")
    except Exception as e:
        StandardMessages.operation_failed(request, "ștergerea gestiunii", str(e))
        log_activity(request.user, "DELETE_GESTIUNE_FAIL_ERROR", f"Ștergere gestiune ID: {pk} eșuată. Eroare: {e}")
    return redirect('gestiuni_list')


@login_required(login_url='/login/')
def edit_gestiune(request, pk):
    user_profile = getattr(request.user, 'userprofile', None)
    
    # Verifică permisiunea ok_gestiuni
    if not user_profile or not user_profile.ok_gestiuni:
        StandardMessages.access_denied(request)
        log_activity(request.user, "EDIT_GESTIUNE_DENIED", f"Încercare acces editare gestiune ID: {pk} (lipsă permisiune ok_gestiuni).")
        return redirect('gestiuni_list')
    gestiune = get_object_or_404(Gestiune, pk=pk)
    if request.method == "POST":
        form = GestiuneForm(request.POST, instance=gestiune)
        if form.is_valid():
            form.save()
            log_activity(request.user, "GESTIUNE_EDIT", f"Gestiunea '{gestiune.nume}' (ID: {pk}) a fost actualizată.")
            StandardMessages.item_updated(request, "Gestiunea"); return redirect('gestiuni_list')
        else:
             StandardMessages.operation_failed(request, "actualizarea gestiunii", "Verifică datele introduse")
             log_activity(request.user, "EDIT_GESTIUNE_FAIL_INVALID", f"Editare gestiune ID: {pk} eșuată. Erori: {form.errors.as_json()}")
    else:
         form = GestiuneForm(instance=gestiune)
         log_activity(request.user, "ACCESS_EDIT_GESTIUNE_FORM", f"Accesat form editare gestiune ID: {pk}.")
    return render(request, 'certificat/edit_gestiune.html', {'form': form, 'gestiune': gestiune})


# --- Tipologie operations (Doar Superadmin) ---
@login_required(login_url='/login/')
def list_tipologii(request):
    user_profile = getattr(request.user, 'userprofile', None)
    
    # Verifică permisiunea ok_tipologii
    if not user_profile or not user_profile.ok_tipologii:
        StandardMessages.access_denied(request)
        log_activity(request.user, "ACCESS_TIPOLOGII_DENIED", "Acces neautorizat la lista tipologii (lipsă permisiune ok_tipologii).")
        return redirect('administrare')
    
    tipologii = TipologieProdus.objects.all().order_by('nume')
    log_activity(request.user, "ACCESS_TIPOLOGII_LIST", "A accesat lista tipologii.")
    context = {'tipologii': tipologii}
    return render(request, 'certificat/tipologii_list.html', context)

@require_POST
@login_required(login_url='/login/')
def delete_tipologie(request, pk):
    user_profile = getattr(request.user, 'userprofile', None)
    
    # Verifică permisiunea ok_tipologii
    if not user_profile or not user_profile.ok_tipologii:
        StandardMessages.access_denied(request)
        log_activity(request.user, "DELETE_TIPOLOGIE_DENIED", f"Încercare ștergere tipologie ID: {pk} (lipsă permisiune ok_tipologii).")
        return redirect('tipologii_list')
    try:
        tipologie = get_object_or_404(TipologieProdus, pk=pk)
        nume_tipologie = tipologie.nume
        # Verificare utilizare (opțional)
        if SpecieMapping.objects.filter(tipologie=tipologie).exists() or DocumentRange.objects.filter(tipologie=tipologie).exists():
             messages.error(request, f"Tipologia '{nume_tipologie}' nu poate fi ștearsă deoarece este utilizată în mapări de specii sau plaje de numere.")
             log_activity(request.user, "DELETE_TIPOLOGIE_FAIL_USED", f"Ștergere tipologie '{nume_tipologie}' (ID: {pk}) eșuată (în uz).")
             return redirect('tipologii_list')

        tipologie.delete()
        log_activity(request.user, "TIPOLOGIE_DELETE", f"Tipologia '{nume_tipologie}' (ID: {pk}) a fost ștearsă.")
        StandardMessages.item_deleted(request, "Tipologia")
    except Http404:
        StandardMessages.item_not_found(request, "Tipologia")
        log_activity(request.user, "DELETE_TIPOLOGIE_FAIL_NOT_FOUND", f"Încercare ștergere tipologie ID: {pk} (negăsit).")
    except Exception as e:
        StandardMessages.operation_failed(request, "ștergerea tipologiei", str(e))
        log_activity(request.user, "DELETE_TIPOLOGIE_FAIL_ERROR", f"Ștergere tipologie ID: {pk} eșuată. Eroare: {e}")
    return redirect('tipologii_list')


# --- Mapping operations (Editare, Update automat) ---
@login_required(login_url='/login/')
def edit_speciemapping(request, pk):
    user_profile = getattr(request.user, 'userprofile', None)
    if not (user_profile and user_profile.role and user_profile.role.name.lower() == 'superadmin'):
         log_activity(request.user, "EDIT_SPECIEMAP_DENIED", f"Încercare acces editare mapare ID: {pk} (neautorizat).")
         StandardMessages.access_denied(request); return redirect('administrare') # Redirect la admin general
    mapping = get_object_or_404(SpecieMapping, pk=pk)
    if request.method == 'POST':
        # Folosim forma simplă SpecieMappingForm aici, nu cea manuală
        form = SpecieMappingForm(request.POST, instance=mapping)
        if form.is_valid():
            updated_mapping = form.save()
            log_activity(request.user, "SPECIEMAP_EDIT", f"Mapare specie '{updated_mapping.specie}' (ID: {pk}) actualizată -> '{updated_mapping.tipologie}'.")
            StandardMessages.item_updated(request, "Mapping-ul pentru specie")
            return redirect('administrare') # Redirect la admin general unde e lista
        else:
             StandardMessages.operation_failed(request, "actualizarea mapping-ului", "Verifică datele introduse")
             log_activity(request.user, "EDIT_SPECIEMAP_FAIL_INVALID", f"Editare mapare ID: {pk} eșuată. Erori: {form.errors.as_json()}")
    else:
         form = SpecieMappingForm(instance=mapping)
         log_activity(request.user, "ACCESS_EDIT_SPECIEMAP_FORM", f"Accesat formular editare mapare ID: {pk}.")
    # Probabil nu avem un template dedicat 'edit_speciemapping.html'?
    # Poate fi integrat în pagina 'administrare' sau necesita un template separat.
    # Să presupunem că există un template:
    return render(request, 'certificat/edit_speciemapping.html', {'form': form, 'mapping': mapping})


@login_required(login_url='/login/')
def update_speciemapping(request):
    user_profile = getattr(request.user, 'userprofile', None)
    if not (user_profile and user_profile.role and user_profile.role.name.lower() == 'superadmin'):
         log_activity(request.user, "UPDATE_SPECIEMAP_DENIED", "Acces neautorizat la update mapare specii.")
         StandardMessages.access_denied(request); return redirect('administrare')

    new_species = []
    try:
        json_url = "https://moldova.info-media.ro/surse/WebFormExportDate.aspx?token=wme_avize_serii_cant"
        response = requests.get(json_url, timeout=15); response.raise_for_status(); data_list = response.json()
        species_in_json = {item.get("SPECIE","").strip() for item in data_list if item.get("SPECIE","").strip()}
        existing_species = {s.strip() for s in SpecieMapping.objects.values_list("specie", flat=True)}
        new_species = sorted(list(species_in_json - existing_species))
    except requests.exceptions.RequestException as e_req:
         StandardMessages.operation_failed(request, "preluarea datelor JSON", f"Eroare de rețea: {str(e_req)}")
         log_activity(request.user, "UPDATE_SPECIEMAP_FAIL_JSON", f"Update mapare eșuat. Eroare JSON API: {e_req}")
         return redirect('administrare')
    except Exception as e: # Alte erori (JSONDecode, etc.)
        StandardMessages.operation_failed(request, "procesarea datelor", str(e))
        log_activity(request.user, "UPDATE_SPECIEMAP_FAIL_PROCESS", f"Update mapare eșuat. Eroare procesare: {e}")
        return redirect('administrare')

    if not new_species:
        StandardMessages.info_message(request, "Nu există specii noi de mapat din sursa de date.")
        log_activity(request.user, "UPDATE_SPECIEMAP_NO_NEW", "Update mapare: Nicio specie nouă găsită.")
        return redirect('administrare')

    # Folosim forma SpecieMappingForm care permite alegerea tipologiei
    SpecieMappingFormSet = modelformset_factory(SpecieMapping, form=SpecieMappingForm, extra=len(new_species), can_delete=False)

    if request.method == "POST":
        formset = SpecieMappingFormSet(request.POST, queryset=SpecieMapping.objects.none(), prefix='mapping') # Adăugăm prefix
        if formset.is_valid():
            try:
                instances = formset.save()
                log_activity(request.user, "SPECIEMAP_UPDATE_SUCCESS", f"Import specii noi finalizat. {len(instances)} mapări adăugate.")
                StandardMessages.operation_success(request, f"{len(instances)} specii noi au fost mapate cu succes!")
                return redirect("administrare")
            except Exception as e_save:
                 StandardMessages.operation_failed(request, "salvarea mapărilor", str(e_save))
                 log_activity(request.user, "UPDATE_SPECIEMAP_FAIL_SAVE", f"Salvare mapări noi eșuată. Eroare: {e_save}")
                 # Re-rendăm formsetul cu erori
        else:
             StandardMessages.operation_failed(request, "maparea speciilor", "Verifică datele introduse (tipologie obligatorie).")
             log_activity(request.user, "UPDATE_SPECIEMAP_FAIL_INVALID", f"Formset mapare invalid. Erori: {formset.errors.as_json()}")
             # Re-rendăm formsetul cu erori
    else: # GET
        initial_data = [{"specie": specie} for specie in new_species]
        formset = SpecieMappingFormSet(queryset=SpecieMapping.objects.none(), initial=initial_data, prefix='mapping') # Adăugăm prefix
        log_activity(request.user, "ACCESS_UPDATE_SPECIEMAP_FORM", f"Accesat formular update mapare. Specii noi: {len(new_species)}")

    return render(request, "certificat/update_speciemapping.html", {"formset": formset, "prefix": 'mapping'})


# --- Generated Documents List ---
@login_required(login_url='/login/')
def generated_documents_list(request):
    """ Afișează lista de documente generate cu filtre și statistici. """
    user_profile = getattr(request.user, 'userprofile', None)
    
    # Verifică permisiunea ok_doc_generate
    if not user_profile or not user_profile.ok_doc_generate:
        StandardMessages.access_denied(request)
        log_activity(request.user, "DOC_LIST_DENIED", "Încercare acces listă documente fără permisiune ok_doc_generate.")
        return redirect('home')
    
    is_superadmin = user_profile and user_profile.role and user_profile.role.name.lower() == 'superadmin'
    is_admin = user_profile and user_profile.role and user_profile.role.name.lower() == 'admin'
    is_admin_or_super = is_admin or is_superadmin
    log_activity(request.user, "ACCESS_DOC_LIST", f"A accesat lista documente (Admin/Super: {is_admin_or_super}).")

    base_qs = GeneratedDocument.objects.select_related('generated_by', 'deleted_by')  # Adăugat deleted_by la select_related

    # Verificare dacă utilizatorul are dreptul să vadă toate documentele
    vede_toate = user_profile and user_profile.vede_toate_documentele

    # MODIFICARE: Utilizatorii normali văd TOATE documentele din gestiunea lor (nu doar cele generate de ei)
    # Filtrarea se face prin prefixele de serii ale gestiunii (mai jos), nu prin generated_by
    # Doar admin/superadmin fără flag "vede_toate" sunt restricționați la propriile documente
    if not vede_toate and is_admin_or_super:
        # Admin/superadmin fără flag "vede toate" vede doar documentele generate de el
        base_qs = base_qs.filter(generated_by=request.user)
    # Pentru utilizatori normali (non-admin), NU filtrăm pe generated_by
    # Ei vor vedea toate documentele din gestiunea lor prin filtrarea pe prefixe (mai jos)

    # Modificare: pentru utilizatorii non-admin/superadmin, afișăm DOAR documentele emise (finalizate)
    # și DOAR cele ale căror serii aparțin plajelor gestiunii utilizatorului (după prefixul din plajă).
    # Pentru admin/superadmin, putem activa același filtru prin toggle (view_as_user=yes) și alegerea unei gestiuni.
    view_as_user = False
    selected_sim_gestiune = None
    if is_admin_or_super:
        view_as_user = request.GET.get("view_as_user", "no") == "yes"
        sim_gestiune_id = request.GET.get("sim_gestiune_id")
        if view_as_user and sim_gestiune_id:
            try:
                selected_sim_gestiune = Gestiune.objects.filter(pk=int(sim_gestiune_id)).first()
            except (ValueError, TypeError):
                selected_sim_gestiune = None
# 
    if not is_admin_or_super or view_as_user:
#         base_qs = base_qs.filter(status='finalizat')
        # Determină gestiunea pentru care aplicăm filtrarea pe plaje
        effective_gestiune = None
        if is_admin_or_super and view_as_user:
            effective_gestiune = selected_sim_gestiune
        else:
            effective_gestiune = user_profile.gestiune if user_profile else None

        # Dacă nu avem o gestiune, nu afișăm nimic
        if effective_gestiune:
            # Construim lista de prefixe din plajele de numere ale gestiunii
            ranges_qs = DocumentRange.objects.filter(gestiune=effective_gestiune).only('numar_inceput')
            prefixes = []
            pattern = re.compile(r'^(.*?)(\d+)$')
            for r in ranges_qs:
                start_val = r.numar_inceput or ''
                m = pattern.match(start_val)
                if m:
                    prefix = m.group(1)
                    if prefix and prefix not in prefixes:
                        prefixes.append(prefix)

            if prefixes:
                prefix_q = Q()
                for pref in prefixes:
                    prefix_q |= Q(document_series__startswith=pref)
                base_qs = base_qs.filter(prefix_q)
            else:
                # Fără plaje definite => nu afișăm documente
                base_qs = base_qs.none()
        else:
            base_qs = base_qs.none()

    # Filtru pentru a afișa sau nu documentele șterse
    include_deleted = request.GET.get("include_deleted", "yes") == "yes"  # Default este "yes"
    if not include_deleted:
        base_qs = base_qs.filter(is_deleted=False)

    # Aplicăm filtrele GET
    aviz_filter = request.GET.get("aviz", "").strip()
    serie_filter = request.GET.get("serie", "").strip()  # Filtru pe seria documentului
    partener_filter = request.GET.get("partener", "").strip()
    lot_filter = request.GET.get("lot", "").strip()  # Filtru pe seria din JSON (lot)
    articol_filter = request.GET.get("articol", "").strip()  # Filtru pe articol/soi/specie din JSON

    # Construim query-ul filtrat
    qs = base_qs.all()  # Pornim cu toate (filtrate pe user dacă e cazul)
    if aviz_filter:
        qs = qs.filter(aviz_number__icontains=aviz_filter)
    if serie_filter:
        qs = qs.filter(document_series__icontains=serie_filter)
    if partener_filter:
        qs = qs.filter(partner__icontains=partener_filter)

    # Filtrare avansată (JSON) - aplicată doar dacă există lot_filter sau articol_filter
    if lot_filter or articol_filter:
        matching_doc_ids = set() # Folosim set pentru eficiență
        # Optimizare: preluăm doar ID și JSON pentru documentele deja filtrate
        docs_to_check_json = qs.filter(context_json__isnull=False).values('id', 'context_json')

        for doc_data in docs_to_check_json:
            try:
                context_data = json.loads(doc_data['context_json'])
                doc_matches = False # Flag dacă documentul curent se potrivește

                # Iterăm prin pozițiile din context
                for i in range(1, 4):
                    position_key = f'pozitie{i}'
                    if position_key in context_data and isinstance(context_data[position_key], dict):
                        position_data = context_data[position_key]

                        # Verificăm potrivirea filtrelor pentru poziția curentă
                        lot_match_pos = (not lot_filter) or (lot_filter.lower() in str(position_data.get('serie', '')).lower())
                        articol_match_pos = (not articol_filter)
                        if not articol_match_pos:
                             for field in ['articol', 'ARTICOL', 'soi', 'specia']:
                                 if articol_filter.lower() in str(position_data.get(field, '')).lower():
                                     articol_match_pos = True; break # Găsit, ieșim din bucla field

                        # Dacă AMBELE filtre (lot și articol) se potrivesc pentru ACEASTĂ poziție,
                        # atunci întregul document se potrivește și putem trece la următorul document.
                        if lot_match_pos and articol_match_pos:
                            doc_matches = True
                            break # Ieșim din bucla pozițiilor (i)

                # Dacă documentul s-a potrivit (în oricare poziție), îl adăugăm
                if doc_matches:
                    matching_doc_ids.add(doc_data['id'])

            except (json.JSONDecodeError, TypeError, AttributeError) as e:
                print(f"Eroare la procesarea JSON pentru doc ID {doc_data['id']} în filtrare: {e}")
                continue # Ignorăm documentul cu JSON invalid

        # Filtrăm queryset-ul final după ID-urile găsite
        qs = qs.filter(id__in=list(matching_doc_ids))
        # Dacă nu s-a găsit nimic și s-a aplicat filtru JSON, qs va fi gol


    # Paginare
    paginator = Paginator(qs.order_by("-created_at"), 25) # 25 documente pe pagină
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)


    # Statistici - calculate pe baza query-ului DE BAZĂ (filtrat pe user sau global)
    all_aviz_numbers = base_qs.values_list('aviz_number', flat=True).distinct()
    total_avize = len(all_aviz_numbers)
    avize_finalizate = 0
    avize_procesare = 0
    # Optimizare: facem un singur query pentru statusuri
    aviz_statuses = base_qs.values('aviz_number').annotate(
        has_finalizat=Count('id', filter=Q(status='finalizat')),
        has_procesare=Count('id', filter=Q(status='in procesare')),
        total_parts=Count('id')
    )
    for aviz_stat in aviz_statuses:
        # Considerăm finalizat dacă TOATE părțile sunt finalizate
        if aviz_stat['has_finalizat'] == aviz_stat['total_parts']:
            avize_finalizate += 1
        # Considerăm în procesare dacă MĂCAR O parte e în procesare
        elif aviz_stat['has_procesare'] > 0:
             avize_procesare += 1
        # Altfel, ar putea fi toate 'salvat' sau alte statusuri - nu le contorizăm separat aici

    stats_source = "sistem"
    if not is_admin_or_super:
        stats_source = "gestiunea ta"  # Modificat: utilizatorii văd documente din gestiunea lor, nu doar ale lor
    elif view_as_user:
        stats_source = f"gestiunea selectată"

    # Adăugăm filtrele GET în context pentru a le menține în paginare/formular
    # Listă gestiuni pentru toggle-ul admin/superadmin
    gestiuni_list = None
    if is_admin_or_super:
        try:
            gestiuni_list = list(Gestiune.objects.all().order_by('nume'))
        except Exception:
            gestiuni_list = []

    context = {
        "page_obj": page_obj, # Obiectul paginii pentru template
        "total_avize": total_avize,
        "avize_finalizate": avize_finalizate,
        "avize_procesare": avize_procesare,
        "stats_source": stats_source,
        "is_superadmin": is_superadmin,
        "is_admin_or_super": is_admin_or_super,
        "view_as_user": view_as_user,
        "sim_gestiune_id": (selected_sim_gestiune.id if selected_sim_gestiune else None),
        "gestiuni": gestiuni_list,
        # Filtrele curente
        "aviz_filter": aviz_filter,
        "serie_filter": serie_filter,
        "partener_filter": partener_filter,
        "lot_filter": lot_filter,
        "articol_filter": articol_filter,
    }
    return render(request, "certificat/generated_documents_list.html", context)


# --- Document Details API ---
@login_required(login_url='/login/')
def document_details(request, aviz_number):
    """ API endpoint to fetch item details for a specific document part (by doc_id). """
    doc_id_str = request.GET.get('doc_id')
    if not doc_id_str:
        return JsonResponse({"error": "Parametrul 'doc_id' este obligatoriu."}, status=400)

    try:
        doc_id = int(doc_id_str)
    except ValueError:
        return JsonResponse({"error": "ID document invalid."}, status=400)

    try:
        doc = get_object_or_404(
            GeneratedDocument.objects.select_related('generated_by__userprofile__role'),
            id=doc_id,
            aviz_number=aviz_number # Verificare dublă
        )

        # Verificare Permisiuni
        user_profile = getattr(request.user, 'userprofile', None)
        is_owner = doc.generated_by_id == request.user.id
        is_admin_or_super = user_profile and user_profile.role and user_profile.role.name.lower() in ['admin', 'superadmin']

        if not (is_owner or is_admin_or_super):
            log_activity(request.user, "VIEW_DOC_DETAILS_DENIED", f"Acces neautorizat detalii doc ID: {doc_id}.")
            return JsonResponse({"error": "Acces nepermis."}, status=403)

        # Procesare JSON
        items = []
        if not doc.context_json:
            return JsonResponse({"items": [], "message": "Nu există detalii salvate (context JSON)."}, status=200)

        try:
            context_dict = json.loads(doc.context_json)
            if not isinstance(context_dict, dict):
                 raise json.JSONDecodeError("Contextul JSON nu este un dicționar.", doc.context_json, 0)

            # Extrage itemii din poziții
            for i in range(1, 4):
                pos_key = f"pozitie{i}"
                pos_data = context_dict.get(pos_key)
                if isinstance(pos_data, dict) and pos_data: # Verificăm că e dicționar și nu e gol
                     # Adăugăm câmpurile relevante, folosind default '-'
                     item = {
                         "specie": pos_data.get("specia", "-"),
                         "soi": pos_data.get("soi", pos_data.get("articol", "-")), # Folosim articol ca fallback pt soi
                         "articol": pos_data.get("articol", "-"), # Articol separat
                         "cantitate": pos_data.get("cantitate", 0), # Default 0 pt cantitate
                         "um": pos_data.get("um", "-"),
                         "serie": pos_data.get("serie", "-") # Adăugăm și seria (lotul)
                     }
                     items.append(item)

            if not items:
                return JsonResponse({"items": [], "message": "Nu s-au găsit articole în detaliile acestei părți."}, status=200)
            else:
                log_activity(request.user, "VIEW_DOC_DETAILS_SUCCESS", f"Vizualizat detalii doc ID: {doc_id}.")
                return JsonResponse({"items": items}, status=200)

        except json.JSONDecodeError as json_err:
            log_activity(request.user, "VIEW_DOC_DETAILS_JSON_ERROR", f"Eroare parsare JSON detalii doc ID: {doc_id}. Eroare: {json_err}")
            print(f"ERROR: JSON Decode Error for doc {doc_id}: {json_err}")
            return JsonResponse({"error": "Detaliile salvate sunt corupte."}, status=500)

    except Http404:
        return JsonResponse({"error": "Documentul specificat nu a fost găsit."}, status=404)
    except Exception as e:
        print(f"--- Unhandled Exception in document_details (doc_id: {doc_id_str}, aviz: {aviz_number}) ---")
        traceback.print_exc()
        log_activity(request.user, "VIEW_DOC_DETAILS_ERROR", f"Eroare server detalii doc ID: {doc_id_str}. Eroare: {e}")
        return JsonResponse({"error": "Eroare internă la server."}, status=500)


# --- Manual Views ---
@login_required(login_url='/login/')
def view_manual(request):
    """ Afișează cel mai recent manual activ. """
    manual = UserManual.objects.filter(is_active=True).order_by('-upload_date').first()
    if manual:
        log_activity(request.user, "ACCESS_MANUAL", f"A accesat manualul de utilizare (v{manual.version}).")
    else:
         log_activity(request.user, "ACCESS_MANUAL_NOT_FOUND", "A încercat să acceseze manualul (negăsit/inactiv).")
         messages.info(request, "Momentan nu este disponibil niciun manual de utilizare activ.")
    return render(request, "certificat/manual.html", {"manual": manual})


@login_required(login_url='/login/')
def download_manual(request, manual_id=None):
    """ Descarcă un manual specific sau cel mai recent. """
    manual_to_download = None
    try:
        if manual_id:
            manual_to_download = get_object_or_404(UserManual, pk=manual_id, is_active=True)
        else:
            manual_to_download = UserManual.objects.filter(is_active=True).order_by('-upload_date').first()

        if not manual_to_download:
            messages.error(request, "Nu există un manual de utilizare activ disponibil pentru descărcare.")
            log_activity(request.user, "DOWNLOAD_MANUAL_FAIL_NOT_FOUND", f"Încercare descărcare manual (ID: {manual_id or 'latest'}) - negăsit/inactiv.")
            # Redirect la pagina manualului sau home?
            return redirect('view_manual')

        # Verificăm dacă fișierul există fizic
        if not manual_to_download.file or not default_storage.exists(manual_to_download.file.name):
             messages.error(request, "Fișierul manualului lipsește de pe server.")
             log_activity(request.user, "DOWNLOAD_MANUAL_FAIL_MISSING_FILE", f"Încercare descărcare manual (ID: {manual_to_download.id}) - fișier lipsă: {manual_to_download.file.name}")
             return redirect('view_manual')


        log_activity(request.user, "DOWNLOAD_MANUAL", f"A descărcat manualul '{manual_to_download.title}' (v{manual_to_download.version}).")

        # Folosim FileResponse pentru fișiere mari și setăm content_type corect
        from django.http import FileResponse
        response = FileResponse(manual_to_download.file.open('rb'), # Deschidem în mod binar
                                content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        # Setăm numele fișierului pentru descărcare
        filename = f"Manual_Utilizare_CertApp_v{manual_to_download.version}.docx"
        # Asigurăm compatibilitatea numelui de fișier
        response['Content-Disposition'] = f'attachment; filename="{filename}"; filename*=UTF-8\'\'{urlencode({"filename": filename}).split("=")[1]}'
        return response

    except Http404:
         messages.error(request, "Manualul specificat nu a fost găsit sau nu este activ.")
         log_activity(request.user, "DOWNLOAD_MANUAL_FAIL_NOT_FOUND", f"Încercare descărcare manual ID: {manual_id} (404).")
         return redirect('view_manual')
    except Exception as e:
         messages.error(request, f"A apărut o eroare la descărcarea manualului: {e}")
         log_activity(request.user, "DOWNLOAD_MANUAL_FAIL_ERROR", f"Eroare descărcare manual (ID: {manual_id or 'latest'}). Eroare: {e}")
         print(f"ERROR downloading manual: {e}\n{traceback.format_exc()}")
         return redirect('view_manual')


# --- SerieExtraData List & Delete (Superadmin) ---
@login_required(login_url='/login/')
def list_serie_extra_data(request):
    """ Afișează lista paginată cu date extra serii, cu căutare. Doar Superadmin. """
    user_profile = getattr(request.user, 'userprofile', None)
    if not (user_profile and user_profile.role and user_profile.role.name.lower() == 'superadmin'):
        log_activity(request.user, "ACCESS_SERIE_DATA_DENIED", "Acces neautorizat la lista de date extra serii.")
        StandardMessages.access_denied(request)
        return redirect('administrare')

    queryset = SerieExtraData.objects.all().order_by('serie')
    search_query = request.GET.get('q', '').strip() # Filtru serie
    articol_query = request.GET.get('articol', '').strip() # Filtru articol

    # Optimizare: Construim maparea articol <-> serie o singură dată dacă e necesar
    articole_map = {}
    series_to_filter_by_articol = None # Inițial None

    # Dacă filtrăm după articol, găsim seriile relevante
    if articol_query:
        series_to_filter_by_articol = set()
        # Căutăm în JSON-ul TUTUROR documentelor (poate fi lent pe volume mari!)
        # Consideră o denormalizare dacă performanța devine o problemă.
        docs_json_data = GeneratedDocument.objects.filter(context_json__isnull=False).values_list('context_json', flat=True)
        for context_json_str in docs_json_data:
            try:
                context_data = json.loads(context_json_str)
                for i in range(1, 4):
                    pos_key = f'pozitie{i}'
                    if pos_key in context_data and isinstance(context_data[pos_key], dict):
                        position_data = context_data[pos_key]
                        serie = position_data.get('serie', '')
                        if not serie: continue

                        articol_found_in_pos = False
                        for field in ['articol', 'ARTICOL', 'soi', 'specia']:
                            articol_val = position_data.get(field, '')
                            if articol_val:
                                # Adăugăm în mapare (pentru afișare ulterioară, chiar dacă nu filtrăm)
                                if serie not in articole_map: articole_map[serie] = articol_val
                                # Verificăm potrivirea cu filtrul
                                if articol_query.lower() in str(articol_val).lower():
                                     series_to_filter_by_articol.add(serie)
                                     articol_found_in_pos = True; break # Găsit articol relevant în poziție
                        # Optimizare: dacă am găsit articol relevant în poziție, trecem la următoarea
                        # if articol_found_in_pos: break # Comentat: vrem să populăm articole_map complet
            except (json.JSONDecodeError, AttributeError) as e:
                print(f"WARN: Eroare parsare JSON în list_serie_extra_data: {e}")
                continue # Ignorăm JSON invalid

    # Aplicăm filtrele la queryset
    if search_query:
        queryset = queryset.filter(serie__icontains=search_query)
    if series_to_filter_by_articol is not None: # Am filtrat după articol
        queryset = queryset.filter(serie__in=list(series_to_filter_by_articol))

    # Construim maparea de articole dacă nu s-a filtrat pe articol (pt afișare)
    if not articol_query:
         series_in_queryset = list(queryset.values_list('serie', flat=True))
         if series_in_queryset:
              # Căutăm articole DOAR pentru seriile din queryset-ul curent (mai eficient)
              docs_json_data = GeneratedDocument.objects.filter(
                  context_json__icontains=any(s for s in series_in_queryset) # Optimizare JSONB? Sau căutare string
              ).filter(context_json__isnull=False).values_list('context_json', flat=True) # Revizuieste filtrarea asta! Poate fi lenta.

              for context_json_str in docs_json_data:
                   try:
                        context_data = json.loads(context_json_str)
                        for i in range(1, 4):
                             pos_key = f'pozitie{i}'
                             if pos_key in context_data and isinstance(context_data[pos_key], dict):
                                 position_data = context_data[pos_key]
                                 serie = position_data.get('serie', '')
                                 # Verificăm dacă seria e relevantă și nu avem deja articol pt ea
                                 if serie and serie in series_in_queryset and serie not in articole_map:
                                      for field in ['articol', 'ARTICOL', 'soi', 'specia']:
                                           articol_val = position_data.get(field, '')
                                           if articol_val:
                                                articole_map[serie] = articol_val
                                                break # Am găsit primul articol, e suficient
                   except (json.JSONDecodeError, AttributeError) as e:
                       continue


    # Paginare
    page_number = request.GET.get('page', 1)
    paginator = Paginator(queryset, 25)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger: page_obj = paginator.page(1)
    except EmptyPage: page_obj = paginator.page(paginator.num_pages)

    if not search_query and not articol_query:
        log_activity(request.user, "ACCESS_SERIE_DATA_LIST", "A accesat lista de date extra pentru serii.")

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'articol_query': articol_query,
        'total_results': paginator.count, # Folosim count de la paginator
        'articole_map': articole_map
    }
    return render(request, 'certificat/serie_extra_data_list.html', context)


@require_POST # Folosim POST pentru ștergere
@login_required(login_url='/login/')
def delete_serie_extra_data(request, pk):
    """ Șterge o intrare specifică SerieExtraData. Doar Superadmin. """
    user_profile = getattr(request.user, 'userprofile', None)
    if not (user_profile and user_profile.role and user_profile.role.name.lower() == 'superadmin'):
        log_activity(request.user, "DELETE_SERIE_DATA_DENIED", f"Încercare ștergere date serie ID: {pk} (neautorizat).")
        StandardMessages.access_denied(request)
        # Răspuns JSON sau redirect? Redirect la listă e mai consistent
        # return JsonResponse({'status': 'error', 'message': 'Acces nepermis'}, status=403)
        return redirect('list_serie_extra_data')

    try:
        serie_data = get_object_or_404(SerieExtraData, pk=pk)
        serie_val = serie_data.serie
        serie_data.delete()
        log_activity(request.user, "DELETE_SERIE_DATA_SUCCESS", f"Șters datele extra pentru seria '{serie_val}' (ID: {pk}).")
        StandardMessages.item_deleted(request, f"Datele salvate pentru seria '{serie_val}'")
        # Răspuns JSON pentru AJAX? Sau doar redirect? Presupunem redirect.
        # return JsonResponse({'status': 'success', 'message': 'Intrare ștearsă.'})

    except Http404:
        log_activity(request.user, "DELETE_SERIE_DATA_NOT_FOUND", f"Încercare ștergere date serie ID: {pk} (negăsit).")
        StandardMessages.item_not_found(request, "Intrarea de date pentru serie")
        # return JsonResponse({'status': 'error', 'message': 'Intrarea nu a fost găsită.'}, status=404)
    except Exception as e:
        log_activity(request.user, "DELETE_SERIE_DATA_ERROR", f"Eroare la ștergerea datelor serie ID: {pk}. Eroare: {e}")
        StandardMessages.operation_failed(request, f"ștergerea datelor pentru seria (ID: {pk})", str(e))
        # return JsonResponse({'status': 'error', 'message': f'Eroare server: {e}'}, status=500)

    # Redirect înapoi la listă, păstrând filtrele?
    # Trebuie să preluăm filtrele din request-ul inițial (GET) sau din POST dacă sunt trimise
    redirect_url = reverse('list_serie_extra_data')
    # Ar trebui să adăugăm query params aici dacă vrem să păstrăm filtrele/pagina
    # Exemplu: params = request.session.get('list_serie_extra_data_params', {})
    # if params: redirect_url += '?' + urlencode(params)
    return redirect(redirect_url)


@require_POST
@login_required(login_url='/login/')
def bulk_delete_serie_data(request):
    """ Gestionează ștergerea în masă a SerieExtraData. Doar Superadmin. """
    user_profile = getattr(request.user, 'userprofile', None)
    if not (user_profile and user_profile.role and user_profile.role.name.lower() == 'superadmin'):
        log_activity(request.user, "BULK_DELETE_SERIE_DATA_DENIED", "Încercare ștergere în masă date serie (neautorizat).")
        StandardMessages.access_denied(request)
        # Construim redirect-ul cu parametrii existenți
        redirect_url = reverse('list_serie_extra_data')
        query_params_dict = {k: v for k, v in request.POST.items() if k in ['q', 'articol', 'page']}
        if query_params_dict: redirect_url += '?' + urlencode(query_params_dict)
        return redirect(redirect_url)

    selected_pks = request.POST.getlist('selected_pks')
    deleted_count = 0
    object_type = "înregistrări date serie"

    if selected_pks:
        try:
            valid_pks = [int(pk) for pk in selected_pks] # Validăm că sunt numere
            queryset_to_delete = SerieExtraData.objects.filter(pk__in=valid_pks)
            # delete() returnează (număr total șters, dicționar {'app.Model': count})
            deleted_info = queryset_to_delete.delete()
            deleted_count = deleted_info[0]

            if deleted_count > 0:
                log_activity(request.user, "BULK_DELETE_SERIE_DATA_SUCCESS", f"Șters în masă {deleted_count} {object_type}. PKs: {valid_pks}")
                messages.success(request, f"{deleted_count} {object_type} au fost șterse cu succes.")
            else:
                messages.warning(request, "Nicio înregistrare validă nu a fost găsită pentru ștergere.")
                log_activity(request.user, "BULK_DELETE_SERIE_DATA_NO_MATCH", f"Ștergere masă: Niciun PK valid găsit din {selected_pks}")

        except ValueError:
            messages.error(request, "Eroare: Selecția conține ID-uri invalide.")
            log_activity(request.user, "BULK_DELETE_SERIE_DATA_INVALID_PK", f"Încercare ștergere masă cu PK-uri invalide: {selected_pks}")
        except Exception as e:
            messages.error(request, f"A apărut o eroare la ștergerea în masă: {e}")
            log_activity(request.user, "BULK_DELETE_SERIE_DATA_ERROR", f"Eroare ștergere masă date serie. PKs: {selected_pks}. Eroare: {e}")
    else:
        messages.warning(request, "Nu ați selectat nicio înregistrare pentru ștergere.")
        log_activity(request.user, "BULK_DELETE_SERIE_DATA_NO_SELECTION", "Încercare ștergere masă fără selecție.")

    # Redirect înapoi la listă, păstrând filtrele și pagina din POST
    redirect_url = reverse('list_serie_extra_data')
    query_params_dict = {k: v for k, v in request.POST.items() if k in ['q', 'articol', 'page'] and v} # Doar params cu valoare
    if query_params_dict:
        redirect_url += '?' + urlencode(query_params_dict)
    return redirect(redirect_url)


# --- Upload Manual Direct (Probabil redundant dacă e în Admin) ---
@login_required(login_url='/login/')
def upload_manual_direct(request):
    """ View simplificat pt upload manual (dacă nu e în admin). """
    user_profile = getattr(request.user, 'userprofile', None)
    if not (user_profile and user_profile.role and user_profile.role.name.lower() == 'superadmin'):
        messages.error(request, "Acces neautorizat.")
        log_activity(request.user, "ACCESS_UPLOAD_MANUAL_DENIED", "Acces neautorizat upload manual direct.")
        return redirect('home')

    if request.method == 'POST':
        form = UserManualForm(request.POST, request.FILES) # Fără prefix aici
        if form.is_valid():
            try:
                manual = form.save()
                log_activity(request.user, "MANUAL_UPLOAD_DIRECT", f"Manual '{manual.title}' v{manual.version} încărcat (direct).")
                messages.success(request, f"Manual '{manual.title}' v{manual.version} încărcat cu succes!")
                return redirect('view_manual') # Redirect la vizualizare manual
            except Exception as e_save:
                 messages.error(request, f"Eroare la salvarea manualului: {e_save}")
                 log_activity(request.user, "MANUAL_UPLOAD_DIRECT_FAIL", f"Salvare manual (direct) eșuată. Eroare: {e_save}")
        else:
            messages.error(request, f"Erori la validarea formularului: {form.errors}")
            log_activity(request.user, "MANUAL_UPLOAD_DIRECT_INVALID", f"Formular upload manual (direct) invalid. Erori: {form.errors.as_json()}")
    else:
        form = UserManualForm()
        log_activity(request.user, "ACCESS_UPLOAD_MANUAL_FORM", "Accesat formular upload manual (direct).")

    return render(request, 'certificat/upload_manual.html', {'form': form})


# --- Delete Manual ---
@require_POST # Folosim POST pentru ștergere
@login_required(login_url='/login/')
def delete_manual(request, manual_id):
    """ Șterge un manual specific. Doar Superadmin. """
    user_profile = getattr(request.user, 'userprofile', None)
    if not (user_profile and user_profile.role and user_profile.role.name.lower() == 'superadmin'):
        messages.error(request, "Acces neautorizat.")
        log_activity(request.user, "MANUAL_DELETE_DENIED", f"Încercare ștergere manual ID: {manual_id} (neautorizat).")
        # Redirect la pagina de unde a venit sau la vizualizare manual
        referer = request.META.get('HTTP_REFERER', reverse('view_manual'))
        return redirect(referer)

    try:
        manual = get_object_or_404(UserManual, pk=manual_id)
        manual_info = f"Manual: '{manual.title}' (v{manual.version}, ID: {manual_id})"

        # Ștergem fișierul asociat DUPĂ confirmarea ștergerii obiectului
        file_path = manual.file.path if manual.file else None

        # Ștergem obiectul din DB
        manual.delete()

        # Încercăm să ștergem fișierul fizic
        if file_path and default_storage.exists(file_path):
             try:
                 default_storage.delete(file_path)
                 print(f"INFO: Fișier manual șters: {file_path}")
             except Exception as e_file_del:
                 # Logăm eroarea, dar nu o considerăm critică pentru user
                 print(f"WARN: Nu s-a putut șterge fișierul manualului {file_path}: {e_file_del}")
                 log_activity(request.user, "MANUAL_DELETE_FILE_FAIL", f"Eroare ștergere fișier pentru {manual_info}. Eroare: {e_file_del}")

        log_activity(request.user, "MANUAL_DELETE_SUCCESS", f"{manual_info} a fost șters cu succes.")
        messages.success(request, f"Manualul a fost șters cu succes.")

    except Http404:
        messages.error(request, "Manualul specificat nu a fost găsit.")
        log_activity(request.user, "MANUAL_DELETE_FAIL_NOT_FOUND", f"Încercare ștergere manual ID: {manual_id} (negăsit).")
    except Exception as e:
        messages.error(request, f"Eroare la ștergerea manualului: {str(e)}")
        log_activity(request.user, "MANUAL_DELETE_FAIL_ERROR", f"Eroare la ștergerea manualului ID: {manual_id}. Eroare: {e}")
        print(f"ERROR deleting manual {manual_id}: {e}\n{traceback.format_exc()}")

    # Redirect la pagina de administrare dacă a venit de acolo, altfel la vizualizare manual
    referer = request.META.get('HTTP_REFERER')
    if referer and reverse('administrare') in referer:
        return redirect('administrare')
    else:
        return redirect('view_manual')


@login_required(login_url='/login/')
def delete_all_documents(request):
    """View pentru ștergerea tuturor documentelor generate."""
    user_profile = getattr(request.user, 'userprofile', None)
    if not (user_profile and user_profile.role and user_profile.role.name.lower() == 'superadmin'):
        log_activity(request.user, "DELETE_ALL_DOCS_DENIED", "Acces neautorizat la ștergerea avizelor.")
        StandardMessages.access_denied(request)
        return redirect('administrare')

    total_documents = GeneratedDocument.objects.count()

    if request.method == 'POST':
        password = request.POST.get('admin_password')
        confirm_text = request.POST.get('confirm_text')
        date_limit = request.POST.get('date_limit')

        # Verificare parolă
        if not request.user.check_password(password):
            messages.error(request, "Parola introdusă este incorectă.")
            log_activity(request.user, "DELETE_ALL_DOCS_WRONG_PASSWORD",
                         "Încercare ștergere avize cu parolă incorectă.")
            return redirect('delete_all_documents')

        # Verificare text confirmare
        if confirm_text != "CONFIRM STERGERE":
            messages.error(request,
                           "Textul de confirmare este incorect. Trebuie să introduceți exact 'CONFIRM STERGERE'.")
            log_activity(request.user, "DELETE_ALL_DOCS_WRONG_CONFIRM",
                         "Încercare ștergere avize cu text confirmare incorect.")
            return redirect('delete_all_documents')

        try:
            query = GeneratedDocument.objects.all()

            # Aplicare filtru dată dacă există
            if date_limit:
                try:
                    date_limit_obj = datetime.strptime(date_limit, '%Y-%m-%d').date()
                    query = query.filter(created_at__date__lte=date_limit_obj)
                    log_activity(request.user, "DELETE_ALL_DOCS_WITH_DATE",
                                 f"Ștergere avize până la data: {date_limit}")
                except ValueError:
                    messages.warning(request, "Formatul datei este invalid. Se vor șterge toate avizele.")

            # Ștergem fișierele fizice înainte de a șterge înregistrările
            for doc in query:
                if doc.pdf_file:
                    try:
                        if doc.pdf_file.storage.exists(doc.pdf_file.path):
                            doc.pdf_file.delete(save=False)
                    except Exception as e:
                        print(f"Eroare la ștergerea fișierului {doc.pdf_file}: {e}")

            # Contorizăm și ștergem
            count_deleted = query.count()
            query.delete()

            log_activity(request.user, "DELETE_ALL_DOCS_SUCCESS", f"Au fost șterse {count_deleted} documente generate.")
            StandardMessages.operation_success(request, f"Au fost șterse cu succes {count_deleted} documente generate.")

            return redirect('administrare')

        except Exception as e:
            error_message = f"A apărut o eroare la ștergerea documentelor: {e}"
            log_activity(request.user, "DELETE_ALL_DOCS_ERROR", f"Eroare la ștergerea documentelor: {e}")
            messages.error(request, error_message)
            return redirect('delete_all_documents')

    # GET request - afișare formular
    context = {
        'total_documents': total_documents,
    }
    log_activity(request.user, "ACCESS_DELETE_ALL_DOCS", "Acces la pagina de ștergere toate documentele.")
    return render(request, 'certificat/delete_all_documents.html', context)

from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash

@login_required(login_url='/login/')
def change_password(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            # Actualizăm sesiunea pentru a păstra utilizatorul autentificat
            update_session_auth_hash(request, user)
            log_activity(request.user, "PASSWORD_CHANGE", "Și-a schimbat parola cu succes.")
            StandardMessages.operation_success(request, "Parola a fost schimbată cu succes.")
            return redirect('home')
        else:
            StandardMessages.operation_failed(request, "schimbarea parolei", "Verificați datele introduse")
            log_activity(request.user, "PASSWORD_CHANGE_FAIL", f"Schimbare parolă eșuată. Erori: {form.errors.as_json()}")
    else:
        form = PasswordChangeForm(request.user)
        log_activity(request.user, "ACCESS_PASSWORD_CHANGE", "A accesat pagina de schimbare parolă.")

    return render(request, 'certificat/change_password.html', {
        'form': form
    })


@login_required(login_url='/login/')
def update_document_data(request, doc_id):
    """Actualizează datele documentului din sursa externă."""
    try:
        doc = get_object_or_404(GeneratedDocument, id=doc_id)

        # Verificare permisiuni
        user_profile = getattr(request.user, 'userprofile', None)
        is_owner = doc.generated_by_id == request.user.id
        is_admin_or_super = user_profile and user_profile.role and user_profile.role.name.lower() in ['admin',
                                                                                                      'superadmin']

        if not (is_owner or is_admin_or_super):
            log_activity(request.user, "UPDATE_DOC_DATA_DENIED",
                         f"Încercare neautorizată de actualizare date pentru doc ID: {doc_id}")
            StandardMessages.access_denied(request)
            return redirect('generated_documents_list')

        # Verifică dacă documentul are status valid pentru actualizare
        if doc.status not in ['finalizat', 'in procesare']:
            messages.warning(request,
                             "Actualizarea poate fi efectuată doar pentru documente finalizate sau în procesare.")
            log_activity(request.user, "UPDATE_DOC_DATA_INVALID_STATUS",
                         f"Încercare actualizare doc ID: {doc_id} cu status invalid: {doc.status}")
            return redirect('generated_documents_list')

        # Obține context-ul original
        old_context = {}
        if doc.context_json:
            try:
                old_context = json.loads(doc.context_json)
            except json.JSONDecodeError:
                messages.error(request, "Contextul documentului este invalid și nu poate fi actualizat.")
                log_activity(request.user, "UPDATE_DOC_DATA_INVALID_JSON",
                             f"Context JSON invalid pentru doc ID: {doc_id}")
                return redirect('generated_documents_list')

        # Extrage avizul și seriile din context
        aviz_number = doc.aviz_number
        series_list = []

        # Extrage serii din pozițiile 1-3
        for i in range(1, 4):
            pos_key = f"pozitie{i}"
            if pos_key in old_context and isinstance(old_context[pos_key], dict):
                serie = old_context[pos_key].get("serie", "")
                if serie:
                    series_list.append(serie)

        if not series_list:
            messages.warning(request, "Nu s-au găsit serii în document pentru actualizare.")
            log_activity(request.user, "UPDATE_DOC_DATA_NO_SERIES", f"Nicio serie găsită pentru doc ID: {doc_id}")
            return redirect('generated_documents_list')

        # Preluăm datele noi din sursa externă
        try:
            json_url = "https://moldova.info-media.ro/surse/WebFormExportDate.aspx?token=wme_avize_serii_cant"
            response = requests.get(json_url, timeout=20)
            response.raise_for_status()
            data_list = response.json()

            # Filtrăm datele pentru avizul nostru
            aviz_records = [item for item in data_list if
                            int(float(item.get("AVIZ", 0))) == int(float(aviz_number))]

            if not aviz_records:
                messages.warning(request, f"Nu s-au găsit date noi pentru avizul {aviz_number} în sursa externă.")
                log_activity(request.user, "UPDATE_DOC_DATA_NO_DATA",
                             f"Nicio dată găsită în sursa externă pentru avizul {aviz_number}")
                return redirect('generated_documents_list')

            # Construim un dicționar cu datele actualizate pentru fiecare serie
            updated_data = {}
            for record in aviz_records:
                serie = record.get("SERIE", "").strip()
                if serie in series_list:
                    if serie not in updated_data:
                        updated_data[serie] = {
                            "serie": serie,
                            "articol": record.get("ARTICOL", "").strip(),
                            "cantitate": float(record.get("CANT", 0)),
                            "specia": record.get("SPECIE", "").strip(),
                            "um": record.get("UM", "").strip(),
                            "soi": record.get("soi", "").strip() or record.get("ARTICOL", "").strip(),
                            "nr_referinta": record.get("nr_referinta", "").strip() or serie
                        }
                    else:
                        # Adăugăm cantitățile dacă seria apare de mai multe ori
                        updated_data[serie]["cantitate"] += float(record.get("CANT", 0))

            # Verificăm dacă am găsit date pentru fiecare serie
            missing_series = [s for s in series_list if s not in updated_data]
            if missing_series:
                messages.warning(request,
                                 f"Nu s-au găsit date pentru următoarele serii: {', '.join(missing_series)}")
                log_activity(request.user, "UPDATE_DOC_DATA_MISSING_SERIES",
                             f"Serii negăsite în sursa externă: {missing_series} pentru doc ID: {doc_id}")

            if not updated_data:
                messages.warning(request, "Nu s-au găsit date pentru nicio serie din document.")
                log_activity(request.user, "UPDATE_DOC_DATA_ALL_SERIES_MISSING",
                             f"Toate seriile lipsesc din sursa externă pentru doc ID: {doc_id}")
                return redirect('generated_documents_list')

            # Actualizăm contextul cu noile date
            new_context = old_context.copy()
            changes = []

            for i in range(1, 4):
                pos_key = f"pozitie{i}"
                if pos_key in new_context and isinstance(new_context[pos_key], dict):
                    serie = new_context[pos_key].get("serie", "")
                    if serie in updated_data:
                        # Salvăm valorile vechi pentru a afișa modificările
                        old_cantitate = new_context[pos_key].get("cantitate", 0)
                        old_articol = new_context[pos_key].get("articol", "")
                        old_um = new_context[pos_key].get("um", "")

                        # Actualizăm cu noile valori
                        new_context[pos_key].update(updated_data[serie])

                        # Adăugăm modificările în lista de schimbări
                        if old_cantitate != updated_data[serie]["cantitate"]:
                            changes.append(
                                f"Seria {serie}: Cantitate {old_cantitate} → {updated_data[serie]['cantitate']}")
                        if old_articol != updated_data[serie]["articol"]:
                            changes.append(
                                f"Seria {serie}: Articol '{old_articol}' → '{updated_data[serie]['articol']}'")
                        if old_um != updated_data[serie]["um"]:
                            changes.append(f"Seria {serie}: UM '{old_um}' → '{updated_data[serie]['um']}'")

            # Salvăm noul context
            doc.context_json = json.dumps(new_context, ensure_ascii=False)
            doc.save()

            # Afișăm mesaj de succes cu modificările
            if changes:
                message = "Datele au fost actualizate cu succes. Modificări:"
                for change in changes[:5]:  # Afișăm maximum 5 modificări
                    message += f"\n- {change}"
                if len(changes) > 5:
                    message += f"\n... și încă {len(changes) - 5} modificări."
                messages.success(request, message)
                log_activity(request.user, "UPDATE_DOC_DATA_SUCCESS",
                             f"Date actualizate pentru doc ID: {doc_id}. Modificări: {changes}")
            else:
                messages.success(request, "Datele documentului au fost verificate. Nu s-au găsit modificări.")
                log_activity(request.user, "UPDATE_DOC_DATA_NO_CHANGES",
                             f"Nicio modificare găsită la actualizarea doc ID: {doc_id}")

        except requests.exceptions.RequestException as e:
            messages.error(request, f"Eroare la comunicarea cu sursa externă: {str(e)}")
            log_activity(request.user, "UPDATE_DOC_DATA_API_ERROR",
                         f"Eroare API la actualizarea doc ID: {doc_id}. Error: {e}")
        except (ValueError, json.JSONDecodeError) as e:
            messages.error(request, f"Eroare la procesarea datelor: {str(e)}")
            log_activity(request.user, "UPDATE_DOC_DATA_PROCESSING_ERROR",
                         f"Eroare procesare la actualizarea doc ID: {doc_id}. Error: {e}")
        except Exception as e:
            messages.error(request, f"Eroare neașteptată: {str(e)}")
            log_activity(request.user, "UPDATE_DOC_DATA_UNEXPECTED_ERROR",
                         f"Eroare neașteptată la actualizarea doc ID: {doc_id}. Error: {e}")
    except Http404:
        messages.error(request, "Documentul specificat nu a fost găsit.")
        log_activity(request.user, "UPDATE_DOC_DATA_DOC_NOT_FOUND", f"Document negăsit ID: {doc_id}")
    except Exception as e:
        messages.error(request, f"Eroare generală: {str(e)}")
        log_activity(request.user, "UPDATE_DOC_DATA_GENERAL_ERROR",
                     f"Eroare generală la actualizarea doc ID: {doc_id}. Error: {e}")

    return redirect('generated_documents_list')


@login_required(login_url='/login/')
def restore_document(request, doc_id):
    # Verifică dacă utilizatorul este superadmin
    user_profile = getattr(request.user, 'userprofile', None)
    is_superadmin = user_profile and user_profile.role and user_profile.role.name.lower() == 'superadmin'

    if not is_superadmin:
        return JsonResponse({
            'status': 'error',
            'message': 'Doar superadminii pot restaura documente șterse.'
        }, status=403)

    try:
        doc = get_object_or_404(GeneratedDocument, id=doc_id)

        if not doc.is_deleted:
            return JsonResponse({
                'status': 'error',
                'message': 'Documentul nu este marcat ca șters.'
            }, status=400)

        # Verifică dacă există deja alte documente neșterse pentru același aviz
        existing_docs = GeneratedDocument.objects.filter(
            aviz_number=doc.aviz_number,
            is_deleted=False
        ).exists()

        if existing_docs:
            log_activity(request.user, "RESTORE_DOC_DENIED",
                         f"Restaurare document ID: {doc_id} (Aviz: {doc.aviz_number}) blocată: există deja documente active pentru acest aviz.")
            return JsonResponse({
                'status': 'error',
                'message': f'Nu se poate restaura documentul pentru avizul {doc.aviz_number} deoarece există deja alte documente active pentru acest aviz.'
            }, status=400)

        # Restaurează documentul
        doc.is_deleted = False
        doc.deleted_at = None
        doc.deleted_by = None
        doc.save()

        log_activity(request.user, "RESTORE_DOC_SUCCESS",
                     f"Document ID: {doc_id} (Aviz: {doc.aviz_number}, Serie: {doc.document_series}) restaurat.")

        return JsonResponse({
            'status': 'success',
            'message': f'Documentul pentru avizul {doc.aviz_number} a fost restaurat cu succes.'
        })

    except Http404:
        return JsonResponse({
            'status': 'error',
            'message': 'Documentul specificat nu a fost găsit.'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Eroare la restaurarea documentului: {str(e)}'
        }, status=500)