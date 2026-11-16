import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from urs.gates import Status
from urs.server import make_server
from urs.workflow import Blocked, Workflow

STAGES = [
    {'id': 'source', 'checks': [{'id': 'content', 'kind': 'automatic'}]},
    {'id': 'report', 'checks': [{'id': 'report', 'kind': 'automatic'}, {'id': 'review', 'kind': 'human'}]},
]


def content_check(content):
    return (Status.PASS if content.strip() else Status.FAIL,
            {'sha256': hashlib.sha256(content.encode()).hexdigest(), 'nonempty': bool(content.strip())})


# Isolated synthetic checks exercise gate mechanics, not real PDF/AI quality.
VALIDATORS = {(s, c): ('nonempty-fixture', '1', content_check)
              for s, c in [('source', 'content'), ('report', 'report')]}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.sqlite'
        self.w = Workflow(self.path)
        self.w.define(STAGES)
        self.w.create('job', 'fixture')

    def test_definitions_are_persistent_and_frozen(self):
        restored = Workflow(self.path)
        restored.define(STAGES)
        with self.assertRaises(Blocked):
            restored.define(STAGES[:1])
        for stages in [[], [{'id': 'x', 'checks': []}], [STAGES[0], STAGES[0]],
                       [{'id': 'x', 'checks': [{'id': 'c', 'kind': 'automatic'}] * 2}]]:
            with self.assertRaises(ValueError):
                restored.define(stages)

    def test_full_flow_persistence_and_invalidation(self):
        with self.assertRaises(Blocked):
            self.w.run('job', 'report', VALIDATORS)
        self.assertTrue(self.w.run('job', 'source', VALIDATORS))
        self.assertFalse(self.w.run('job', 'report', VALIDATORS))
        with self.assertRaises(Blocked):
            self.w.approve('job', 1, 'reviewer')
        self.w.review('job', 'report', 'review', 1, 'reviewer', 'inspected fixture output')
        self.w.approve('job', 1, 'reviewer')
        restored = Workflow(self.path)
        self.assertTrue(restored.snapshot('job')['approved'])
        for r in restored.snapshot('job')['results']:
            self.assertEqual(r['digest'], hashlib.sha256(r['evidence'].encode()).hexdigest())
            self.assertTrue(r['created'] and r['validator'] and r['version'])
        restored.edit('job', 1, 'new')
        state = restored.snapshot('job')
        self.assertFalse(state['approved'])
        self.assertEqual(state['results'], [])
        self.assertFalse(any(s['passed'] for s in state['stages']))
        self.assertTrue(any(e['action'] == 'approved' for e in state['events']))
        with self.assertRaises(Blocked):
            restored.run('job', 'report', VALIDATORS)
        with self.assertRaises(Blocked):
            restored.approve('job', 1, 'reviewer')

    def test_cannot_forge_automatic_pass(self):
        with self.assertRaises(Blocked):
            self.w.review('job', 'source', 'content', 1, 'reviewer', 'pretend pass')
        self.assertFalse(self.w.run('job', 'source', {}))
        self.assertEqual(self.w.snapshot('job')['results'][0]['status'], 'NOT_IMPLEMENTED')

    def test_all_nonpassing_statuses_block_next_stage(self):
        for status in Status:
            if status == Status.PASS:
                continue
            validators = {('source', 'content'): ('fixture', '1', lambda text, s=status: (s, {'reason': 'test'}))}
            self.assertFalse(self.w.run('job', 'source', validators))
            with self.assertRaises(Blocked):
                self.w.run('job', 'report', VALIDATORS)

    def test_concurrent_edit_during_validation_rejects_result(self):
        def racing(content):
            Workflow(self.path).edit('job', 1, 'edited while running')
            return Status.PASS, {'reason': 'old input'}
        with self.assertRaises(Blocked):
            self.w.run('job', 'source', {('source', 'content'): ('racing', '1', racing)})
        self.assertEqual(self.w.snapshot('job')['results'], [])

    def test_validator_exception_fails_closed(self):
        def broken(content):
            raise RuntimeError('secret details must not leak')
        self.assertFalse(self.w.run('job', 'source', {('source', 'content'): ('broken', '1', broken)}))
        self.assertNotIn('secret details', str(self.w.snapshot('job')))

    def test_rerun_clears_downstream_and_approval(self):
        self.w.run('job', 'source', VALIDATORS)
        self.w.run('job', 'report', VALIDATORS)
        self.w.review('job', 'report', 'review', 1, 'r', 'checked')
        self.w.approve('job', 1, 'r')
        self.w.run('job', 'source', VALIDATORS)
        snapshot = self.w.snapshot('job')
        self.assertFalse(snapshot['approved'])
        self.assertEqual(len(snapshot['results']), 1)

    def test_http_sequence_and_forgery(self):
        token = 'test-internal-token-' + 'x' * 32
        server = make_server(self.w, VALIDATORS, token)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}/jobs/job'
        def request(action, body=None, authorized=True):
            headers = {'Content-Type': 'application/json'}
            if authorized:
                headers['Authorization'] = 'Bearer ' + token
            req = urllib.request.Request(base + action, data=None if body is None else json.dumps(body).encode(), headers=headers)
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.load(r)
            except urllib.error.HTTPError as e:
                return e.code, json.load(e)
        self.assertEqual(request('', authorized=False)[0], 401)
        self.assertEqual(request('/run', {'stage': 'report'})[0], 409)
        self.assertEqual(request('/run', {'stage': 'source', 'status': 'PASS'})[0], 400)
        self.assertEqual(request('/run', {'stage': 'source'})[0], 200)
        self.assertEqual(request('/run', {'stage': 'report'})[0], 200)
        self.assertEqual(request('/approve', {'revision': 1})[0], 409)
        self.w.review('job', 'report', 'review', 1, 'reviewer', 'fixture inspected')
        self.assertTrue(request('/approve', {'revision': 1})[1]['approved'])
        self.assertEqual(request('/edit', {'revision': 1, 'content': 'revised'})[0], 200)
        self.assertEqual(request('/edit', {'revision': 1, 'content': 'stale'})[0], 409)
        self.assertEqual(request('/run', {'stage': 'report'})[0], 409)
        self.assertFalse(request('')[1]['approved'])


    def test_revalidation_revokes_approval_before_validator_returns(self):
        self.w.run('job', 'source', VALIDATORS)
        self.w.run('job', 'report', VALIDATORS)
        self.w.review('job','report','review',1,'reviewer','checked')
        self.w.approve('job',1,'reviewer')
        observed=[]
        def inspect(content):
            state=self.w.snapshot('job')
            observed.append(state['approved'])
            self.assertFalse(any(s['passed'] for s in state['stages']))
            return Status.PASS, {'reason':'new verification'}
        self.w.run('job','source',{('source','content'):('inspect','1',inspect)})
        self.assertEqual(observed,[False])
