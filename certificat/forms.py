# certificat/forms.py

from django import forms
from django.contrib.auth.models import User
from .models import (
    Role, Gestiune, TipologieProdus, UserProfile, DocumentRange,
    SpecieMapping, SerieExtraData, GeneratedDocument, UserManual
)
# Importăm FormHelper
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, HTML # Opțional, dacă vrei să adaugi HTML custom

# --- Formulare utilizate în administrare.html ---

class UserForm(forms.ModelForm):
    email = forms.EmailField(required=True)
    password = forms.CharField(widget=forms.PasswordInput, required=True)
    role = forms.ModelChoiceField(queryset=Role.objects.all(), required=False, label="Rol")
    gestiune = forms.ModelChoiceField(queryset=Gestiune.objects.all(), required=False, label="Gestiune")

    class Meta:
        model = User
        fields = ('username', 'email', 'password')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False # Nu genera <form>...</form>
        # Poți adăuga aici layout dacă vrei să controlezi ordinea/aspectul câmpurilor
        # self.helper.layout = Layout(...)

class RoleForm(forms.ModelForm):
    class Meta:
        model = Role
        fields = ('name', 'ok_raportare', 'ok_administrare', 'ok_aviz', 'ok_plaje', 'ok_gestiuni', 'ok_tipologii', 'ok_doc_generate', 'vede_toate_documentele')
        labels = {
            'name': 'Nume Rol',
            'ok_raportare': 'Permite Raportare',
            'ok_administrare': 'Permite Administrare',
            'ok_aviz': 'Permite Generare Avize',
            'ok_plaje': 'Permite Gestionare Plaje Numere',
            'ok_gestiuni': 'Permite Gestionare Gestiuni',
            'ok_tipologii': 'Permite Gestionare Tipologii',
            'ok_doc_generate': 'Permite Vizualizare Documente Generate',
            'vede_toate_documentele': 'Vede TOATE documentele (altfel doar proprii)'
        }
        widgets = {
            'name': forms.Select(attrs={'class': 'form-select', 'disabled': 'disabled'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False # Nu genera <form>...</form>
        # Facem ca numele să fie readonly (nu editabil)
        if self.instance and self.instance.pk:
            self.fields['name'].disabled = True

class GestiuneForm(forms.ModelForm):
    class Meta:
        model = Gestiune
        fields = ('nume', 'locatie', 'cod_inregistrare')
        labels = {
            'nume': 'Nume Gestiune',
            'locatie': 'Locație',
            'cod_inregistrare': 'Cod Înregistrare (Opțional)'
        }
        widgets = { # Poți adăuga clase bootstrap aici dacă nu le setează crispy automat
            'nume': forms.TextInput(attrs={'class': 'form-control'}),
            'locatie': forms.TextInput(attrs={'class': 'form-control'}),
            'cod_inregistrare': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False # Nu genera <form>...</form>

class TipologieProdusForm(forms.ModelForm):
    class Meta:
        model = TipologieProdus
        fields = ('nume',)
        labels = {
            'nume': 'Nume Tipologie'
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False # Nu genera <form>...</form>

class DocumentRangeForm(forms.ModelForm):
    class Meta:
        model = DocumentRange
        fields = ('gestiune', 'tipologie', 'numar_inceput', 'numar_final', 'numar_curent')
        labels = {
            'gestiune': 'Gestiune',
            'tipologie': 'Tipologie Document',
            'numar_inceput': 'Număr Început',
            'numar_final': 'Număr Final',
            'numar_curent': 'Număr Curent (Opțional)' # Simplificăm label-ul, help_text explică
        }
        help_texts = {
            'numar_curent': 'Lăsați gol pentru a începe de la "Număr Început" la prima generare.' # Text ajutător actualizat
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # --- MODIFICARE AICI ---
        self.fields['numar_curent'].required = False
        # --- SFÂRȘIT MODIFICARE ---

        self.helper = FormHelper()
        self.helper.form_tag = False

        if user:
            user_profile = getattr(user, 'userprofile', None)
            if user_profile and user_profile.role.name.lower() != 'superadmin' and user_profile.gestiune:
                self.fields['gestiune'].queryset = Gestiune.objects.filter(pk=user_profile.gestiune.pk)
                self.fields['gestiune'].disabled = True
                if not self.is_bound:
                     self.initial['gestiune'] = user_profile.gestiune
                self.fields['gestiune'].help_text = "Gestiunea este asignată automat contului tău."

class SpecieMappingManualForm(forms.ModelForm):
    class Meta:
        model = SpecieMapping
        fields = ('specie', 'tipologie')
        labels = {
            'specie': 'Nume Specie (Exact ca în datele externe)',
            'tipologie': 'Tipologie Produs Asignată'
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False # Nu genera <form>...</form>

class UserManualForm(forms.ModelForm):
    class Meta:
        model = UserManual
        fields = ['title', 'description', 'file', 'version']
        labels = {
            'title': 'Titlu Manual',
            'description': 'Descriere Scurtă (Opțional)',
            'file': 'Fișier (.docx)',
            'version': 'Versiune (ex: 1.0)'
        }
        widgets = { # Adăugăm clase explicit dacă nu le pune crispy
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'file': forms.FileInput(attrs={'class': 'form-control'}),
            'version': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False # Nu genera <form>...</form


# --- Formulare care NU sunt folosite pentru CREARE cu crispy în administrare.html ---
# (Le lăsăm neschimbate, fără FormHelper specific aici, dacă nu e necesar în altă parte)

class UserProfileForm(forms.ModelForm):
    # Acest formular este pentru editare user, probabil pe altă pagină/modal
    class Meta:
        model = UserProfile
        # Câmpurile sunt definite în model, le preia automat
        fields = ('role', 'gestiune', 'ok_raportare', 'ok_administrare', 'ok_aviz', 'ok_plaje', 'ok_gestiuni', 'ok_tipologii', 'ok_doc_generate', 'vede_toate_documentele')
        # Adaugă labels dacă vrei nume mai prietenoase
        labels = {
            'ok_raportare': 'Permite Raportare',
            'ok_administrare': 'Permite Administrare (general)',
            'ok_aviz': 'Permite Generare Avize',
            'ok_plaje': 'Permite Gestionare Plaje Numere',
            'ok_gestiuni': 'Permite Gestionare Gestiuni (Superadmin)',
            'ok_tipologii': 'Permite Gestionare Tipologii (Superadmin)',
            'ok_doc_generate': 'Permite Vizualizare Documente Generate (general)',
            'vede_toate_documentele': 'Vede TOATE documentele (altfel vede doar doc. proprii)'
        }
        # Poți adăuga help_texts pentru clarificări

class SpecieMappingForm(forms.ModelForm):
    # Acest formular pare folosit în update_speciemapping, cu specie hidden
    class Meta:
        model = SpecieMapping
        fields = ('specie', 'tipologie')
        widgets = {
            "specie": forms.HiddenInput(), # Păstrăm widget-ul hidden
        }
        labels = {
            'tipologie': 'Selectează Tipologia'
        }
    # Nu adăugăm helper aici dacă nu e randat cu {% crispy %} în acel view

class SerieExtraDataForm(forms.ModelForm):
    # Folosit în edit_generated_document și generate_docx_aviz
    class Meta:
        model = SerieExtraData
        fields = [
            'serie', 'nr_ambalaje', 'doc_oficial', 'etch_oficiale', 'puritate',
            'sem_straine', 'umiditate', 'germinatie', 'masa_1000b',
            'stare_sanitara', 'cold', 'producator', 'tara_productie',
            'samanta_tratata', 'garantie',
        ]
        widgets = {
            'serie': forms.HiddenInput(),
            # Poți scoate clasele de aici dacă folosești crispy în template-ul unde e redat
            'nr_ambalaje': forms.TextInput(), #attrs={'class': 'form-control'}),
            'doc_oficial': forms.TextInput(), #attrs={'class': 'form-control'}),
            # ... etc pentru celelalte ...
            'samanta_tratata': forms.TextInput(), #attrs={'class': 'form-control'}),
            'garantie': forms.TextInput(), #attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Păstrăm logica de a face câmpurile neobligatorii
        for field_name, field in self.fields.items():
            if field_name != 'serie':
                field.required = False
    # Nu adăugăm helper aici dacă nu e randat cu {% crispy %} în acele view-uri

class GeneratedDocumentForm(forms.ModelForm):
    # Nu pare folosit pentru redare cu crispy
    class Meta:
        model = GeneratedDocument
        fields = ['partner', 'status']

class GeneratedDocumentEditForm(forms.ModelForm):
     # Nu pare folosit pentru redare cu crispy
    class Meta:
        model = GeneratedDocument
        fields = []