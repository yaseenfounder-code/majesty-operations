from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from .models import Base

def database(url):
    engine=create_engine(url)
    if url.startswith('sqlite'):
        @event.listens_for(engine,'connect')
        def configure(conn, record):
            conn.execute('PRAGMA foreign_keys=ON'); conn.execute('PRAGMA busy_timeout=10000')
        @event.listens_for(engine,'begin')
        def serialize(conn): conn.exec_driver_sql('BEGIN IMMEDIATE')
    Base.metadata.create_all(engine)
    return sessionmaker(engine,expire_on_commit=False)
