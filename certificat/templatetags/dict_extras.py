# certificat/templatetags/dict_extras.py
from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """
    Returnează valoarea corespunzătoare cheii din dicționar.
    Dacă cheia nu există sau dicționarul nu este valid, returnează un string gol.
    """
    if isinstance(dictionary, dict):
        return dictionary.get(key, '')  # Modificat aici: default la ''
    return '' # Și aici, dacă dictionary nu e dict