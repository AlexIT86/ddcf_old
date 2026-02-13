# certificat/admin.py
from django.urls import path
from django.contrib import admin
from django.utils.html import format_html
from .views import generate_docx_aviz as generate_docx
from .models import Certificat  # Adăugați această linie
from .models import DailyQuote

class CertificatAdmin(admin.ModelAdmin):
    #change_list_template = "certificat/admin/certificat_change_list.html"  # personalizat

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("generate_docx/", self.admin_site.admin_view(generate_docx), name="generate_docx"),
        ]
        return custom_urls + urls

admin.site.register(Certificat, CertificatAdmin)
class DailyQuoteAdmin(admin.ModelAdmin):
    list_display = ('text', 'author', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('text', 'author')

admin.site.register(DailyQuote, DailyQuoteAdmin)

