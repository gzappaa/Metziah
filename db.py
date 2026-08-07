"""
Database connection helper.
 
Reads connection details from environment variables (via a .env file if
present). Generic on purpose -- fill in real values in .env once the DB
exists; nothing here should need to change when you do.
 
Env vars expected:
    PGHOST      (default: localhost)
    PGPORT      (default: 5432)
    PGUSER
    PGPASSWORD
    PGDATABASE
"""
 
import os
 
import psycopg
from dotenv import load_dotenv
 
load_dotenv()
 
 
def get_connection():
    """
    Returns a new psycopg3 connection. Caller is responsible for closing
    it (or using it as a context manager, which is the recommended way):
 
        with get_connection() as conn:
            ...
    """
    return psycopg.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5432"),
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        dbname=os.environ["PGDATABASE"],
    )
 