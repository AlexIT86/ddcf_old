from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import UserProfile
from .utils import log_activity
from django.contrib.auth.signals import user_logged_in, user_logged_out

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    """Înregistrează login-ul utilizatorului."""
    log_activity(user, "LOGIN", f"Utilizatorul '{user.username}' s-a autentificat.")

@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    """Înregistrează logout-ul utilizatorului."""
    # Verificăm dacă user există, deoarece semnalul poate fi trimis și la ștergere sesiune
    if user:
        log_activity(user, "LOGOUT", f"Utilizatorul '{user.username}' s-a deconectat.")