#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script pentru actualizarea campului 'seria' din context_json
cu seriile noi pentru toate documentele modificate
"""

import sqlite3
import json
import openpyxl
import shutil
from datetime import datetime

# ==================== CONFIGURARE ====================
EXCEL_FILE = 'Serii de modificat.xlsx'
DB_FILE = 'db.sqlite3'
LOG_FILE = f'log_actualizare_context_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'

# ==================== FUNCTII ====================

def log_message(message, to_console=True, to_file=True):
    """Scrie mesaje in fisier si consola"""
    message_console = message.replace('✓', '[OK]').replace('✗', '[ERR]').replace('⚠', '[WARN]').replace('→', '->')
    
    if to_console:
        print(message_console)
    if to_file:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(message + '\n')

def create_backup():
    """Creeaza backup la baza de date"""
    backup_file = f'db_backup_context_{datetime.now().strftime("%Y%m%d_%H%M%S")}.sqlite3'
    try:
        shutil.copy2(DB_FILE, backup_file)
        log_message(f"✓ Backup creat: {backup_file}")
        return backup_file
    except Exception as e:
        log_message(f"✗ EROARE la crearea backup-ului: {e}")
        return None

def read_excel_mappings():
    """Citeste mappings-urile din fisierul Excel"""
    try:
        wb = openpyxl.load_workbook(EXCEL_FILE)
        ws = wb.active
        
        mappings = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:  # Skip header
                continue
            
            serie_veche = row[2] if len(row) > 2 else None
            serie_noua = row[3] if len(row) > 3 else None
            
            if serie_veche and serie_noua:
                mappings.append((serie_veche.strip(), serie_noua.strip()))
        
        log_message(f"✓ Citite {len(mappings)} mapari din Excel")
        return mappings
    
    except Exception as e:
        log_message(f"✗ EROARE la citirea Excel: {e}")
        return []

def get_documents_by_new_serie(conn, serie_noua):
    """Gaseste documentele cu seria noua (deja modificate)"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, aviz_number, context_json 
        FROM certificat_generateddocument 
        WHERE document_series = ? AND is_deleted = 0
    """, (serie_noua,))
    return cursor.fetchall()

def update_context_json_seria(conn, doc_id, serie_noua, aviz_number):
    """Actualizeaza campul 'seria' din context_json"""
    cursor = conn.cursor()
    
    # Citeste context_json curent
    cursor.execute("""
        SELECT context_json 
        FROM certificat_generateddocument 
        WHERE id = ?
    """, (doc_id,))
    
    result = cursor.fetchone()
    if not result or not result[0]:
        return False, "Context JSON este NULL"
    
    try:
        context = json.loads(result[0])
        
        # Actualizeaza campul 'seria' daca exista
        if 'seria' in context:
            seria_veche = context['seria']
            context['seria'] = serie_noua
            
            # Salveaza context-ul actualizat
            new_context_json = json.dumps(context, ensure_ascii=False, indent=2)
            cursor.execute("""
                UPDATE certificat_generateddocument 
                SET context_json = ? 
                WHERE id = ?
            """, (new_context_json, doc_id))
            conn.commit()
            
            return True, f"{seria_veche} → {serie_noua}"
        else:
            return False, "Camp 'seria' nu exista in context"
            
    except json.JSONDecodeError as e:
        return False, f"Eroare parsare JSON: {e}"
    except Exception as e:
        return False, f"Eroare: {e}"

# ==================== MAIN ====================

def main():
    log_message("=" * 80)
    log_message(f"ACTUALIZARE CONTEXT_JSON - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log_message("=" * 80)
    
    # 1. Creeaza backup
    log_message("\n[1/4] Creare backup baza de date...")
    backup_file = create_backup()
    if not backup_file:
        log_message("\n✗ SCRIPT OPRIT: Nu s-a putut crea backup-ul!")
        return
    
    # 2. Citeste mappings din Excel
    log_message("\n[2/4] Citire fisier Excel...")
    mappings = read_excel_mappings()
    if not mappings:
        log_message("\n✗ SCRIPT OPRIT: Nu s-au gasit mapari in Excel!")
        return
    
    # 3. Conectare la baza de date
    log_message("\n[3/4] Conectare la baza de date...")
    try:
        conn = sqlite3.connect(DB_FILE)
        log_message("✓ Conectat la baza de date")
    except Exception as e:
        log_message(f"✗ EROARE la conectare: {e}")
        return
    
    # 4. Procesare actualizari context_json
    log_message("\n[4/4] Actualizare context_json pentru fiecare document...")
    log_message("-" * 80)
    
    total_docs_updated = 0
    total_docs_skipped = 0
    errors = []
    
    for i, (serie_veche, serie_noua) in enumerate(mappings, 1):
        log_message(f"\n[{i}/{len(mappings)}] Serie: {serie_veche} → {serie_noua}")
        
        # Gaseste documentele cu seria noua (deja modificate anterior)
        docs = get_documents_by_new_serie(conn, serie_noua)
        
        if not docs:
            log_message(f"  ⚠ Nu s-au gasit documente cu seria {serie_noua}")
            continue
        
        log_message(f"  → Gasite {len(docs)} documente")
        
        for doc in docs:
            doc_id, aviz_number, context_json = doc
            
            success, message = update_context_json_seria(conn, doc_id, serie_noua, aviz_number)
            
            if success:
                log_message(f"  ✓ Doc ID {doc_id} (Aviz: {aviz_number}): {message}")
                total_docs_updated += 1
            else:
                log_message(f"  ⚠ Doc ID {doc_id} (Aviz: {aviz_number}): {message}")
                total_docs_skipped += 1
    
    # Inchide conexiunea
    conn.close()
    
    # 5. Raport final
    log_message("\n" + "=" * 80)
    log_message("RAPORT FINAL")
    log_message("=" * 80)
    log_message(f"Total mapari procesate: {len(mappings)}")
    log_message(f"Total context_json actualizate: {total_docs_updated}")
    log_message(f"Total documente sarite: {total_docs_skipped}")
    log_message(f"Backup creat: {backup_file}")
    log_message(f"Log salvat in: {LOG_FILE}")
    
    if errors:
        log_message(f"\n⚠ ATENTIE: {len(errors)} erori detectate!")
    else:
        log_message("\n✓ TOATE ACTUALIZARILE AU FOST EFECTUATE CU SUCCES!")
    
    log_message("\n" + "=" * 80)
    log_message("\nACUM PDF-urile se vor regenera cu seriile noi!")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n✗ Script intrerupt de utilizator!")
    except Exception as e:
        print(f"\n\n✗ EROARE CRITICA: {e}")
        import traceback
        traceback.print_exc()

