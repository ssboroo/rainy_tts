import asyncio
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
from app import core, billing

class ProviderCostTests(unittest.TestCase):
    def setUp(self):
        self.old=core.DATA; self.tmp=tempfile.TemporaryDirectory(); core.DATA=Path(self.tmp.name); core.init()
        self.env=patch.dict(os.environ,{'ELEVENLABS_PROVIDER_PLAN':'starter','BILLING_TARGET_MARKUP':'2','BILLING_EXPECTED_ACTIVE_USERS':'1'},clear=True);self.env.start()
    def tearDown(self):
        self.env.stop();core.DATA=self.old;self.tmp.cleanup()
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('app.provider_cost'),'Provider account cost integration missing')
        from app import provider_cost
        return provider_cost
    def sync(self,**changes):
        data={'tier':'starter','status':'active','character_count':1000,'character_limit':30000,'currency':'usd','next_character_count_reset_unix':time.time()+86400}
        data.update(changes)
        return asyncio.run(self.module().refresh(type('API',(),{'subscription':AsyncMock(return_value=data)})(),force=True))
    def test_real_tier_and_balance_are_saved_without_secrets(self):
        s=self.sync(tier='creator',character_limit=121000,api_key='never-store-this')
        self.assertEqual(s['remaining_credits'],120000)
        self.assertEqual(billing.pricing_settings()['provider_plan'],'creator')
        self.assertNotIn('never-store-this',json.dumps(s))
    def test_included_usage_is_not_added_to_base_subscription_twice(self):
        self.sync()
        self.assertEqual(billing.get_plan('pro')['monthly_credits'],7000)
        self.assertGreaterEqual(90000,2.2*(max(6*4070,7000*.001*4070)+90000*(1-.97*.9)))
    def test_rollover_and_first_month_discount_do_not_lower_unit_cost(self):
        s=self.sync(character_limit=90000,next_invoice={'amount_due_cents':100},billing_period='monthly_period')
        self.assertAlmostEqual(s['usd_per_provider_credit'],6/30000)
    def test_stale_snapshot_uses_conservative_old_formula(self):
        self.sync()
        with patch('app.provider_cost.time.time',return_value=time.time()+7200):
            self.assertEqual(billing.get_plan('pro')['monthly_credits'],7000)
            self.assertGreaterEqual(billing.get_plan('pro')['price_mnt'],135000)
    def test_observed_paid_usage_can_only_reduce_credit_allowance(self):
        self.sync()
        with core.db() as c:
            c.execute('INSERT INTO users VALUES(?,?,?,?)',('u','a@example.com','hash',time.time()))
        billing.grant('u',1000)
        billing.debit('u',80,'tts','j')
        core.add_provider_usage('u','j','text_to_speech',metadata={'character_cost':1000})
        self.assertEqual(billing.get_plan('pro')['monthly_credits'],7000)
        self.assertGreaterEqual(billing.get_plan('pro')['price_mnt'],180000)
    def test_refresh_error_keeps_last_good_snapshot(self):
        self.sync()
        api=type('API',(),{'subscription':AsyncMock(side_effect=RuntimeError('contains-secret'))})()
        s=asyncio.run(self.module().refresh(api,force=True))
        self.assertEqual(s['tier'],'starter')
        self.assertNotIn('contains-secret',json.dumps(s))
    def test_checkout_reserves_provider_capacity_and_freezes_credit_quote(self):
        self.sync()
        with core.db() as c:
            for uid in ['u','v']:
                c.execute('INSERT INTO users VALUES(?,?,?,?)',(uid,uid+'@example.com','hash',time.time()))
        # 29k remaining provider credits * $0.0002 = $5.8. This cannot
        # back a $6.4 RAINY usage allowance without a verified overage price.
        with self.assertRaisesRegex(ValueError,'нөөц'):
            billing.create_order('u','pro')
        self.sync(character_limit=90000)
        order=billing.create_order('u','pro')
        with self.assertRaisesRegex(ValueError,'нөөц'):
            billing.create_order('v','agency')
        # Changing pricing after checkout must not alter purchased entitlement.
        with patch.dict(os.environ,{'BILLING_TARGET_MARKUP':'3'}):
            billing.mark_order_paid(order['id'])
        self.assertEqual(billing.wallet('u')['wallet']['balance'],7000)
    def test_failed_refresh_disables_sales_and_live_cost_formula(self):
        self.sync()
        api=type('API',(),{'subscription':AsyncMock(side_effect=RuntimeError('failure'))})()
        asyncio.run(self.module().refresh(api,force=True))
        self.assertIsNone(self.module().read(fresh=True))
        self.assertGreaterEqual(billing.get_plan('pro')['price_mnt'],135000)
    def test_free_downgrade_does_not_reuse_previous_paid_account(self):
        self.sync()
        self.sync(tier='free',character_limit=10000)
        self.assertFalse(billing.pricing_settings()['provider_account_verified'])
    def test_upgrade_reserves_still_spendable_old_wallet(self):
        self.sync(character_limit=90000)
        with core.db() as c:
            c.execute('INSERT INTO users VALUES(?,?,?,?)',('u','a@example.com','hash',time.time()))
        billing.grant('u',15000)
        with self.assertRaisesRegex(ValueError,'нөөц'):
            billing.create_order('u','pro')
    def test_admin_test_usage_also_calibrates_real_cost(self):
        self.sync()
        with core.db() as c:
            c.execute('INSERT INTO users VALUES(?,?,?,?)',('u','a@example.com','hash',time.time()))
            payload=json.dumps({'text':'Сайн '*200,'model_id':'eleven_v4','billing':{'credits':0,'voice_multiplier':1}})
            c.execute('INSERT INTO jobs(id,user_id,voice_id,title,payload,status,created) VALUES(?,?,?,?,?,?,?)',('j','u','voice','test',payload,'done',time.time()))
        core.add_provider_usage('u','j','text_to_speech',metadata={'character_cost':1000})
        self.assertGreater(billing.pricing_settings()['observed_cost_factor'],1)
    def test_fixed_credit_packages_price_above_120_percent_markup(self):
        self.sync()
        plans=[p for p in billing.public_plan_catalog() if p['id']!='trial']
        self.assertEqual([p['monthly_credits'] for p in plans],[7000,16000,38000])
        self.assertEqual([p['price_mnt'] for p in plans],[90000,200000,475000])
        for p in plans:
            modeled=max(6*4070,p['monthly_credits']*.001*4070)
            self.assertGreaterEqual(p['price_mnt'],(modeled+p['price_mnt']*(1-.97*.9))*2.2)
    def test_cost_increase_raises_price_without_cutting_promised_credits(self):
        self.sync()
        with patch.dict(os.environ,{'BILLING_USD_MNT_RATE':'4500'}):
            p=billing.get_plan('pro')
        self.assertEqual(p['monthly_credits'],7000)
        self.assertGreater(p['price_mnt'],90000)
    def test_impossible_fee_configuration_hides_public_packages(self):
        self.sync()
        with patch.dict(os.environ,{'BILLING_PAYMENT_FEE_PERCENT':'25','BILLING_OVERHEAD_RESERVE_PERCENT':'50'}):
            self.assertFalse(billing.get_plan('pro')['profit_safe'])
            self.assertEqual([p['id'] for p in billing.public_plan_catalog()],['trial'])
