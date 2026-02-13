# 🎯 Ghid Template Permisiuni per Rol

## 📋 Ce Am Implementat

Am creat un sistem de **Template de Permisiuni** pentru fiecare rol din sistem. Acum, superadminul poate:

1. **Defini permisiuni default pentru fiecare rol** (utilizator, admin, superadmin)
2. **Sincroniza automat** aceste permisiuni cu toți utilizatorii care au acel rol
3. **Modifica punctual** permisiunile individuale ale utilizatorilor, dacă e nevoie

---

## 🚀 Cum Funcționează

### Pasul 1: Accesează Pagina de Administrare
- Mergi la: `http://127.0.0.1:8000/administrare/?tab=role`
- Doar **superadmin** are acces la această funcționalitate

### Pasul 2: Editează Template-ul de Permisiuni
- În tab-ul **"Roluri"**, vei vedea lista cu toate rolurile
- Fiecare rol are un buton **"Editează Permisiuni"**
- Click pe acest buton pentru a accesa pagina de editare

### Pasul 3: Configurează Permisiunile
În pagina de editare vei găsi toate permisiunile:

#### 🔹 Permisiuni Funcționale:
- ✅ **Generare Avize/Certificate** - poate genera documente
- ✅ **Acces Certificate Generate** - poate vedea lista de certificate
- ✅ **Gestionare Plaje Numere** - poate edita plajele de numere
- ✅ **Acces Raportare** - poate accesa pagina de raportare
- ✅ **Acces Administrare** - poate accesa administrarea
- ✅ **Gestionare Gestiuni** - poate crea/edita gestiuni
- ✅ **Gestionare Tipologii** - poate crea/edita tipologii

#### 🔹 Vizualizare Documente:
- ✅ **Vede TOATE documentele** - vede toate documentele din sistem
- ❌ **Dezactivat** - vede doar documentele generate de el

### Pasul 4: Salvează și Sincronizează
- Click pe **"Salvează și Sincronizează cu Utilizatorii (X)"**
- Sistemul va:
  1. Salva permisiunile în template-ul de rol
  2. Găsi toți utilizatorii cu acel rol
  3. Copia permisiunile din rol în profilul fiecărui utilizator
  4. Afișa un mesaj de succes cu numărul de utilizatori sincronizați

---

## 🎨 Exemple de Utilizare

### Exemplu 1: Configurare Rol "Utilizator"
**Scenariu:** Vrei ca toți utilizatorii simpli să poată doar genera și vedea propriile certificate.

**Pași:**
1. Mergi la `/administrare/?tab=role`
2. Click **"Editează Permisiuni"** pentru rolul **"Utilizator"**
3. Bifează:
   - ✅ Generare Avize/Certificate
   - ✅ Acces Certificate Generate
   - ❌ Vede TOATE documentele (nebifat)
4. Salvează
5. **Rezultat:** Toți cei 8 utilizatori cu rolul "Utilizator" vor avea aceste permisiuni

### Exemplu 2: Configurare Rol "Admin"
**Scenariu:** Vrei ca adminii să vadă toate documentele și să genereze certificate.

**Pași:**
1. Mergi la `/administrare/?tab=role`
2. Click **"Editează Permisiuni"** pentru rolul **"Admin"**
3. Bifează:
   - ✅ Generare Avize/Certificate
   - ✅ Acces Certificate Generate
   - ✅ Vede TOATE documentele
4. Salvează
5. **Rezultat:** Toți cei 4 admini vor vedea toate documentele din sistem

### Exemplu 3: Modificare Punctuală
**Scenariu:** Ai sincronizat permisiunile pentru rolul "Admin", dar vrei ca UN admin să nu vadă toate documentele.

**Pași:**
1. Mergi la `/administrare/?tab=user`
2. Click **"Editează Profil"** pentru utilizatorul dorit
3. În secțiunea **"Vizualizare Documente"**, debifează **"Vede TOATE documentele"**
4. Salvează
5. **Rezultat:** Doar acel utilizator va vedea doar propriile documente, restul adminilor vor vedea toate

---

## 📊 Structura Bazei de Date

### Tabelul `certificat_role`
```sql
- id (INT)
- name (VARCHAR) - utilizator | admin | superadmin
- ok_raportare (BOOLEAN)
- ok_administrare (BOOLEAN)
- ok_aviz (BOOLEAN)
- ok_plaje (BOOLEAN)
- ok_gestiuni (BOOLEAN)
- ok_tipologii (BOOLEAN)
- ok_doc_generate (BOOLEAN)
- vede_toate_documentele (BOOLEAN)
```

### Sincronizare
Când se salvează un rol, sistemul copiază valorile din `certificat_role` în `certificat_userprofile` pentru toți utilizatorii cu acel rol.

---

## 🔒 Securitate

- Doar **superadmin** poate edita template-urile de rol
- Permisiunile sunt verificate în backend (nu doar în frontend)
- Toate modificările sunt înregistrate în `ActivityLog`
- Mesajele de success/error sunt afișate utilizatorului

---

## 🧪 Testare

### Test 1: Verifică Template-urile Curente
```bash
python test_template_rol.py
```

### Test 2: Verifică Sincronizarea
```bash
python test_sincronizare_rol.py
```

---

## 📝 Log-uri

Toate acțiunile sunt înregistrate în `ActivityLog`:
- `ACCESS_EDIT_ROLE` - acces pagină editare rol
- `ROLE_UPDATED` - rol actualizat cu succes
- `ROLE_UPDATE_FAIL` - actualizare eșuată
- `EDIT_ROLE_DENIED` - acces refuzat (non-superadmin)

---

## 🎯 Beneficii

✅ **Configurare centralizată** - setezi permisiuni o singură dată pentru fiecare rol
✅ **Sincronizare automată** - toți utilizatorii cu acel rol primesc automat permisiunile
✅ **Flexibilitate** - poți modifica punctual permisiunile individuale
✅ **Audit complet** - toate modificările sunt înregistrate
✅ **UI intuitiv** - switch-uri clare pentru fiecare permisiune

---

## 🔄 Workflow Complet

```mermaid
graph TD
    A[Superadmin] --> B[/administrare/?tab=role]
    B --> C[Click Editează Permisiuni]
    C --> D[/role/edit/ID/]
    D --> E[Modifică switch-uri permisiuni]
    E --> F[Salvează]
    F --> G[Backend: Salvează rol]
    G --> H[Backend: Găsește users cu acel rol]
    H --> I[Backend: Copiază permisiuni în fiecare UserProfile]
    I --> J[Mesaj success: X utilizatori sincronizați]
    J --> K{Modificări individuale?}
    K -->|Da| L[/userprofile/edit/ID/]
    K -->|Nu| M[Gata!]
    L --> M
```

---

## 📞 Suport

Pentru întrebări sau probleme:
- Verifică log-urile în `ActivityLog`
- Testează cu scripturile de test
- Verifică permisiunile în baza de date direct

---

**✅ IMPLEMENTARE FINALIZATĂ CU SUCCES!**

