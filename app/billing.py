"""RAINY subscription, wallet and usage-credit accounting.

1 RAINY credit is modeled as USD 0.001 of upstream API cost.
Retail plan prices are in MNT and intentionally include margin for payment fees,
hosting, failed generations, support and FX movement.
"""
import json
import math
import os
import time

from . import core

CREDIT_USD = 0.001

# ElevenLabs provider subscription prices/allowances supplied on 2026-10-01.
# Creator's $11 first-month offer is promotional; recurring cost is $22.
ELEVENLABS_PROVIDER_PLANS = {
    "free": {"price_usd":0, "monthly_credits":10_000},
    "starter": {"price_usd":6, "monthly_credits":30_000},
    "creator": {"price_usd":22, "monthly_credits":121_000},
    "pro": {"price_usd":99, "monthly_credits":600_000},
    "scale": {"price_usd":299, "monthly_credits":1_800_000},
    "business": {"price_usd":990, "monthly_credits":6_000_000},
}

# RAINY customer subscription plans. Monthly credits are computed dynamically
# from price and the protected cost model rather than hard-coded.
PLANS = {
    "trial": {
        "id":"trial","name":"Trial","price_mnt":0,
        "description":"Үйлчилгээг харах үнэгүй бүртгэл","sort":0,
    },
    "starter": {
        "id":"starter","name":"Starter","price_mnt":60_000,
        "description":"Эхлэх хэрэглээ · 1 хоолой хадгалах эрх","sort":1,
    },
    "creator": {
        "id":"creator","name":"Creator","price_mnt":69_900,
        "description":"Контент бүтээгч · 2 хоолой хадгалах эрх","sort":2,
    },
    "pro": {
        "id":"pro","name":"Pro","price_mnt":60_000,
        "description":"Идэвхтэй хэрэглээ · 5 энгийн + 1 мэргэжлийн хоолой","sort":3,
    },
    "studio": {
        "id":"studio","name":"Studio","price_mnt":150_000,
        "description":"Студи, баг · 10 энгийн + 2 мэргэжлийн хоолой","sort":4,
    },
    "agency": {
        "id":"agency","name":"Agency","price_mnt":350_000,
        "description":"Байгууллага · 20 энгийн + 4 мэргэжлийн хоолой","sort":5,
    },
}

PLAN_ENTITLEMENTS = {
    "trial":{"clone_limit":0,"pvc_limit":0},
    "starter":{"clone_limit":1,"pvc_limit":0},
    "creator":{"clone_limit":2,"pvc_limit":0},
    "pro":{"clone_limit":5,"pvc_limit":1},
    "studio":{"clone_limit":10,"pvc_limit":2},
    "agency":{"clone_limit":20,"pvc_limit":4},
}

# API list prices mapped to RAINY credits: 1 RAINY credit = $0.001 upstream cost.
# Temporary v4 promo prices ($0.022 / $0.011 through Oct 12, 2026) are
# intentionally not used for customer billing; normal list prices keep the
# customer price safe after the promotion expires.
TTS_MODEL_RATES = {
    "eleven_v4": 80,                    # $0.08 / 1K chars
    "eleven_v4_turbo": 40,              # $0.04 / 1K chars
    "eleven_v3": 80,
    "eleven_v3_conversational": 40,
    "eleven_multilingual_v2": 80,
    "eleven_flash_v2_5": 40,
    "eleven_turbo_v2_5": 40,
}
TTS_FALLBACK_RATE = 80

RATES = {
    "tts_default_per_1000_chars": 80,
    "dialogue_per_1000_chars": 80,
    "stt_per_hour": 220,
    "realtime_stt_per_hour": 390,
    "agents_per_min": 80,
    "music_per_min": 150,
    "voice_isolator_per_min": 120,
    "voice_changer_per_min": 120,
    "sound_effects_per_generation": 120,
    "dubbing_v1_per_min": 330,
    "dubbing_v2_per_min": 2200,
    "voice_clone_flat": 1000,
}

