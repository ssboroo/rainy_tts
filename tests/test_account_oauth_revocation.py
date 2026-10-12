"""Credential replacement invalidates delegated access in the same transaction."""
import base64
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import accounts, core, mcp_remote, server


class AccountOAuthRevocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data = core.DATA
        core.DATA = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'VOICE_MCP_ENABLED': 'true', 'PUBLIC_ORIGIN': 'https://voice.example.com'})
        self.env.start()
        core.init()
        accounts.ensure_schema()
        mcp_remote.schema()
        self.verifier = 'v' * 48
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).decode().rstrip('=')
        with core.db() as c:
            for uid in ('one', 'two'):
                c.execute('INSERT INTO users VALUES(?,?,?,?)', (uid, uid+'@example.com', core.hash_password('password-123456'), time.time()))
                c.execute('INSERT INTO sessions VALUES(?,?,?,?)', (mcp_remote.digest(uid), uid, 'csrf', time.time()+3600))
                c.execute('INSERT INTO vmcp_tokens VALUES(?,?,?,?,?,?,?,0)', (mcp_remote.digest('access-'+uid), mcp_remote.digest('refresh-'+uid), 'client', uid, 'voice:read', time.time()+3600, time.time()+7200))
                c.execute('INSERT INTO vmcp_code VALUES(?,?,?,?,?,?,?)', (mcp_remote.digest('code-'+uid+'x'*30), 'client', uid, 'https://client.example/callback', challenge, 'voice:read', time.time()+120))
                c.execute('INSERT INTO vmcp_consent VALUES(?,?,?,?,?,?,?,?)', ('consent-'+uid, 'client', uid, 'https://client.example/callback', challenge, 'voice:read', '', time.time()+120))
            c.execute('INSERT INTO account_reset_tokens VALUES(?,?,?,?)', (mcp_remote.digest('reset'), 'one', time.time()+120, time.time()))
        app = FastAPI()
        accounts.register_routes(app, server.session, server.mutation_guard, lambda *args: None)
        mcp_remote.register_routes(app, server.session, lambda uid: set(), lambda *args: 1)
        self.client = TestClient(app)
        self.client.cookies.set('session', 'one')
        self.headers = {'origin': 'http://testserver', 'x-csrf-token': 'csrf'}

    def tearDown(self):
        self.client.close()
        self.env.stop()
        core.DATA = self.old_data
        self.tmp.cleanup()

    def replace_password(self, reset=False):
        path = 'reset/confirm' if reset else 'password'
        payload = {'new_password': 'updated-password123', **({'token': 'reset'} if reset else {'current_password': 'password-123456'})}
        return self.client.post('/api/account/'+path, json=payload, headers=self.headers)

    def assert_revoked(self):
        rpc = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}
        self.assertEqual(self.client.post('/mcp', headers={'Authorization': 'Bearer access-one'}, json=rpc).status_code, 401)
        self.assertEqual(self.client.post('/mcp', headers={'Authorization': 'Bearer access-two'}, json=rpc).status_code, 200)
        self.assertEqual(self.client.post('/oauth/token', data={'grant_type': 'refresh_token', 'client_id': 'client', 'refresh_token': 'refresh-one'}).status_code, 400)
        self.assertEqual(self.client.post('/oauth/token', data={'grant_type': 'authorization_code', 'client_id': 'client', 'code': 'code-one'+'x'*30, 'code_verifier': self.verifier, 'redirect_uri': 'https://client.example/callback'}).status_code, 400)
        with core.db() as c:
            self.assertEqual(c.execute("SELECT revoked FROM vmcp_tokens WHERE uid='one'").fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT revoked FROM vmcp_tokens WHERE uid='two'").fetchone()[0], 0)
            for table in ('vmcp_code', 'vmcp_consent'):
                self.assertEqual(c.execute(f'SELECT count(*) FROM {table} WHERE uid=?', ('one',)).fetchone()[0], 0)
                self.assertEqual(c.execute(f'SELECT count(*) FROM {table} WHERE uid=?', ('two',)).fetchone()[0], 1)

    def test_password_change_revokes_only_owned_oauth_access(self):
        self.assertEqual(self.replace_password().status_code, 200)
        self.assert_revoked()

    def test_password_reset_revokes_only_owned_oauth_access(self):
        self.assertEqual(self.replace_password(reset=True).status_code, 200)
        self.assert_revoked()

    def test_failed_revocation_rolls_back_credentials_sessions_and_reset_token(self):
        for reset in (False, True):
            with self.subTest(reset=reset):
                with core.db() as c:
                    c.execute("CREATE TRIGGER reject_revocation BEFORE UPDATE ON vmcp_tokens BEGIN SELECT RAISE(ABORT, 'revocation failed'); END")
                with self.assertRaisesRegex(sqlite3.IntegrityError, 'revocation failed'):
                    self.replace_password(reset=reset)
                with core.db() as c:
                    self.assertTrue(core.verify_password('password-123456', c.execute("SELECT password FROM users WHERE id='one'").fetchone()[0]))
                    self.assertEqual(c.execute("SELECT count(*) FROM sessions WHERE user_id='one'").fetchone()[0], 1)
                    self.assertEqual(c.execute("SELECT count(*) FROM account_reset_tokens WHERE user_id='one'").fetchone()[0], 1)
                    self.assertEqual(c.execute("SELECT revoked FROM vmcp_tokens WHERE uid='one'").fetchone()[0], 0)
                    self.assertEqual(c.execute("SELECT count(*) FROM vmcp_code WHERE uid='one'").fetchone()[0], 1)
                    c.execute('DROP TRIGGER reject_revocation')

    def check_missing_mcp_tables(self, reset):
        with core.db() as c:
            for table in ('vmcp_tokens', 'vmcp_code', 'vmcp_consent'):
                c.execute(f'DROP TABLE {table}')
        self.assertEqual(self.replace_password(reset=reset).status_code, 200)
        with core.db() as c:
            self.assertTrue(core.verify_password('updated-password123', c.execute("SELECT password FROM users WHERE id='one'").fetchone()[0]))

    def test_password_change_works_before_mcp_tables_exist(self):
        self.check_missing_mcp_tables(False)

    def test_password_reset_works_before_mcp_tables_exist(self):
        self.check_missing_mcp_tables(True)

    def test_bootstrap_password_replacement_revokes_owned_access(self):
        with patch.dict(os.environ, {'ADMIN_EMAILS': 'one@example.com', 'ADMIN_BOOTSTRAP_EMAIL': 'one@example.com', 'ADMIN_BOOTSTRAP_PASSWORD_HASH': core.hash_password('updated-password123')}):
            accounts.bootstrap_admin()
        self.assert_revoked()

    def token_form(self, refresh):
        if refresh:
            return {'grant_type': 'refresh_token', 'client_id': 'client', 'refresh_token': 'refresh-one'}
        return {'grant_type': 'authorization_code', 'client_id': 'client', 'code': 'code-one'+'x'*30, 'code_verifier': self.verifier, 'redirect_uri': 'https://client.example/callback'}

    def check_issuance_reset_boundary(self, refresh):
        original_db = core.db
        reset_results = []
        fired = False

        @contextmanager
        def reset_after_commit():
            nonlocal fired
            with original_db() as c:
                yield c
            if not fired:
                fired = True
                reset_results.append(self.replace_password(reset=True).status_code)

        with patch.object(core, 'db', reset_after_commit):
            result = self.client.post('/oauth/token', data=self.token_form(refresh))
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(reset_results, [200])
        access = result.json()['access_token']
        rpc = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}
        self.assertEqual(self.client.post('/mcp', headers={'Authorization': 'Bearer '+access}, json=rpc).status_code, 401)

    def test_reset_at_authorization_commit_cannot_leave_new_access(self):
        self.check_issuance_reset_boundary(False)

    def test_reset_at_refresh_commit_cannot_leave_new_access(self):
        self.check_issuance_reset_boundary(True)

    def check_failed_issuance_rollback(self, refresh):
        with core.db() as c:
            c.execute("CREATE TRIGGER reject_issue BEFORE INSERT ON vmcp_tokens BEGIN SELECT RAISE(ABORT, 'issuance failed'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'issuance failed'):
            self.client.post('/oauth/token', data=self.token_form(refresh))
        with core.db() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM vmcp_code WHERE uid='one'").fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT revoked FROM vmcp_tokens WHERE uid='one'").fetchone()[0], 0)
            c.execute('DROP TRIGGER reject_issue')
        self.assertEqual(self.client.post('/oauth/token', data=self.token_form(refresh)).status_code, 200)

    def test_failed_authorization_issuance_preserves_code_for_retry(self):
        self.check_failed_issuance_rollback(False)

    def test_failed_refresh_issuance_preserves_grant_for_retry(self):
        self.check_failed_issuance_rollback(True)


if __name__ == '__main__':
    unittest.main()
