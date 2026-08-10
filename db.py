"""
Database connection helper.
"""

import psycopg

from config import settings


def get_connection():
    """
    Returns a new psycopg3 connection.
    Caller is responsible for closing it.
    """
    return psycopg.connect(
        host=settings.PGHOST,
        port=settings.PGPORT,
        user=settings.PGUSER,
        password=settings.PGPASSWORD,
        dbname=settings.PGDATABASE,
    )