def pricing_settings():
    fx=max(1.0,float(os.getenv("BILLING_USD_MNT_RATE","3700")))
    markup=max(2.0,float(os.getenv("BILLING_TARGET_MARKUP","2.0")))
    payment_fee=min(max(float(os.getenv("BILLING_PAYMENT_FEE_PERCENT","3.0"))/100,0),0.25)
    overhead=min(max(float(os.getenv("BILLING_OVERHEAD_RESERVE_PERCENT","10.0"))/100,0),0.50)
    fx_buffer=min(max(float(os.getenv("BILLING_FX_BUFFER_PERCENT","10.0"))/100,0),0.50)
    provider_plan=os.getenv("ELEVENLABS_PROVIDER_PLAN","pro").strip().lower() or "pro"
    if provider_plan not in ELEVENLABS_PROVIDER_PLANS:
        provider_plan="pro"
    provider_meta=ELEVENLABS_PROVIDER_PLANS[provider_plan]
    expected_active=max(1,int(os.getenv("BILLING_EXPECTED_ACTIVE_USERS","100")))
    fixed_per_user=max(
        float(os.getenv("BILLING_FIXED_COST_PER_ACTIVE_USER_USD","1.25")),
        float(provider_meta["price_usd"])/expected_active,
    )
    return {
        "usd_mnt_rate":fx,
        "target_markup":markup,
        "payment_fee":payment_fee,
        "overhead_reserve":overhead,
        "fx_buffer":fx_buffer,
        "provider_plan":provider_plan,
        "provider_base_usd":provider_meta["price_usd"],
        "provider_monthly_credits":provider_meta["monthly_credits"],
        "expected_active_users":expected_active,
        "fixed_cost_per_active_user_usd":fixed_per_user,
    }

def recommended_provider_plan(active_users):
    users=max(1,int(active_users or 1))
    if users<=5: return "starter"
    if users<=20: return "creator"
    if users<=100: return "pro"
    if users<=300: return "scale"
    if users<=1000: return "business"
    return "business"

def minimum_safe_plan_price_mnt():
    settings=pricing_settings()
    fixed_cost=settings["fixed_cost_per_active_user_usd"]*settings["usd_mnt_rate"]*(1+settings["fx_buffer"])
    denominator=(1-settings["payment_fee"])*(1-settings["overhead_reserve"])
    if denominator<=0:
        return math.inf
    return math.ceil((fixed_cost*settings["target_markup"])/denominator)

