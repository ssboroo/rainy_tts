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

PLANS = {
    "trial": {
        "id":"trial","name":"Trial","price_mnt":0,
        "description":"Үйлчилгээг харах үнэгүй бүртгэл","sort":0,
    },
    "starter": {
        "id":"starter","name":"Starter","price_mnt":59900,
        "description":"Хөнгөн хэрэглээ · 1 clone slot","sort":1,
    },
    "creator": {
        "id":"creator","name":"Creator","price_mnt":119900,
        "description":"Контент бүтээгч · 2 clone slot","sort":2,
    },
    "pro": {
        "id":"pro","name":"Pro","price_mnt":249900,
        "description":"Идэвхтэй хэрэглээ · 5 clone slot","sort":3,
    },
    "studio": {
        "id":"studio","name":"Studio","price_mnt":499900,
        "description":"Баг, студи · 10 clone slot","sort":4,
    },
}

PLAN_ENTITLEMENTS = {
    "trial":{"clone_limit":0},
    "starter":{"clone_limit":1},
    "creator":{"clone_limit":2},
    "pro":{"clone_limit":5},
    "studio":{"clone_limit":10},
}

def pricing_settings():
    fx=max(1.0,float(os.getenv("BILLING_USD_MNT_RATE","3700")))
    markup=max(2.0,float(os.getenv("BILLING_TARGET_MARKUP","2.0")))
    payment_fee=min(max(float(os.getenv("BILLING_PAYMENT_FEE_PERCENT","3.0"))/100,0),0.25)
    overhead=min(max(float(os.getenv("BILLING_OVERHEAD_RESERVE_PERCENT","10.0"))/100,0),0.50)
    fx_buffer=min(max(float(os.getenv("BILLING_FX_BUFFER_PERCENT","10.0"))/100,0),0.50)
    provider_base_usd=max(0.0,float(os.getenv("BILLING_PROVIDER_BASE_USD","6.0")))
    return {
        "usd_mnt_rate":fx,
        "target_markup":markup,
        "payment_fee":payment_fee,
        "overhead_reserve":overhead,
        "fx_buffer":fx_buffer,
        "provider_base_usd":provider_base_usd,
    }

def minimum_safe_plan_price_mnt():
    settings=pricing_settings()
    fixed_cost=settings["provider_base_usd"]*settings["usd_mnt_rate"]*(1+settings["fx_buffer"])
    denominator=(1-settings["payment_fee"])*(1-settings["overhead_reserve"])
    if denominator<=0:
        return math.inf
    return math.ceil((fixed_cost*settings["target_markup"])/denominator)

def safe_monthly_credits(price_mnt):
    settings=pricing_settings()
    usable=float(price_mnt)*(1-settings["payment_fee"])*(1-settings["overhead_reserve"])
    upstream_mnt_per_credit=CREDIT_USD*settings["usd_mnt_rate"]*(1+settings["fx_buffer"])
    max_credits=usable/(upstream_mnt_per_credit*settings["target_markup"])
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

def public_plan_catalog():
    public=[]
    for plan in plan_catalog():
        if plan["id"]!="trial" and not plan.get("profit_safe",False):
            continue
        item={k:v for k,v in plan.items() if k not in {"profit_safe","sort"}}
        public.append(item)
    return public

# Integer RAINY credits. Rates mirror public ElevenAPI API pricing,
# plus a platform fee for scarce custom-voice slots.
RATES = {
    "tts_per_1000_chars": 100,       # ~$0.10
    "dialogue_per_1000_chars": 100,  # conservative TTS-equivalent
    "stt_per_hour": 220,             # ~$0.22/hour
    "realtime_15min": 100,           # >= $0.0975, rounded
    "music_per_min": 150,            # ~$0.15/min
    "sfx_per_min": 120,              # ~$0.12/min
    "voice_changer_per_min": 120,    # ~$0.12/min
    "dubbing_v2_per_min": 2200,      # ~$2.20/min
    "voice_clone_flat": 1000,        # RAINY platform fee; provider plan/slot limits also apply
}

def billing_enabled():
    return os.getenv("BILLING_ENABLED","false").strip().lower() in {"1","true","yes","on"}

def plan_catalog():
    return [get_plan(key) for key in sorted(PLANS,key=lambda k:PLANS[k]["sort"])]

def estimate(tool_type, *, chars=0, seconds=0, duration_known=True):
    chars=max(0,int(chars or 0))
    seconds=max(0,float(seconds or 0))
    if tool_type=="tts":
        return max(1,math.ceil(chars*RATES["tts_per_1000_chars"]/1000))
    if tool_type=="dialogue":
        return max(1,math.ceil(chars*RATES["dialogue_per_1000_chars"]/1000))
    if tool_type=="speech_to_text":
        return max(1,math.ceil(seconds*RATES["stt_per_hour"]/3600))
    if tool_type=="realtime_stt":
        return RATES["realtime_15min"]
    if tool_type=="music":
        return max(1,math.ceil(seconds*RATES["music_per_min"]/60))
    if tool_type=="sound_effects":
        if not duration_known:
            return math.ceil(30*RATES["sfx_per_min"]/60)
        return max(1,math.ceil(seconds*RATES["sfx_per_min"]/60))
    if tool_type=="voice_changer":
        return max(1,math.ceil(seconds*RATES["voice_changer_per_min"]/60))
    if tool_type=="dubbing":
        return max(1,math.ceil(seconds*RATES["dubbing_v2_per_min"]/60))
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

def debit(user_id, credits, tool_type, reference=None, metadata=None):
    credits=max(0,int(credits))
    if not billing_enabled() or credits==0:
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

def refund(user_id, charge_id, reason="provider_failed"):
    if not charge_id or not billing_enabled():
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
