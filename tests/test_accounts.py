import hashlib
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import core, server, accounts

class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.old=core.DATA; core.DATA=Path(self.tmp.name)
        core.init(); accounts.ensure_schema()
        with core.db() as c:
            for uid in ('one','two'):
                c.execute('INSERT INTO users VALUES(?,?,?,?)',(uid,uid+'@example.com',core.hash_password('password-123456'),time.time()))
                c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(uid.encode()).hexdigest(),uid,'csrf',time.time()+3600))
        app=FastAPI(); accounts.register_routes(app,server.session,server.mutation_guard,lambda *a:None)
        self.client=TestClient(app); self.client.cookies.set('session','one')
        self.headers={'origin':'http://testserver','x-csrf-token':'csrf'}
    def tearDown(self):
        self.client.close(); core.DATA=self.old; self.tmp.cleanup()
    def post(self,path,data):
        return self.client.post('/api/account/'+path,json=data,headers=self.headers)
    def test_password_invalidates_sessions(self):
        self.assertEqual(self.post('password',{'current_password':'wrong','new_password':'new-password123'}).status_code,403)
        self.assertEqual(self.post('password',{'current_password':'password-123456','new_password':'new-password123'}).status_code,200)
        self.assertEqual(self.client.get('/api/account').status_code,401)
        with core.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM sessions WHERE user_id=?',('two',)).fetchone()[0],1)
    def test_reset_generic_hashed_expiring_single_use(self):
        with patch.object(accounts,'email_configured',return_value=True), patch.object(accounts,'send_reset_email') as send:
            known=self.post('reset/request',{'email':'one@example.com'})
            unknown=self.post('reset/request',{'email':'missing@example.com'})
            self.assertEqual(known.json(),unknown.json()); self.assertEqual(send.call_count,1)
            token=send.call_args.args[1]
        with core.db() as c:
            row=c.execute('SELECT * FROM account_reset_tokens').fetchone(); self.assertNotEqual(row['token_hash'],token)
        data={'token':token,'new_password':'updated-password123'}
        self.assertEqual(self.post('reset/confirm',data).status_code,200)
        self.assertEqual(self.post('reset/confirm',data).status_code,400)
        self.assertEqual(self.client.get('/api/account').status_code,401)
    def test_missing_email_configuration_is_generic_and_no_token(self):
        with patch.object(accounts,'email_configured',return_value=False), patch.object(accounts,'send_reset_email') as send:
            known=self.post('reset/request',{'email':'one@example.com'})
            unknown=self.post('reset/request',{'email':'missing@example.com'})
            self.assertEqual(known.status_code,503)
            self.assertEqual(known.json(),unknown.json())
            send.assert_not_called()
        with core.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM account_reset_tokens').fetchone()[0],0)

    def test_provider_clones_are_queued_and_unsafe_paths_preserved(self):
        outside=Path(self.tmp.name).parent/('outside-'+core.uid());outside.write_text('protected')
        try:
            with core.db() as c:
                c.execute('INSERT INTO voices VALUES(?,?,?,?,?)',('owned-provider-id','one','name','sample',time.time()))
                c.execute('INSERT INTO voices VALUES(?,?,?,?,?)',('other-provider-id','two','name','sample',time.time()))
                c.execute('INSERT INTO tool_jobs VALUES(?,?,?,?,?,?,?,?,?,?)',('tool','one','dubbing','title',__import__('json').dumps({'source_path':str(outside)}),'done',None,'{}',time.time(),time.time()))
            self.assertEqual(self.post('delete',{'password':'password-123456','confirmation':'УСТГАХ'}).status_code,200)
            self.assertTrue(outside.exists())
            with core.db() as c:
                self.assertEqual([r['voice_id'] for r in c.execute('SELECT voice_id FROM account_provider_cleanup')],['owned-provider-id'])
                self.assertIsNotNone(c.execute("SELECT id FROM voices WHERE id='other-provider-id'").fetchone())
        finally:outside.unlink(missing_ok=True)

    def test_expired_reset(self):
        with core.db() as c:
            c.execute('INSERT INTO account_reset_tokens VALUES(?,?,?,?)',(hashlib.sha256(b'expired').hexdigest(),'one',time.time()-1,time.time()-60))
        self.assertEqual(self.post('reset/confirm',{'token':'expired','new_password':'updated-password123'}).status_code,400)
    def test_delete_ownership_accounting_and_active_job(self):
        with core.db() as c:
            c.execute("INSERT INTO jobs(id,user_id,voice_id,title,payload,status,created) VALUES('job','one','v','title','{}','queued',?)",(time.time(),))
            c.execute("INSERT INTO credit_wallets VALUES('one',10,10,0,?)",(time.time(),))
        data={'password':'password-123456','confirmation':'УСТГАХ'}
        self.assertEqual(self.post('delete',data).status_code,409)
        owned=core.DATA/'artifacts'/'owned.txt'; owned.write_text('personal'); other=core.DATA/'artifacts'/'other.txt';other.write_text('other')
        with core.db() as c:
            c.execute("UPDATE jobs SET status='done' WHERE id='job'")
            for uid,path in [('one',owned),('two',other)]:
                c.execute('INSERT INTO tool_jobs VALUES(?,?,?,?,?,?,?,?,?,?)',(uid,uid,'stt','title','{}','done',None,'{}',time.time(),time.time()))
                c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?)',(uid,uid,uid,'text','x.txt','text/plain',str(path),time.time()))
        self.assertEqual(self.post('delete',data).status_code,200)
        self.assertFalse(owned.exists());self.assertTrue(other.exists())
        with core.db() as c:
            self.assertTrue(c.execute("SELECT email FROM users WHERE id='one'").fetchone()[0].endswith('@deleted.invalid'))
            self.assertEqual(c.execute("SELECT balance FROM credit_wallets WHERE user_id='one'").fetchone()[0],10)
    def test_admin_guard_and_csrf(self):
        self.assertEqual(self.client.get('/api/admin/overview').status_code,403)
        with patch.dict(os.environ,{'ADMIN_EMAILS':'one@example.com'}):
            self.assertEqual(self.client.get('/api/admin/overview').status_code,200)
        self.assertEqual(self.client.post('/api/account/password',json={}).status_code,403)

    def test_admin_bootstrap_preserves_identity_and_applies_once(self):
        password_hash=core.hash_password('bootstrap-password-123')
        with patch.dict(os.environ,{'ADMIN_EMAILS':'one@example.com','ADMIN_BOOTSTRAP_EMAIL':'ONE@example.com','ADMIN_BOOTSTRAP_PASSWORD_HASH':password_hash}):
            accounts.bootstrap_admin()
            with core.db() as c:
                row=c.execute("SELECT * FROM users WHERE email='one@example.com'").fetchone()
                self.assertEqual(row['id'],'one')
                self.assertTrue(core.verify_password('bootstrap-password-123',row['password']))
                self.assertEqual(c.execute("SELECT count(*) FROM sessions WHERE user_id='one'").fetchone()[0],0)
                c.execute("UPDATE users SET password=? WHERE id='one'",(core.hash_password('changed-password-123'),))
            accounts.bootstrap_admin()
            with core.db() as c:
                self.assertTrue(core.verify_password('changed-password-123',c.execute("SELECT password FROM users WHERE id='one'").fetchone()[0]))

    def test_admin_bootstrap_requires_allowlist_and_valid_hash(self):
        with patch.dict(os.environ,{'ADMIN_EMAILS':'one@example.com','ADMIN_BOOTSTRAP_EMAIL':'new@example.com','ADMIN_BOOTSTRAP_PASSWORD_HASH':core.hash_password('bootstrap-password-123')}):
            accounts.bootstrap_admin()
            with core.db() as c:self.assertIsNone(c.execute("SELECT id FROM users WHERE email='new@example.com'").fetchone())
        with patch.dict(os.environ,{'ADMIN_EMAILS':'new@example.com','ADMIN_BOOTSTRAP_EMAIL':'new@example.com','ADMIN_BOOTSTRAP_PASSWORD_HASH':'invalid'}):
            accounts.bootstrap_admin()
            with core.db() as c:self.assertIsNone(c.execute("SELECT id FROM users WHERE email='new@example.com'").fetchone())

    def test_admin_bootstrap_creates_reserved_account(self):
        with patch.dict(os.environ,{'ADMIN_EMAILS':'new@example.com','ADMIN_BOOTSTRAP_EMAIL':'new@example.com','ADMIN_BOOTSTRAP_PASSWORD_HASH':core.hash_password('bootstrap-password-123')}):
            accounts.bootstrap_admin()
            with core.db() as c:
                row=c.execute("SELECT * FROM users WHERE email='new@example.com'").fetchone()
                self.assertIsNotNone(row)
                self.assertTrue(core.verify_password('bootstrap-password-123',row['password']))
