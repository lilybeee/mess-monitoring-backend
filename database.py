import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://neondb_owner:npg_yFW41YZVoQtp@ep-round-frost-a1hwa9jz.ap-southeast-1.aws.neon.tech/neondb?sslmode=require")

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Note: Some sqlalchemy engines might have issues with channel_binding parameter, 
# if so it can be omitted, but sslmode=require is kept.

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
