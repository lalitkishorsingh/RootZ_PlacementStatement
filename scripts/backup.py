"""Authenticated encrypted database snapshots. Never writes plaintext dump files."""
import argparse
import base64
import json
import logging
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime, timezone
from cryptography.fernet import Fernet
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')

def cipher():
    key = os.environ.get('BACKUP_KEY')
    if not key: raise RuntimeError('BACKUP_KEY must be supplied externally.')
    return Fernet(key.encode())

def pg_env():
    env = os.environ.copy()
    env.update(PGHOST=os.environ['DB_HOST'],PGPORT=os.getenv('DB_PORT','5432'),PGUSER=os.environ['DB_USER'],
               PGPASSWORD=os.environ['DB_PASSWORD'],PGSSLMODE=os.getenv('DB_SSLMODE','require'))
    if os.getenv('DB_SSLROOTCERT'): env['PGSSLROOTCERT']=os.environ['DB_SSLROOTCERT']
    return env

def create_snapshot():
    if os.getenv('DB_HOST'):
        result = subprocess.run(['pg_dump','--format=custom','--no-owner','--no-acl','--dbname',os.environ['DB_NAME']],
            env=pg_env(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
        payload, engine = result.stdout,'postgresql'
    else:
        with closing(sqlite3.connect(ROOT / 'dev.sqlite3')) as source, closing(sqlite3.connect(':memory:')) as target:
            source.backup(target)
            payload = target.serialize()
        engine = 'sqlite'
    content = json.dumps({'engine':engine,'created':datetime.now(timezone.utc).isoformat(),
                          'payload':base64.b64encode(payload).decode()}).encode()
    return cipher().encrypt(content)

def restore_snapshot(encrypted, target):
    data = json.loads(cipher().decrypt(encrypted))
    payload = base64.b64decode(data['payload'],validate=True)
    if data['engine']=='sqlite':
        path = Path(target).resolve()
        if path.exists(): raise RuntimeError('Restore target must not exist.')
        # Validate in memory before creating a new database file.
        with closing(sqlite3.connect(':memory:')) as db:
            db.deserialize(payload)
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise RuntimeError('Snapshot integrity failed.')
            with closing(sqlite3.connect(path)) as restored: db.backup(restored)
    elif data['engine']=='postgresql':
        import psycopg
        with psycopg.connect(host=os.environ['DB_HOST'],port=os.getenv('DB_PORT','5432'),user=os.environ['DB_USER'],
                            password=os.environ['DB_PASSWORD'],dbname=target,sslmode=os.getenv('DB_SSLMODE','require'),
                            **({'sslrootcert':os.environ['DB_SSLROOTCERT']} if os.getenv('DB_SSLROOTCERT') else {})) as db:
            count = db.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0]
            if count: raise RuntimeError('Restore only into a newly created, empty database.')
        subprocess.run(['pg_restore','--no-owner','--no-acl','--exit-on-error','--single-transaction','--dbname',target],
            env=pg_env(),input=payload,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
    else: raise RuntimeError('Unsupported snapshot format.')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation',choices=['create','restore'])
    parser.add_argument('file')
    parser.add_argument('--target',help='A new SQLite path or an empty PostgreSQL database')
    args = parser.parse_args()
    try:
        if args.operation=='create':
            path = Path(args.file); path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as out: out.write(create_snapshot())
            print('Encrypted backup created.')
        else:
            if not args.target: parser.error('--target is required for restoration')
            restore_snapshot(Path(args.file).read_bytes(),args.target)
            print('Backup restored into isolated target. Run migrations/checks, audit verification, and workflow checks before promotion.')
    except Exception:
        logging.critical('Backup or restore failed; check protected operational logs and configuration.')
        sys.exit(1)

if __name__=='__main__': main()
