# Create a file called populate_quotes.py in the root directory

import os
import django

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')
django.setup()

# Import the model
from certificat.models import DailyQuote

# Initial quotes data
quotes = [
    {"text": "Drumul către succes este mereu în construcție.", "author": "Lily Tomlin"},
    {"text": "Nu contează cât de încet mergi, atâta timp cât nu te oprești.", "author": "Confucius"},
    {"text": "Succesul constă în a cădea de nouă ori și a te ridica de zece ori.", "author": "Jon Bon Jovi"},
    {"text": "Secretul succesului este să începi de unde te afli. Folosește ce ai.", "author": "Arthur Ashe"},
    {"text": "Acțiunea este cheia fundamentală a oricărui succes.", "author": "Pablo Picasso"},
    {"text": "Învață din trecut, trăiește în prezent, speră în viitor.", "author": "Albert Einstein"},
    {"text": "Viitorul aparține celor care cred în frumusețea viselor lor.", "author": "Eleanor Roosevelt"},
    {"text": "Cea mai bună pregătire pentru mâine este să faci tot ce poți azi.", "author": "H. Jackson Brown Jr."},
    {"text": "Nu aștepta, niciodată nu va fi timpul potrivit.", "author": "Napoleon Hill"},
    {"text": "Fii schimbarea pe care vrei să o vezi în lume.", "author": "Mahatma Gandhi"},
    {"text": "Singura limită pentru realizările noastre de mâine sunt îndoielile de azi.","author": "Franklin D. Roosevelt"},
    {"text": "Secretul de a merge înainte este de a începe.", "author": "Mark Twain"},
    {"text": "Nu poți traversa marea doar stând și privind apa.", "author": "Rabindranath Tagore"},
    {"text": "Viața este 10% ce ți se întâmplă și 90% cum reacționezi la aceasta.", "author": "Charles R. Swindoll"},
    {"text": "Schimbarea este legea vieții. Cei care privesc doar în trecut sau prezent vor rata cu siguranță viitorul.","author": "John F. Kennedy"},
    {"text": "Curajul înseamnă să fii înfricoșat până la moarte, dar să încaleci oricum.", "author": "John Wayne"},
    {"text": "Ce nu te doboară te face mai puternic.", "author": "Friedrich Nietzsche"},
    {"text": "Dacă șansa nu bate la ușă, construiește o ușă.", "author": "Milton Berle"},
    {"text": "Nimic nu este imposibil pentru cel care încearcă.", "author": "Alexandru cel Mare"},
    {"text": "Fiecare realizare începe cu decizia de a încerca.", "author": "Gail Devers"}
]


def populate_quotes():
    print("Populating quotes...")
    # Delete existing quotes if needed
    # DailyQuote.objects.all().delete()

    # Only add quotes that don't already exist
    existing_quotes = set(DailyQuote.objects.values_list('text', flat=True))
    counter = 0

    for quote_data in quotes:
        if quote_data['text'] not in existing_quotes:
            DailyQuote.objects.create(
                text=quote_data['text'],
                author=quote_data['author'],
                is_active=True
            )
            counter += 1

    print(f"Added {counter} new quotes to the database.")


if __name__ == '__main__':
    populate_quotes()