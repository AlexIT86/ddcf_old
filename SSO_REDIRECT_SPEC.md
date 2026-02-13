# Specificatie SSO Cross-Site Redirect

## Descriere Generala

Mecanismul permite utilizatorilor sa navigheze intre cele doua platforme DDCF fara a fi nevoiti sa se autentifice din nou. Autentificarea se face prin token-uri semnate criptografic, valabile 30 de secunde.

## Platforme

| Platforma | Folder Server | Port | Domeniu |
|-----------|--------------|------|---------|
| Moldova Farming SRL | `C:\ddcf_old` | 8088 | `ddcf-mf.moldovafarming.ro` |
| Moldova Farming Agricultura | `C:\ddcf` | 8087 | `ddcf-mfa.moldovafarming.ro` |

## Flux de Autentificare

### Directia 1: ddcf-mf -> ddcf-mfa

```
Utilizator (logat pe ddcf-mf)
    |
    | Click pe "apasa aici" (link catre /redirect-mfa/)
    v
[ddcf-mf] View: redirect_to_mfa
    |
    | Genereaza token semnat cu TimestampSigner (username)
    | Redirect catre https://ddcf-mfa.moldovafarming.ro/sso-login/?token=...
    v
[ddcf-mfa] View: sso_login
    |
    | Verifica semnatura token-ului
    | Verifica expirarea (max 30 secunde)
    | Cauta utilizatorul dupa username
    | Apeleaza login(request, user)
    | Redirect catre /
    v
Utilizator (logat pe ddcf-mfa)
```

### Directia 2: ddcf-mfa -> ddcf-mf

```
Utilizator (logat pe ddcf-mfa)
    |
    | Click pe "apasa aici" (link catre /redirect-mf/)
    v
[ddcf-mfa] View: redirect_to_mf
    |
    | Genereaza token semnat cu TimestampSigner (username)
    | Redirect catre https://ddcf-mf.moldovafarming.ro/sso-login/?token=...
    v
[ddcf-mf] View: sso_login
    |
    | Verifica semnatura token-ului
    | Verifica expirarea (max 30 secunde)
    | Cauta utilizatorul dupa username
    | Apeleaza login(request, user)
    | Redirect catre /
    v
Utilizator (logat pe ddcf-mf)
```

## Detalii Tehnice

### Mecanism de Semnare

- Se foloseste `django.core.signing.TimestampSigner` din Django
- Token-ul contine username-ul utilizatorului, semnat cu `SECRET_KEY` din `settings.py`
- **Conditie obligatorie**: ambele proiecte trebuie sa aiba acelasi `SECRET_KEY` in `settings.py`
- Token-ul expira automat dupa **30 de secunde** (parametrul `max_age=30`)

### Structura Token-ului

```
username:timestamp:signature
```

- `username` — numele utilizatorului care face redirect-ul
- `timestamp` — momentul generarii (base62)
- `signature` — semnatura HMAC generata cu SECRET_KEY

### Securitate

- Token-ul este **one-time use implicit** (expira in 30 secunde)
- Nu se transmit parole — doar username-ul semnat criptografic
- Semnatura nu poate fi falsificata fara SECRET_KEY
- View-ul de generare token (`redirect_to_mfa` / `redirect_to_mf`) necesita `@login_required`
- View-ul de receptie (`sso_login`) nu necesita login (evident, userul nu e inca logat pe site-ul tinta)

## Fisiere Modificate

### Pe ddcf-mf (C:\ddcf_old)

| Fisier | Modificare |
|--------|-----------|
| `certificat/templates/home.html` | Adaugat link "treci pe Moldova Farming Agricultura" |
| `certificat/views.py` | Adaugat view `redirect_to_mfa` (generare token + redirect) |
| `certificat/views.py` | Adaugat view `sso_login` (verificare token + login) |
| `certificat/urls.py` | Adaugat ruta `redirect-mfa/` |
| `certificat/urls.py` | Adaugat ruta `sso-login/` |

### Pe ddcf-mfa (C:\ddcf)

| Fisier | Modificare |
|--------|-----------|
| `certificat/templates/home.html` | Adaugat link "treci pe Moldova Farming SRL" |
| `certificat/views.py` | Adaugat view `redirect_to_mf` (generare token + redirect) |
| `certificat/views.py` | Adaugat view `sso_login` (verificare token + login) |
| `certificat/urls.py` | Adaugat ruta `redirect-mf/` |
| `certificat/urls.py` | Adaugat ruta `sso-login/` |

## Rute URL

### ddcf-mf (ddcf-mf.moldovafarming.ro)

| URL | View | Descriere |
|-----|------|-----------|
| `/redirect-mfa/` | `redirect_to_mfa` | Genereaza token si redirect catre ddcf-mfa |
| `/sso-login/?token=...` | `sso_login` | Primeste token de la ddcf-mfa si autentifica userul |

### ddcf-mfa (ddcf-mfa.moldovafarming.ro)

| URL | View | Descriere |
|-----|------|-----------|
| `/redirect-mf/` | `redirect_to_mf` | Genereaza token si redirect catre ddcf-mf |
| `/sso-login/?token=...` | `sso_login` | Primeste token de la ddcf-mf si autentifica userul |

## Tratarea Erorilor

| Situatie | Comportament |
|----------|-------------|
| Token lipsa | Redirect la `/login/` |
| Token expirat (>30s) | Mesaj eroare + redirect la `/login/` |
| Semnatura invalida | Mesaj eroare + redirect la `/login/` |
| Utilizator inexistent pe platforma tinta | Mesaj eroare + redirect la `/login/` |
| Utilizator nelogat apasa link-ul | Redirect la `/login/` (datorita `@login_required`) |

## Prerequisite

1. Ambele proiecte au **acelasi SECRET_KEY** in `settings.py`
2. Userii au **acelasi username** pe ambele platforme
3. Domeniile sunt configurate in `ALLOWED_HOSTS` si `CSRF_TRUSTED_ORIGINS`
4. Ambele servere ruleaza si sunt accesibile prin domeniile respective
