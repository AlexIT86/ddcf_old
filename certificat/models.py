from django.conf import settings
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import RegexValidator

class Role(models.Model):
    ROLE_CHOICES = [
        ('utilizator', 'Utilizator'),
        ('admin', 'Admin'),
        ('superadmin', 'Super Admin'),
    ]
    name = models.CharField(max_length=20, choices=ROLE_CHOICES, unique=True)
    
    # Template de permisiuni pentru acest rol (se vor aplica automat la toti userii cu acest rol)
    ok_raportare = models.BooleanField(default=False, help_text="Permite accesul la pagina de raportare")
    ok_administrare = models.BooleanField(default=True, help_text="Permite accesul la pagina de administrare")
    ok_aviz = models.BooleanField(default=True, help_text="Permite generarea de avize/certificate")
    ok_plaje = models.BooleanField(default=True, help_text="Permite gestionarea plajelor de numere")
    ok_gestiuni = models.BooleanField(default=True, help_text="Permite gestionarea gestiunilor")
    ok_tipologii = models.BooleanField(default=True, help_text="Permite gestionarea tipologiilor")
    ok_doc_generate = models.BooleanField(default=False, help_text="Permite vizualizarea documentelor generate")
    vede_toate_documentele = models.BooleanField(default=False, help_text="Utilizatorul vede toate documentele sau doar pe ale lui")

    def __str__(self):
        return self.name

class Gestiune(models.Model):
    nume = models.CharField(max_length=100)
    locatie = models.CharField(max_length=100)
    cod_inregistrare = models.CharField(max_length=50, unique=True, blank=True, null=True)

    def __str__(self):
        return self.nume

class TipologieProdus(models.Model):
    nume = models.CharField(max_length=100)

    def __str__(self):
        return self.nume

alphanumeric_validator = RegexValidator(r'^[0-9a-zA-Z-]+$', 'Doar litere, cifre și caracterul "-" sunt permise.')
class DocumentRange(models.Model):
    gestiune = models.ForeignKey(Gestiune, on_delete=models.CASCADE)
    tipologie = models.ForeignKey(TipologieProdus, on_delete=models.CASCADE, default=1)
    numar_inceput = models.CharField(max_length=50)
    numar_final = models.CharField(max_length=50)
    numar_curent = models.CharField(max_length=50, default='')

    def __str__(self):
        return f"{self.gestiune} - {self.tipologie}"

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, blank=True)
    gestiune = models.ForeignKey(Gestiune, on_delete=models.SET_NULL, null=True, blank=True)
    ok_raportare = models.BooleanField(default=False)
    ok_administrare = models.BooleanField(default=True)
    ok_aviz = models.BooleanField(default=True)
    ok_plaje = models.BooleanField(default=True)
    ok_gestiuni = models.BooleanField(default=True)
    ok_tipologii = models.BooleanField(default=True)
    ok_doc_generate = models.BooleanField(default=False)
    vede_toate_documentele = models.BooleanField(default=False, help_text="Dacă este bifat, utilizatorul vede toate documentele din sistem. Altfel, vede doar documentele generate de el.")

    def __str__(self):
        return self.user.username

class Certificat(models.Model):
    gestiune = models.ForeignKey(Gestiune, on_delete=models.CASCADE)
    numar_document = models.IntegerField(unique=True)
    aviz_number = models.CharField(max_length=100)
    data_aviz = models.DateField()
    beneficiar = models.CharField(max_length=200)
    date_complementare = models.TextField(blank=True, null=True)  # câmp extra

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Certificat {self.numar_document} - Aviz {self.aviz_number}"

class SpecieMapping(models.Model):
    specie = models.CharField(max_length=100, unique=True)
    tipologie = models.ForeignKey(TipologieProdus, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.specie} -> {self.tipologies}"

