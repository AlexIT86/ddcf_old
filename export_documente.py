#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script pentru exportul documentelor generate în format CSV
"""

import sqlite3
import csv
from datetime import datetime

# Conectare la baza de date
conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()

# Query pentru a extrage documentele generate începând cu 29.10.2024
query = """
SELECT 
    gd.document_series as seria,
    gd.aviz_number as numar_aviz,
    datetime(gd.created_at, 'localtime') as data,
    gd.partner as produs,
    u.username as utilizator,
    gd.status as status
FROM certificat_generateddocument gd
LEFT JOIN auth_user u ON gd.generated_by_id = u.id
WHERE gd.created_at >= '2024-10-29 00:00:00'
  AND gd.is_deleted = 0
ORDER BY gd.created_at DESC
"""

print("Extragere date din baza de date...")
cursor.execute(query)
results = cursor.fetchall()

if not results:
    print("Nu s-au găsit documente generate de la data 29.10.2024!")
    # Verificăm ce date avem disponibile
    cursor.execute("SELECT MIN(created_at), MAX(created_at) FROM certificat_generateddocument WHERE is_deleted = 0")
    date_range = cursor.fetchone()
    print(f"Interval date disponibile: de la {date_range[0]} până la {date_range[1]}")
else:
    # Creează fișierul CSV
    output_file = f'export_documente_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    with open(output_file, 'w', newline='', encoding='utf-8-sig') as csvfile:
        writer = csv.writer(csvfile)
        
        # Header
        writer.writerow(['Seria', 'Număr Aviz', 'Data', 'Produs/Partener', 'Utilizator', 'Status'])
        
        # Date
        for row in results:
            writer.writerow(row)
    
    print(f"Export realizat cu succes!")
    print(f"Total documente exportate: {len(results)}")
    print(f"Fisier salvat: {output_file}")
    
    # Afișează primele 5 rânduri ca exemplu
    print("\nPrimele 5 documente:")
    print("-" * 100)
    for i, row in enumerate(results[:5], 1):
        print(f"{i}. Seria: {row[0]}, Aviz: {row[1]}, Data: {row[2]}, Produs: {row[3]}, User: {row[4]}")

conn.close()

