"""
Utility functions for standardized messages across the application.
"""
from django.contrib import messages
from .models import ActivityLog
from django.contrib.auth.models import AnonymousUser, User # Importă User dacă e nevoie

class StandardMessages:
    """
    Class that provides standardized message templates for various actions.
    """

    # Success messages
    @staticmethod
    def item_created(request, item_type):
        messages.success(request, f"{item_type} a fost creat cu succes.")

    @staticmethod
    def item_updated(request, item_type):
        messages.success(request, f"{item_type} a fost actualizat cu succes.")

    @staticmethod
    def item_deleted(request, item_type):
        messages.success(request, f"{item_type} a fost șters cu succes.")

    @staticmethod
    def operation_success(request, message):
        messages.success(request, message)

    # Info messages
    @staticmethod
    def info_message(request, message):
        messages.info(request, message)

    # Warning messages
    @staticmethod
    def duplicate_warning(request, item_type, identifier):
        messages.warning(
            request,
            f"Există deja un {item_type} cu identificatorul {identifier}. Modificările pot duce la duplicate."
        )

    @staticmethod
    def incomplete_data(request, message):
        messages.warning(request, message)

    # Error messages
    @staticmethod
    def operation_failed(request, operation, error=None):
        error_message = f"Operația {operation} nu a putut fi efectuată."
        if error:
            error_message += f" Eroare: {error}"
        messages.error(request, error_message)

    @staticmethod
    def access_denied(request):
        messages.error(request, "Nu aveți permisiunea necesară pentru această acțiune.")

    @staticmethod
    def item_not_found(request, item_type):
        messages.error(request, f"{item_type} solicitat nu a fost găsit.")

    # Document specific messages
    @staticmethod
    def document_generated(request):
        messages.success(request, "Documentul a fost generat cu succes!")

    @staticmethod
    def document_saved(request):
        messages.success(request, "Documentul a fost salvat cu succes!")

    @staticmethod
    def document_reserved(request):
        messages.info(request, "Numerele au fost rezervate cu succes!")

    # Confirmation messages
    @staticmethod
    def confirm_delete(item_type):
        return f"Sigur doriți să ștergeți acest {item_type}?"

    @staticmethod
    def confirm_generate_document():
        return "Ești sigur că vrei să generezi documentul final? Această acțiune nu poate fi anulată."

    # Form validation messages
    @staticmethod
    def required_fields_message(fields):
        return f"Următoarele câmpuri sunt obligatorii: {', '.join(fields)}"

def log_activity(user, action_type, details):
        """Înregistrează o acțiune în jurnalul de activitate."""
        try:
            # Asigură-te că user este un obiect User sau None, nu AnonymousUser
            # Verificăm dacă user este autentificat și nu e anonim
            user_instance = None
            if user and user.is_authenticated:
                # Verificăm dacă este instanță de User (nu AnonymousUser)
                if isinstance(user, User):
                    user_instance = user

            ActivityLog.objects.create(
                user=user_instance,
                action_type=action_type,
                details=details
            )
            # Poți scoate print-ul după ce confirmi că funcționează
            # print(f"LOG: User={user_instance.username if user_instance else 'System/None'}, Action={action_type}, Details={details}")
        except Exception as e:
            # Loghează eroarea de logare undeva (ex: consola, fișier separat)
            # pentru a nu opri funcționalitatea principală
            print(f"!!! ERROR logging activity: {e}")
            import traceback
            traceback.print_exc()  # Afișează mai multe detalii despre eroare în consolă