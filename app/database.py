import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

# .env file load karo
load_dotenv()

# Database URL fetch karo
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

# Engine banayein
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# SessionLocal class banayein jo DB sessions handle karegi
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class jisko inherit karke hum tables banayenge
Base = declarative_base()

# Dependency for FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()