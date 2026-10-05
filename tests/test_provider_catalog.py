import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock,patch
from app import core

class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=core.DATA;core.DATA=Path(self.tmp.name)
    def tearDown(self):core.DATA=self.old;self.tmp.cleanup()
    def test_only_public_mongolian_and_default_voices_are_published(self):
        from app import provider_catalog as catalog
        fake=AsyncMock()
        fake._request.side_effect=[
            type('R',(),{'json':lambda self:[{'model_id':'eleven_v4','languages':[{'language_id':'mn'}],'can_do_text_to_speech':True}]})(),
            type('R',(),{'json':lambda self:{'voices':[{'voice_id':'native','name':'Монгол','language':'mn','public_owner_id':'owner','use_case':'narration','rate':1},{'voice_id':'foreign','name':'English','language':'en','public_owner_id':'owner'}],'has_more':False}})(),
            type('R',(),{'json':lambda self:{'voices':[{'voice_id':'default','name':'Default','category':'premade','labels':{'language':'en'}},{'voice_id':'private','name':'Private clone','category':'cloned'}],'has_more':False}})()]
        with patch.dict(os.environ,{'ELEVENLABS_API_KEY':'test'}):asyncio.run(catalog.refresh(fake))
        data=catalog.read();self.assertEqual({v['id'] for v in data['voices']},{'native','default'})
        self.assertTrue(next(v for v in data['voices'] if v['id']=='native')['native_mn'])
        self.assertFalse(next(v for v in data['voices'] if v['id']=='default')['native_mn'])
        self.assertNotIn('test',str(data));self.assertTrue(data['models'][0]['supports_mn'])
    def test_failure_keeps_last_good_catalog(self):
        from app import provider_catalog as catalog
        catalog.write({'voices':[{'id':'old'}],'models':[],'updated':1})
        fake=AsyncMock();fake._request.side_effect=RuntimeError('secret provider details')
        with patch.dict(os.environ,{'ELEVENLABS_API_KEY':'test'}):asyncio.run(catalog.refresh(fake))
        self.assertEqual(catalog.read()['voices'][0]['id'],'old')
        self.assertNotIn('secret',str(catalog.read()))

    def test_imported_default_voice_bypasses_shared_paid_gate(self):
        from app import provider_catalog as catalog,server
        core.init()
        catalog.write({'voices':[{'id':'default_voice','name':'Default','source':'default','builtin':True,'native_mn':False}]})
        with patch.object(server.tools,'subscription',AsyncMock(side_effect=AssertionError('must not query shared entitlement'))):
            self.assertEqual(asyncio.run(server.ensure_provider_voice('default_voice','user')),'default_voice')
            self.assertEqual(asyncio.run(server.voice_cost_multiplier('default_voice','user')),1.0)
    def test_catalog_refresh_requires_admin(self):
        from fastapi.testclient import TestClient
        from app import server
        core.init()
        client=TestClient(server.app)
        self.assertEqual(client.post('/api/admin/studio/catalog/refresh').status_code,401)
    def test_native_import_keeps_premade_capacity(self):
        from app import provider_catalog as catalog
        # Verify independently bounded sources retain defaults when native catalogue is large.
        fake=AsyncMock()
        R=lambda data:type('R',(),{'json':lambda self:data})()
        fake._request.side_effect=[R([]),R({'voices':[{'voice_id':'mn'+str(i),'language':'mn','public_owner_id':'owner'} for i in range(150)]}),R({'voices':[{'voice_id':'default','category':'premade'}]})]
        with patch.dict(os.environ,{'ELEVENLABS_API_KEY':'test'}):asyncio.run(catalog.refresh(fake))
        self.assertEqual(len(catalog.read()['voices']),101)
        self.assertIn('default',{v['id'] for v in catalog.read()['voices']})
