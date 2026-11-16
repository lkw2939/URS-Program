"""Operator-only SQLite snapshots; never overwrite a working database."""
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

REQUIRED={'users','sessions','projects','documents','jobs','definitions','results','events','artifacts','page_assets','qualifications'}


def inspect_database(path):
    path=Path(path).resolve()
    if not path.is_file():raise ValueError('작업 DB 파일이 없습니다.')
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('BEGIN')
            if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('작업 DB 무결성 검사 실패')
            tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not REQUIRED.issubset(tables):raise ValueError('URS 작업 DB 형식이 아닙니다.')
            for payload,digest in db.execute('SELECT original,sha256 FROM documents'):
                if hashlib.sha256(payload).hexdigest()!=digest:raise ValueError('보관된 PDF 원본 해시가 일치하지 않습니다.')
            for job,revision,evidence,digest in db.execute('SELECT job,revision,evidence,digest FROM results'):
                if hashlib.sha256(evidence.encode()).hexdigest()!=digest:raise ValueError('검증 결과의 근거 해시가 일치하지 않습니다.')
                for kind,expected in json.loads(evidence).get('outputs',{}).items():
                    row=db.execute('SELECT payload FROM artifacts WHERE document=? AND revision=? AND kind=?',(job,revision,kind)).fetchone()
                    if row is None or hashlib.sha256(row[0]).hexdigest()!=expected:
                        raise ValueError('보고서 파일이 누락되었거나 검증 해시가 일치하지 않습니다.')
            # Page images are shared across revisions; inspect the latest extraction.
            for document,payload in db.execute('SELECT a.document,a.payload FROM artifacts a WHERE a.kind=? AND a.revision=(SELECT MAX(b.revision) FROM artifacts b WHERE b.document=a.document AND b.kind=a.kind)',('extraction',)):
                pages=json.loads(payload)['pages']
                images=dict(db.execute('SELECT page,payload FROM page_assets WHERE document=?',(document,)))
                if len(images)!=len(pages) or any(page['number'] not in images or hashlib.sha256(images[page['number']]).hexdigest()!=page['preview_sha256'] for page in pages):
                    raise ValueError('페이지 미리보기가 누락되었거나 검증 해시가 일치하지 않습니다.')
            return {'projects':db.execute('SELECT COUNT(*) FROM projects').fetchone()[0],
                    'documents':db.execute('SELECT COUNT(*) FROM documents').fetchone()[0],
                    'jobs':db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],
                    'events':db.execute('SELECT COUNT(*) FROM events').fetchone()[0]}
    except (sqlite3.Error,TypeError,AttributeError,KeyError,json.JSONDecodeError):
        raise ValueError('작업 DB를 검증할 수 없습니다.') from None


def _snapshot(source,destination,restore=False):
    source=Path(source).resolve();destination=Path(destination).absolute()
    if source==destination.resolve():raise ValueError('원본과 대상 DB 경로는 달라야 합니다.')
    inspect_database(source)
    if destination.exists() or destination.is_symlink():raise ValueError('기존 파일에는 덮어쓰지 않습니다. 새 경로를 선택하세요.')
    destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    # Exclusively reserve a new private destination before SQLite writes to it.
    descriptor=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as origin:
            with closing(sqlite3.connect(destination)) as target:
                origin.backup(target,pages=256,sleep=0.05)
                if restore:
                    # Recovered data retains users/hashes, not old login sessions.
                    target.execute('DELETE FROM sessions')
                    target.commit()
        counts=inspect_database(destination)
        with destination.open('rb') as backup_file:
            file_hash=hashlib.file_digest(backup_file,'sha256').hexdigest()
        return {'operation':'restore' if restore else 'backup','path':str(destination),**counts,
                'sha256':file_hash,
                'old_sessions_invalidated':restore}
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def backup_database(source,destination):
    return _snapshot(source,destination)


def restore_database(source,destination):
    return _snapshot(source,destination,restore=True)