class SerieExtraData(models.Model):
    serie = models.CharField(max_length=100, unique=True, db_index=True)
    nr_ambalaje = models.CharField(max_length=255, blank=True, null=True)
    doc_oficial = models.CharField(max_length=255, blank=True, null=True)
    etch_oficiale = models.CharField(max_length=255, blank=True, null=True)
    puritate = models.CharField(max_length=50, blank=True, null=True) # Sau FloatField/DecimalField dacă sunt numere
    sem_straine = models.CharField(max_length=50, blank=True, null=True)
    umiditate = models.CharField(max_length=50, blank=True, null=True)
    germinatie = models.CharField(max_length=50, blank=True, null=True)
    masa_1000b = models.CharField(max_length=50, blank=True, null=True)
    stare_sanitara = models.CharField(max_length=255, blank=True, null=True)
    cold = models.CharField(max_length=50, blank=True, null=True)
    producator = models.CharField(max_length=255, blank=True, null=True)
    tara_productie = models.CharField(max_length=100, blank=True, null=True)
    samanta_tratata = models.CharField(max_length=255, blank=True, null=True)
    garantie = models.CharField(max_length=100, blank=True, null=True)
    # Adaugă timestamp-uri dacă dorești
    # created_at = models.DateTimeField(auto_now_add=True)
    # updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Date extra pentru seria {self.serie}"

    class Meta:
        verbose_name = "Date Extra Serie"
        verbose_name_plural = "Date Extra Serii"

class GeneratedDocument(models.Model):
    aviz_number = models.CharField(max_length=100, db_index=True)  # nu mai e unic
    pdf_file = models.FileField(upload_to="generated_docs/", blank=True, null=True)
    generated_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    context_json = models.TextField(blank=True, null=True)
    partner = models.CharField(max_length=200, blank=True, null=True)  # PARTENER
    document_series = models.CharField(max_length=100, blank=True, null=True, db_index=True)  # placeholder {{seria}}
    regenerated = models.BooleanField(default=False)  # Indicator dacă documentul a fost regenerat
    regenerated_at = models.DateTimeField(blank=True, null=True)  # Data ultimei regenerări
    regeneration_count = models.IntegerField(default=0)  # Numărul de regenerări
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='deleted_documents')
    STATUS_CHOICES = [
        ('salvat', 'Salvat'),
        ('finalizat', 'Finalizat'),
        ('in procesare', 'In procesare'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='salvat', db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['is_deleted', 'created_at'], name='idx_doc_active_date'),
            models.Index(fields=['generated_by', 'is_deleted'], name='idx_doc_user_active'),
        ]

    def __str__(self):
        return f"Document {self.aviz_number} - {self.document_series} - {self.status}"

class ActivityLog(models.Model):
    """Model pentru a stoca jurnalul de activitate al utilizatorilor."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, # Păstrează log-ul chiar dacă userul e șters
        null=True,
        blank=True,
        verbose_name="Utilizator"
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name="Dată și Oră"
    )
    action_type = models.CharField(
        max_length=100,
        blank=True, # Opțional, pentru categorisire
        db_index=True,
        verbose_name="Tip Acțiune"
    )
    details = models.TextField(
        verbose_name="Detalii Acțiune"
    )
    # Opțional: Adaugă IP, etc.
    # ip_address = models.GenericIPAddressField(null=True, blank=True)

    def __str__(self):
        user_display = self.user.username if self.user else "Sistem/Necunoscut"
        return f"{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')} - {user_display} - {self.action_type}"

    class Meta:
        verbose_name = "Înregistrare Jurnal Activitate"
        verbose_name_plural = "Jurnal Activitate"
        ordering = ['-timestamp'] # Afișează cele mai recente prima dată


class DailyQuote(models.Model):
    """Model to store daily quotes."""
    text = models.TextField(verbose_name="Text citatei")
    author = models.CharField(max_length=100, verbose_name="Autor")
    is_active = models.BooleanField(default=True, verbose_name="Activ")

    def __str__(self):
        return f"{self.text[:50]}... - {self.author}"

    class Meta:
        verbose_name = "Citat Zilnic"
        verbose_name_plural = "Citate Zilnice"

class UserManual(models.Model):
    """Model pentru stocarea manualului de utilizare al aplicației."""
    title = models.CharField(max_length=100, verbose_name="Titlu Manual")
    description = models.TextField(blank=True, null=True, verbose_name="Descriere")
    file = models.FileField(upload_to='manuals/', verbose_name="Fișier Manual")
    version = models.CharField(max_length=20, verbose_name="Versiune")
    upload_date = models.DateTimeField(auto_now=True, verbose_name="Data Încărcare")
    is_active = models.BooleanField(default=True, verbose_name="Activ")

    def __str__(self):
        return f"{self.title} (v{self.version})"

    class Meta:
        verbose_name = "Manual Utilizare"
        verbose_name_plural = "Manuale Utilizare"
        ordering = ['-upload_date']