def safe_monthly_credits(price_mnt):
    settings=pricing_settings()
    net_revenue=float(price_mnt)*(1-settings["payment_fee"])*(1-settings["overhead_reserve"])
    total_cost_budget=net_revenue/settings["target_markup"]
    fixed_cost_mnt=settings["fixed_cost_per_active_user_usd"]*settings["usd_mnt_rate"]*(1+settings["fx_buffer"])
    variable_cost_budget=max(0.0,total_cost_budget-fixed_cost_mnt)
    upstream_mnt_per_credit=CREDIT_USD*settings["usd_mnt_rate"]*(1+settings["fx_buffer"])
    max_credits=variable_cost_budget/upstream_mnt_per_credit
    return max(0,int(max_credits//100)*100)

def get_plan(plan_id):
    base=PLANS.get(plan_id)
    if not base:
        return None
    plan=base.copy()
    if plan_id=="trial":
        plan["monthly_credits"]=max(0,int(os.getenv("BILLING_TRIAL_CREDITS","0")))
        plan["profit_safe"]=True
    else:
        plan["monthly_credits"]=safe_monthly_credits(plan["price_mnt"])
        plan["profit_safe"]=plan["price_mnt"]>=minimum_safe_plan_price_mnt()
    plan.update(PLAN_ENTITLEMENTS.get(plan_id,{}))
    return plan

def plan_catalog():
    return [get_plan(key) for key in sorted(PLANS,key=lambda k:PLANS[k]["sort"])]

def public_plan_catalog():
    public=[]
    for plan in plan_catalog():
        # Retain legacy IDs for existing subscriptions, but sell three current tiers.
        if plan["id"] in {"starter", "creator"}:
            continue
        if plan["id"]!="trial" and not plan.get("profit_safe",False):
            continue
        item={k:v for k,v in plan.items() if k not in {"profit_safe","sort"}}
        public.append(item)
    return public

def tts_rate(model_id=None):
    model=(model_id or os.getenv("ELEVENLABS_TTS_MODEL","eleven_v4")).strip().lower()
    return TTS_MODEL_RATES.get(model,TTS_FALLBACK_RATE)

def public_rate_card():
    return {
        "tts": {
            "eleven_v4":80,
            "eleven_v4_turbo":40,
            "eleven_v3":80,
            "eleven_v3_conversational":40,
            "eleven_multilingual_v2":80,
            "flash_turbo":40,
            "unit":"per_1000_chars",
        },
        "speech_to_text":{"credits":220,"unit":"per_hour"},
        "realtime_stt":{"credits":390,"unit":"per_hour"},
        "agents":{"credits":80,"unit":"per_min"},
        "music":{"credits":150,"unit":"per_min"},
        "voice_isolator":{"credits":120,"unit":"per_min"},
        "voice_changer":{"credits":120,"unit":"per_min"},
        "sound_effects":{"credits":120,"unit":"per_generation"},
        "dubbing_v1":{"credits":330,"unit":"per_min"},
        "dubbing_v2":{"credits":2200,"unit":"per_min"},
        "video_voiceover":{"credits":10,"unit":"per_started_min","minimum":10,"basis":"local_render_reserve"},
    }

def billing_enabled():
    return os.getenv("BILLING_ENABLED","true").strip().lower() in {"1","true","yes","on"}

def estimate(tool_type, *, chars=0, seconds=0, duration_known=True, model_id=None, version=None):
    chars=max(0,int(chars or 0))
    seconds=max(0,float(seconds or 0))
    if tool_type=="tts":
        return max(1,math.ceil(chars*tts_rate(model_id)/1000))
    if tool_type=="dialogue":
        return max(1,math.ceil(chars*RATES["dialogue_per_1000_chars"]/1000))
    if tool_type in {"speech_to_text","medical_stt"}:
        return max(1,math.ceil(seconds*RATES["stt_per_hour"]/3600))
    if tool_type=="realtime_stt":
        window=seconds if seconds>0 else 15*60
        return max(1,math.ceil(window*RATES["realtime_stt_per_hour"]/3600))
    if tool_type=="agents":
        return max(1,math.ceil(seconds*RATES["agents_per_min"]/60))
    if tool_type=="music":
        return max(1,math.ceil(seconds*RATES["music_per_min"]/60))
    if tool_type=="voice_isolator":
        return max(1,math.ceil(seconds*RATES["voice_isolator_per_min"]/60))
    if tool_type=="sound_effects":
        return RATES["sound_effects_per_generation"]
    if tool_type=="voice_changer":
        return max(1,math.ceil(seconds*RATES["voice_changer_per_min"]/60))
    if tool_type=="dubbing":
        key="dubbing_v1_per_min" if str(version or "v2").lower()=="v1" else "dubbing_v2_per_min"
        return max(1,math.ceil(seconds*RATES[key]/60))
    if tool_type=="voice_clone":
        return RATES["voice_clone_flat"]
    raise ValueError("Unknown billable tool.")

def ensure_wallet(user_id, trial=True):
    now=time.time()
    with core.db() as c:
        row=c.execute("SELECT * FROM credit_wallets WHERE user_id=?",(user_id,)).fetchone()
        if row:
            return dict(row)
        starting=get_plan("trial")["monthly_credits"] if trial else 0
        c.execute(
            "INSERT INTO credit_wallets(user_id,balance,lifetime_in,lifetime_out,updated) VALUES(?,?,?,?,?)",
            (user_id,starting,starting,0,now)
        )
        if starting:
            c.execute(
                "INSERT INTO credit_ledger(id,user_id,kind,delta,balance_after,tool_type,reference,metadata,created) VALUES(?,?,?,?,?,?,?,?,?)",
                (core.uid(),user_id,"trial_grant",starting,starting,None,None,json.dumps({"plan":"trial"}),now)
            )
        c.execute(
            "INSERT OR IGNORE INTO subscriptions(user_id,plan_id,status,cycle_start,cycle_end,monthly_credits,auto_renew,updated) VALUES(?,?,?,?,?,?,?,?)",
            (user_id,"trial","active",now,now+7*86400,starting,0,now)
        )
        return {"user_id":user_id,"balance":starting,"lifetime_in":starting,"lifetime_out":0,"updated":now}

def _expire_if_needed(user_id):
    now=time.time()
    with core.db() as c:
        c.execute("BEGIN IMMEDIATE")
        sub=c.execute("SELECT * FROM subscriptions WHERE user_id=?",(user_id,)).fetchone()
        if not sub or sub["status"]!="active" or float(sub["cycle_end"])>now:
            return False
        row=c.execute("SELECT balance FROM credit_wallets WHERE user_id=?",(user_id,)).fetchone()
        balance=int(row["balance"]) if row else 0
        c.execute("UPDATE subscriptions SET status='expired',updated=? WHERE user_id=?",(now,user_id))
        if row and balance:
            c.execute("UPDATE credit_wallets SET balance=0,updated=? WHERE user_id=?",(now,user_id))
            c.execute(
                "INSERT INTO credit_ledger(id,user_id,kind,delta,balance_after,tool_type,reference,metadata,created) VALUES(?,?,?,?,?,?,?,?,?)",
                (core.uid(),user_id,"cycle_expired",-balance,0,None,None,json.dumps({"plan":sub["plan_id"]}),now)
            )
        return True

def wallet(user_id):
    ensure_wallet(user_id)
    _expire_if_needed(user_id)
    with core.db() as c:
        row=c.execute("SELECT * FROM credit_wallets WHERE user_id=?",(user_id,)).fetchone()
        sub=c.execute("SELECT * FROM subscriptions WHERE user_id=?",(user_id,)).fetchone()
    return {"wallet":dict(row),"subscription":dict(sub) if sub else None}

def admin_test_mode(user_id):
    if os.getenv('ADMIN_TEST_MODE','false').strip().lower() not in {'1','true','yes','on'}:
        return False
    allowed={email.strip().lower() for email in os.getenv('ADMIN_EMAILS','').split(',') if email.strip()}
    if not allowed:return False
    with core.db() as db:row=db.execute('SELECT email FROM users WHERE id=?',(user_id,)).fetchone()
    return bool(row and row['email'].lower() in allowed)

def debit(user_id, credits, tool_type, reference=None, metadata=None):
    credits=max(0,int(credits))
    if not billing_enabled() or credits==0 or admin_test_mode(user_id):
        return None
    ensure_wallet(user_id)
    _expire_if_needed(user_id)
    now=time.time()
    with core.db() as c:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT balance,lifetime_out FROM credit_wallets WHERE user_id=?",(user_id,)).fetchone()
        if not row or row["balance"]<credits:
            balance=row["balance"] if row else 0
            raise ValueError(f"Credit хүрэлцэхгүй байна. Шаардлагатай: {credits}, үлдэгдэл: {balance}.")
        new_balance=row["balance"]-credits
        charge_id=core.uid()
        c.execute(
            "UPDATE credit_wallets SET balance=?,lifetime_out=lifetime_out+?,updated=? WHERE user_id=?",
            (new_balance,credits,now,user_id)
        )
        c.execute(
            "INSERT INTO credit_ledger(id,user_id,kind,delta,balance_after,tool_type,reference,metadata,created) VALUES(?,?,?,?,?,?,?,?,?)",
            (charge_id,user_id,"usage",-credits,new_balance,tool_type,reference,json.dumps(metadata or {},ensure_ascii=False),now)
        )
    return charge_id

def enqueue_tts(user_id, job_id, voice_id, title, payload, credits, metadata):
    """Reserve credits and the per-user queue slot in one SQLite transaction."""
    ensure_wallet(user_id)
    _expire_if_needed(user_id)
    paid = billing_enabled() and not admin_test_mode(user_id)
    now = time.time()
    with core.db() as c:
        c.execute('BEGIN IMMEDIATE')
        user=c.execute('SELECT email FROM users WHERE id=?',(user_id,)).fetchone()
        if not user or user['email'].endswith('@deleted.invalid'):
            raise ValueError('Аккаунт идэвхгүй байна.')
        active = c.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND status IN ('queued','running')",(user_id,)).fetchone()[0]
        if active >= 3:
            raise ValueError('Зэрэг 3-аас олон TTS ажил үүсгэхгүй.')
        charge_id = core.uid() if paid else None
        if paid:
            row = c.execute('SELECT balance FROM credit_wallets WHERE user_id=?',(user_id,)).fetchone()
            if row['balance'] < credits:
                raise ValueError(f"Credit хүрэлцэхгүй байна. Шаардлагатай: {credits}, үлдэгдэл: {row['balance']}.")
            balance = row['balance'] - credits
            c.execute('UPDATE credit_wallets SET balance=?,lifetime_out=lifetime_out+?,updated=? WHERE user_id=?',(balance,credits,now,user_id))
            c.execute('INSERT INTO credit_ledger VALUES(?,?,?,?,?,?,?,?,?)',
                      (charge_id,user_id,'usage',-credits,balance,'tts',job_id,json.dumps(metadata),now))
        payload['billing']={'credits':credits if paid else 0,'charge_id':charge_id,
                            'voice_multiplier':metadata['voice_multiplier'],'model_id':metadata['model_id']}
        c.execute('INSERT INTO jobs(id,user_id,voice_id,title,payload,status,created) VALUES(?,?,?,?,?,?,?)',
                  (job_id,user_id,voice_id,title,json.dumps(payload,ensure_ascii=False),'queued',now))
    return credits if paid else 0

def refund(user_id, charge_id, reason="provider_failed"):
    # A historical debit must remain refundable even if billing is later disabled.
    if not charge_id:
        return False
    now=time.time()
    with core.db() as c:
        c.execute("BEGIN IMMEDIATE")
        original=c.execute(
            "SELECT * FROM credit_ledger WHERE id=? AND user_id=? AND kind='usage'",
            (charge_id,user_id)
        ).fetchone()
        if not original:
            return False
        already=c.execute(
            "SELECT 1 FROM credit_ledger WHERE reference=? AND user_id=? AND kind='refund'",
            (charge_id,user_id)
        ).fetchone()
        if already:
            return False
        amount=abs(int(original["delta"]))
        wallet_row=c.execute("SELECT balance FROM credit_wallets WHERE user_id=?",(user_id,)).fetchone()
        new_balance=int(wallet_row["balance"])+amount
        c.execute(
            "UPDATE credit_wallets SET balance=?,lifetime_in=lifetime_in+?,updated=? WHERE user_id=?",
            (new_balance,amount,now,user_id)
        )
        c.execute(
            "INSERT INTO credit_ledger(id,user_id,kind,delta,balance_after,tool_type,reference,metadata,created) VALUES(?,?,?,?,?,?,?,?,?)",
            (core.uid(),user_id,"refund",amount,new_balance,original["tool_type"],charge_id,json.dumps({"reason":reason},ensure_ascii=False),now)
        )
    return True

def grant(user_id, credits, kind="admin_grant", reference=None, metadata=None):
    credits=max(0,int(credits))
    ensure_wallet(user_id)
    now=time.time()
    with core.db() as c:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT balance FROM credit_wallets WHERE user_id=?",(user_id,)).fetchone()
        new_balance=int(row["balance"])+credits
        c.execute(
            "UPDATE credit_wallets SET balance=?,lifetime_in=lifetime_in+?,updated=? WHERE user_id=?",
            (new_balance,credits,now,user_id)
        )
        ledger_id=core.uid()
        c.execute(
            "INSERT INTO credit_ledger(id,user_id,kind,delta,balance_after,tool_type,reference,metadata,created) VALUES(?,?,?,?,?,?,?,?,?)",
            (ledger_id,user_id,kind,credits,new_balance,None,reference,json.dumps(metadata or {},ensure_ascii=False),now)
        )
    return ledger_id

def _activate_plan_tx(c, user_id, plan_id, order_id=None, now=None):
    plan=get_plan(plan_id)
    if not plan or plan_id=="trial":
        raise ValueError("Paid plan буруу байна.")
    now=time.time() if now is None else now
    row=c.execute("SELECT balance FROM credit_wallets WHERE user_id=?",(user_id,)).fetchone()
    if not row:
        starting=0
        c.execute(
            "INSERT INTO credit_wallets(user_id,balance,lifetime_in,lifetime_out,updated) VALUES(?,?,?,?,?)",
            (user_id,starting,0,0,now)
        )
        old_balance=0
    else:
        old_balance=int(row["balance"])
    new_balance=plan["monthly_credits"]
    c.execute(
        "UPDATE credit_wallets SET balance=?,lifetime_in=lifetime_in+?,updated=? WHERE user_id=?",
        (new_balance,plan["monthly_credits"],now,user_id)
    )
    c.execute(
        "INSERT OR REPLACE INTO subscriptions(user_id,plan_id,status,cycle_start,cycle_end,monthly_credits,auto_renew,updated) VALUES(?,?,?,?,?,?,?,?)",
        (user_id,plan_id,"active",now,now+30*86400,plan["monthly_credits"],0,now)
    )
    c.execute(
        "INSERT INTO credit_ledger(id,user_id,kind,delta,balance_after,tool_type,reference,metadata,created) VALUES(?,?,?,?,?,?,?,?,?)",
        (core.uid(),user_id,"subscription_reset",new_balance-old_balance,new_balance,None,order_id,json.dumps({"plan":plan_id,"monthly_credits":plan["monthly_credits"]}),now)
    )
    return plan

def activate_plan(user_id, plan_id, order_id=None):
    ensure_wallet(user_id)
    now=time.time()
    with core.db() as c:
        c.execute("BEGIN IMMEDIATE")
        plan=_activate_plan_tx(c,user_id,plan_id,order_id,now)
    return plan.copy()

def create_order(user_id, plan_id, provider="manual"):
    plan=get_plan(plan_id)
    if not plan or plan_id=="trial":
        raise ValueError("Plan буруу байна.")
    if not plan.get("profit_safe",False):
        raise ValueError("Plan pricing хамгаалалтын доод босгыг хангахгүй байна.")
    order_id=core.uid()
    now=time.time()
    with core.db() as c:
        c.execute(
            "INSERT INTO billing_orders(id,user_id,plan_id,amount_mnt,status,provider,provider_ref,created,paid_at) VALUES(?,?,?,?,?,?,?,?,NULL)",
            (order_id,user_id,plan_id,plan["price_mnt"],"pending",provider,None,now)
        )
    return {"id":order_id,"plan_id":plan_id,"amount_mnt":plan["price_mnt"],"status":"pending","provider":provider}

def mark_order_paid(order_id, provider_ref=None):
    now=time.time()
    with core.db() as c:
        c.execute("BEGIN IMMEDIATE")
        order=c.execute("SELECT * FROM billing_orders WHERE id=?",(order_id,)).fetchone()
        if not order:
            raise ValueError("Order олдсонгүй.")
        if order["status"]=="paid":
            return dict(order)
        if order["status"]!="pending":
            raise ValueError("Order төлөв буруу байна.")
        changed=c.execute(
            "UPDATE billing_orders SET status='paid',provider_ref=?,paid_at=? WHERE id=? AND status='pending'",
            (provider_ref,now,order_id)
        )
        if changed.rowcount!=1:
            current=c.execute("SELECT * FROM billing_orders WHERE id=?",(order_id,)).fetchone()
            return dict(current)
        _activate_plan_tx(c,order["user_id"],order["plan_id"],order_id,now)
        return dict(c.execute("SELECT * FROM billing_orders WHERE id=?",(order_id,)).fetchone())

def ledger(user_id, limit=100):
    ensure_wallet(user_id)
    with core.db() as c:
        rows=c.execute(
            "SELECT id,kind,delta,balance_after,tool_type,reference,metadata,created FROM credit_ledger WHERE user_id=? ORDER BY created DESC LIMIT ?",
            (user_id,min(max(int(limit),1),200))
        ).fetchall()
    result=[]
    for row in rows:
        item=dict(row)
        try:item["metadata"]=json.loads(item["metadata"] or "{}")
        except Exception:item["metadata"]={}
        result.append(item)
    return result
