"""Transactional, revision-scoped workflow storage for server-owned validators."""
import hashlib
import json
import sqlite3
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from urs.gates import Status
from urs.ai import AIBlocked,AIError


class Blocked(ValueError):
    pass


class Workflow:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS definitions(id TEXT PRIMARY KEY, position INTEGER UNIQUE, checks TEXT);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, content TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS results(job TEXT, stage TEXT, revision INTEGER, check_id TEXT,
              status TEXT, evidence TEXT, digest TEXT, validator TEXT, version TEXT, created TEXT,
              PRIMARY KEY(job,stage,revision,check_id));
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, job TEXT, revision INTEGER,
              action TEXT, detail TEXT, created TEXT);
            CREATE TABLE IF NOT EXISTS approvals(job TEXT PRIMARY KEY, revision INTEGER, reviewer TEXT);
            CREATE TABLE IF NOT EXISTS stage_runs(job TEXT,stage TEXT,revision INTEGER,token TEXT,
              PRIMARY KEY(job,stage));
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def define(self, stages):
        ids = [s['id'] for s in stages]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError('stage IDs must be unique and nonempty')
        for stage in stages:
            checks = stage['checks']
            names = [c['id'] for c in checks]
            if not stage['id'] or not names or len(set(names)) != len(names):
                raise ValueError('nonempty unique checks required')
            if any(not c['id'] or c['kind'] not in ('automatic', 'human') for c in checks):
                raise ValueError('invalid check definition')
        with self.connect() as db:
            existing = db.execute('SELECT id,checks FROM definitions ORDER BY position').fetchall()
            if existing:
                current = [{'id': r['id'], 'checks': json.loads(r['checks'])} for r in existing]
                if current != stages:
                    raise Blocked('definitions are frozen; explicit schema migration required')
                return
            for pos, stage in enumerate(stages):
                db.execute('INSERT INTO definitions VALUES(?,?,?)', (stage['id'], pos, json.dumps(stage['checks'])))

    def _event(self, db, job, revision, action, detail):
        db.execute('INSERT INTO events(job,revision,action,detail,created) VALUES(?,?,?,?,?)',
                   (job, revision, action, json.dumps(detail), datetime.now(timezone.utc).isoformat()))

    def create(self, job, content):
        with self.connect() as db:
            db.execute('INSERT INTO jobs VALUES(?,1,?)', (job, content))
            self._event(db, job, 1, 'created', {})

    def _job(self, db, job):
        row = db.execute('SELECT * FROM jobs WHERE id=?', (job,)).fetchone()
        if row is None:
            raise ValueError('unknown job')
        return row

    def edit(self, job, expected_revision, content):
        with self.connect() as db:
            row = self._job(db, job)
            if row['revision'] != expected_revision:
                raise Blocked('stale revision')
            revision = expected_revision + 1
            db.execute('UPDATE jobs SET revision=?,content=? WHERE id=?', (revision, content, job))
            db.execute('DELETE FROM approvals WHERE job=?', (job,))
            self._event(db, job, revision, 'edited_all_results_invalidated', {})
            return revision

    def _definitions(self, db):
        if hasattr(self, 'active_stages'):
            return [dict(id=s['id'],position=i,checks=json.dumps(s['checks'])) for i,s in enumerate(self.active_stages)]
        return db.execute('SELECT * FROM definitions ORDER BY position').fetchall()

    def _passed(self, db, job, revision, stage):
        checks = json.loads(stage['checks'])
        results = db.execute('SELECT * FROM results WHERE job=? AND stage=? AND revision=?',
                             (job, stage['id'], revision)).fetchall()
        by_id = {r['check_id']: r for r in results}
        for check in checks:
            r = by_id.get(check['id'])
            if r is None or r['status'] != Status.PASS.value:
                return False
            if hashlib.sha256(r['evidence'].encode()).hexdigest() != r['digest']:
                return False
        return bool(checks)

    def _entry(self, db, job, revision, stage_id):
        stages = self._definitions(db)
        for stage in stages:
            if stage['id'] == stage_id:
                return stage
            if not self._passed(db, job, revision, stage):
                raise Blocked('previous stage has not passed')
        raise ValueError('unknown stage')

    def run(self, job, stage_id, validators):
        # Validators are registered by server code, never supplied by HTTP clients.
        with self.connect() as db:
            row = self._job(db, job)
            revision, content = row['revision'], row['content']
            stage = self._entry(db, job, revision, stage_id)
            checks = json.loads(stage['checks'])
            run_token = secrets.token_hex(16)
            # Invalidate before invoking any validator: old approval/results
            # cannot remain usable while a new verification is in progress.
            downstream=[s['id'] for s in self._definitions(db) if s['position']>=stage['position']]
            for sid in downstream:
                db.execute('DELETE FROM results WHERE job=? AND revision=? AND stage=?',(job,revision,sid))
            for sid in downstream:
                db.execute('DELETE FROM stage_runs WHERE job=? AND stage=?',(job,sid))
            db.execute('INSERT INTO stage_runs VALUES(?,?,?,?)', (job,stage_id,revision,run_token))
            db.execute('DELETE FROM approvals WHERE job=?', (job,))
            self._event(db,job,revision,'validation_started',{'stage':stage_id,'token':run_token})
        outputs = []
        for check in checks:
            if check['kind'] == 'human':
                continue
            validator = validators.get((stage_id, check['id']))
            if validator is None:
                outputs.append((check['id'], Status.NOT_IMPLEMENTED, {'reason': 'validator unavailable'}, 'missing', '0'))
                continue
            name, version, function = validator
            try:
                status, evidence = function(content)
                status = Status(status)
                if not isinstance(evidence, dict) or not evidence:
                    raise ValueError('structured evidence required')
            except (AIBlocked,AIError) as exc:
                status,evidence=Status.FAIL,{'reason':str(exc),'type':type(exc).__name__}
                if getattr(exc,'diagnostics',None):evidence['api_diagnostics']=exc.diagnostics
            except Exception as exc:
                status, evidence = Status.FAIL, {'reason': 'validator exception', 'type': type(exc).__name__}
            outputs.append((check['id'], status, evidence, name, version))
        with self.connect() as db:
            if self._job(db, job)['revision'] != revision:
                raise Blocked('document changed during validation')
            active = db.execute('SELECT token FROM stage_runs WHERE job=? AND stage=? AND revision=?',
                                (job,stage_id,revision)).fetchone()
            if active is None or active['token'] != run_token:
                raise Blocked('validation was superseded')
            self._entry(db, job, revision, stage_id)
            for check, status, evidence, name, version in outputs:
                self._record(db, job, stage_id, revision, check, status, evidence, name, version)
            # Any rerun invalidates subsequent results and previous approval.
            for s in self._definitions(db):
                if s['position']>stage['position']:
                    db.execute('DELETE FROM results WHERE job=? AND revision=? AND stage=?',(job,revision,s['id']))
            db.execute('DELETE FROM approvals WHERE job=?', (job,))
            db.execute('DELETE FROM results WHERE job=? AND stage=? AND revision=? AND validator=?',
                       (job, stage_id, revision, 'human'))
            db.execute('DELETE FROM stage_runs WHERE job=? AND stage=?', (job,stage_id))
            return self._passed(db, job, revision, stage)

    def _record(self, db, job, stage, revision, check, status, evidence, validator, version):
        text = json.dumps(evidence, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(text.encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        db.execute('INSERT OR REPLACE INTO results VALUES(?,?,?,?,?,?,?,?,?,?)',
                   (job, stage, revision, check, status.value, text, digest, validator, version, now))
        self._event(db, job, revision, 'check_result', dict(stage=stage, check=check, status=status.value,
                                                          evidence=evidence, digest=digest, validator=validator, version=version))

    def review(self, job, stage_id, check_id, revision, reviewer, note):
        if not reviewer.strip() or not note.strip():
            raise ValueError('reviewer and evidence note required')
        with self.connect() as db:
            if self._job(db, job)['revision'] != revision:
                raise Blocked('stale revision')
            stage = self._entry(db, job, revision, stage_id)
            checks = json.loads(stage['checks'])
            if not any(c['id'] == check_id and c['kind'] == 'human' for c in checks):
                raise Blocked('cannot manually pass an automatic check')
            for c in checks:
                if c['kind'] == 'automatic':
                    result = db.execute('SELECT status FROM results WHERE job=? AND stage=? AND revision=? AND check_id=?',
                                        (job, stage_id, revision, c['id'])).fetchone()
                    if result is None or result['status'] != 'PASS':
                        raise Blocked('automatic checks must pass before review')
            self._record(db, job, stage_id, revision, check_id, Status.PASS,
                         {'reviewer': reviewer, 'note': note}, 'human', '1')

    def approve(self, job, revision, reviewer):
        if not reviewer.strip():
            raise ValueError('reviewer required')
        with self.connect() as db:
            if self._job(db, job)['revision'] != revision:
                raise Blocked('stale revision')
            stages = self._definitions(db)
            if not stages or not all(self._passed(db, job, revision, s) for s in stages):
                raise Blocked('all required checks must pass')
            db.execute('INSERT OR REPLACE INTO approvals VALUES(?,?,?)', (job, revision, reviewer))
            self._event(db, job, revision, 'approved', {'reviewer': reviewer})

    def snapshot(self, job):
        with self.connect() as db:
            return self._snapshot(db, job)

    def _snapshot(self, db, job):
        row = self._job(db, job)
        revision = row['revision']
        return {'id': job, 'revision': revision,
                'stages': [{'id': s['id'], 'passed': self._passed(db, job, revision, s)} for s in self._definitions(db)],
                'results': [dict(r) for r in db.execute('SELECT * FROM results WHERE job=? AND revision=?', (job, revision)) if any(s['id']==r['stage'] and any(c['id']==r['check_id'] for c in json.loads(s['checks'])) for s in self._definitions(db))],
                'approved': all(self._passed(db,job,revision,s) for s in self._definitions(db)) and db.execute('SELECT 1 FROM approvals WHERE job=? AND revision=?', (job, revision)).fetchone() is not None,
                'events': [dict(r) for r in db.execute('SELECT * FROM events WHERE job=? ORDER BY id', (job,))]}
