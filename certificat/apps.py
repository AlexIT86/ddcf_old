from django.apps import AppConfig


class CertificatConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'certificat'

    def ready(self):
        import certificat.signals  # Asigură-te că semnalele sunt înregistrate


class CertificatConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'certificat'

    def ready(self):
        # Importă și conectează semnalele aici
        import certificat.signals