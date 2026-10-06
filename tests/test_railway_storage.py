from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from app import railway


class StorageBootstrapTests(unittest.TestCase):
    def test_root_volume_is_repaired_before_privileges_are_dropped(self):
        calls=[]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'data';path.mkdir();(path/'studio.db').write_bytes(b'data')
            account=types.SimpleNamespace(pw_uid=10001,pw_gid=10001)
            with patch.dict('os.environ',{'DATA_DIR':str(path)}),patch('pwd.getpwnam',return_value=account),patch('os.geteuid',side_effect=[0,10001]),patch('os.chown',side_effect=lambda *a,**k:calls.append('chown')),patch('os.setgroups',side_effect=lambda v:calls.append(('groups',v))),patch('os.setgid',side_effect=lambda v:calls.append(('gid',v))),patch('os.setuid',side_effect=lambda v:calls.append(('uid',v))):
                railway.prepare_storage()
            self.assertEqual(calls[-3:],[('groups',[]),('gid',10001),('uid',10001)])
            self.assertIn('chown',calls)

    def test_bootstrap_rejects_root_or_symlink_data(self):
        with patch('os.geteuid',return_value=0),patch('pwd.getpwnam',return_value=types.SimpleNamespace(pw_uid=10001,pw_gid=10001)),patch.dict('os.environ',{'DATA_DIR':'/'}):
            with self.assertRaises(RuntimeError):railway.prepare_storage()

    def test_existing_nonroot_runtime_needs_no_privileged_operations(self):
        with patch('os.geteuid',return_value=10001),patch('os.chown') as chown,patch('os.setuid') as uid:
            railway.prepare_storage()
            chown.assert_not_called();uid.assert_not_called()
