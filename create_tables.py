from app.database import engine
from app.models import Base

print("Database tables create ho rahi hain...")

# Yeh command models.py ki saari tables ko DB mein push kar degi
Base.metadata.create_all(bind=engine)

print("Tables successfully create ho gayin!")
