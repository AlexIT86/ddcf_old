#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script pentru modificarea seriilor de documente generate
conform tabelului din fisierul 'Serii de modificat.xlsx'
"""

import sqlite3
import openpyxl
import os
import shutil
from datetime import datetime

# ==================== CONFIGURARE ====================
EXCEL_FILE = 'Serii de modificat.xlsx'
DB_FILE = 'db.sqlite3'
MEDIA_DIR = 'media/generated_docs/'
LOG_FILE = f'log_modificare_serii_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'

# ==================== FUNCTII ====================

def log_message(message, to_console=True, to_file=True):
    """Scrie mesaje in fisier si consola"""
    # Inlocuieste caractere Unicode pentru consola Windows
    message_console = message.replace('✓', '[OK]').replace('✗', '[ERR]').replace('⚠', '[WARN]').replace('→', '->')
    
    if to_console:
        print(message_console)
    if to_file:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(message + '\n')

def create_backup():
    """Creeaza backup la baza de date"""
    backup_file = f'db_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.sqlite3'
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
        
        log_message(f"\n✓ Citite {len(mappings)} mapari din Excel")
        return mappings
    
    except Exception as e:
        log_message(f"✗ EROARE la citirea Excel: {e}")
        return []

def get_documents_by_serie(conn, serie):
    """Gaseste documentele cu o anumita serie"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, aviz_number, pdf_file, partner, created_at 
        FROM certificat_generateddocument 
        WHERE document_series = ? AND is_deleted = 0
    """, (serie,))
    return cursor.fetchall()

def update_document_serie(conn, doc_id, serie_noua):
    """Actualizeaza seria unui document"""
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE certificat_generateddocument 
        SET document_series = ? 
        WHERE id = ?
    """, (serie_noua, doc_id))
    conn.commit()

def rename_pdf_file(old_path, serie_veche, serie_noua):
    """Redenumeste fisierul PDF cu seria noua"""
    if not old_path or not os.path.exists(old_path):
        return None
    
    # Extrage numele de fisier
    dir_name = os.path.dirname(old_path)
    file_name = os.path.basename(old_path)
    
    # Inlocuieste seria veche cu seria noua in numele fisierului
    new_file_name = file_name.replace(serie_veche, serie_noua)
    new_path = os.path.join(dir_name, new_file_name)
    
    try:
        os.rename(old_path, new_path)
        return new_path
    except Exception as e:
        log_message(f"    ATENTIE: Nu s-a putut redenumi fisierul: {e}")
        return old_path

def update_pdf_path_in_db(conn, doc_id, new_path):
    """Actualizeaza calea fisierului PDF in baza de date"""
    # Extrage doar partea relativa (fara media/)
    relative_path = new_path.replace('media/', '') if 'media/' in new_path else new_path
    
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE certificat_generateddocument 
        SET pdf_file = ? 
        WHERE id = ?
    """, (relative_path, doc_id))
    conn.commit()

# ==================== MAIN ====================

def main():
    log_message("=" * 80)
    log_message(f"MODIFICARE SERII DOCUMENTE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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
    
    # 4. Procesare modificari
    log_message("\n[4/4] Procesare modificari...")
    log_message("-" * 80)
    
    total_docs_modified = 0
    total_pdfs_renamed = 0
    errors = []
    
    for i, (serie_veche, serie_noua) in enumerate(mappings, 1):
        log_message(f"\n[{i}/{len(mappings)}] Serie: {serie_veche} → {serie_noua}")
        
        # Gaseste documentele cu seria veche
        docs = get_documents_by_serie(conn, serie_veche)
        
        if not docs:
            log_message(f"  ⚠ Nu s-au gasit documente cu seria {serie_veche}")
            continue
        
        log_message(f"  → Gasite {len(docs)} documente")
        
        for doc in docs:
            doc_id, aviz, pdf_file, partner, created_at = doc
            
            try:
                # Actualizeaza seria in DB
                update_document_serie(conn, doc_id, serie_noua)
                log_message(f"  ✓ DB: Doc ID {doc_id} (Aviz: {aviz})")
                total_docs_modified += 1
                
                # Redenumeste PDF daca exista
                if pdf_file:
                    full_pdf_path = os.path.join('media', pdf_file)
                    if os.path.exists(full_pdf_path):
                        new_pdf_path = rename_pdf_file(full_pdf_path, serie_veche, serie_noua)
                        if new_pdf_path and new_pdf_path != full_pdf_path:
                            update_pdf_path_in_db(conn, doc_id, new_pdf_path)
                            log_message(f"  ✓ PDF: {os.path.basename(new_pdf_path)}")
                            total_pdfs_renamed += 1
                        else:
                            log_message(f"  → PDF: Fara modificari")
                
            except Exception as e:
                error_msg = f"  ✗ EROARE la Doc ID {doc_id}: {e}"
                log_message(error_msg)
                errors.append(error_msg)
    
    # Inchide conexiunea
    conn.close()
    
    # 5. Raport final
    log_message("\n" + "=" * 80)
    log_message("RAPORT FINAL")
    log_message("=" * 80)
    log_message(f"Total mapari procesate: {len(mappings)}")
    log_message(f"Total documente modificate in DB: {total_docs_modified}")
    log_message(f"Total fisiere PDF redenumite: {total_pdfs_renamed}")
    log_message(f"Backup creat: {backup_file}")
    log_message(f"Log salvat in: {LOG_FILE}")
    
    if errors:
        log_message(f"\n⚠ ATENTIE: {len(errors)} erori detectate!")
        log_message("\nDetalii erori:")
        for error in errors:
            log_message(error)
    else:
        log_message("\n✓ TOATE MODIFICARILE AU FOST EFECTUATE CU SUCCES!")
    
    log_message("\n" + "=" * 80)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n✗ Script intrerupt de utilizator!")
    except Exception as e:
        print(f"\n\n✗ EROARE CRITICA: {e}")
        import traceback
        traceback.print_exc()

