"""Private account snapshots and conservative reconciliation of measured usage.

Provider credits are NOT USD. The conversion is a subscription allocation estimate,
not an invoice for an individual request. Never dilute cost using rollover/promos.
"""
import asyncio
import json
import logging
import math
import os
import time
import sqlite3
from . import core

MAX_AGE = 900
_lock = asyncio.Lock()

def read(fresh=False):
    try:
        with core.db() as c:
            row=c.execute('SELECT payload FROM provider_account_snapshot WHERE id=1').fetchone()
        value=json.loads(row['payload']) if row else None
        if fresh and value and (not value.get('refresh_ok',True) or not 0<=time.time()-value['updated']<=MAX_AGE):
            return None
        return value
    except (sqlite3.Error,ValueError,KeyError):
        return None

async def refresh(api,force=False):
    async with _lock:
        old=read()
        if not force and old and old.get('refresh_ok',True) and 0<=time.time()-old['updated']<300:
            return old
        try:
            from .billing import ELEVENLABS_PROVIDER_PLANS
            usage_cutoff=time.time()
            raw=await api.subscription()
            tier=str(raw.get('tier','')).lower()
            if tier not in ELEVENLABS_PROVIDER_PLANS:
                raise ValueError('Unsupported paid subscription')
            meta=ELEVENLABS_PROVIDER_PLANS[tier]
            limit=int(raw['character_limit']);used=int(raw['character_count'])
            if limit<=0 or used<0: raise ValueError('Invalid provider balance')
            # API limit may contain rollover; do not value that as a recurring quota.
            quota=min(limit,int(meta['monthly_credits']))
            monthly=float(meta['price_usd'])
            invoice=raw.get('next_invoice') or {}
            if str(raw.get('currency','')).lower()=='usd' and raw.get('billing_period')=='monthly_period':
                amount=float(invoice.get('amount_due_cents',0))/100
                if math.isfinite(amount): monthly=max(monthly,amount)
            reset=raw.get('next_character_count_reset_unix')
            status='free' if tier=='free' else str(raw.get('status','unknown'))
            snapshot={
                'tier':tier,'status':status,'used_credits':used,'limit_credits':limit,
                'remaining_credits':max(0,limit-used),'monthly_quota':quota,
                'monthly_cost_usd':monthly,'usd_per_provider_credit':monthly/quota,
                'cost_basis':'conservative_subscription_allocation',
                'next_reset_unix':int(reset) if reset else None,
                'overage_enabled':bool(raw.get('can_extend_character_limit')) and raw.get('max_credit_limit_extension',0)!=0,
                'updated':time.time(),'usage_cutoff':usage_cutoff,'refresh_ok':True,
            }
            with core.db() as c:
                c.execute('INSERT OR REPLACE INTO provider_account_snapshot(id,payload) VALUES(1,?)',(json.dumps(snapshot),))
            logging.warning('Provider cost snapshot: tier=%s remaining=%s cost_usd=%s status=%s',tier,snapshot['remaining_credits'],monthly,status)
            return snapshot
        except Exception as exc:
            # Never persist or log upstream error bodies / account credentials.
            logging.warning('Provider cost refresh failed (%s); retaining safe fallback',type(exc).__name__)
            if old:
                old={**old,'refresh_ok':False}
                with core.db() as c:
                    c.execute('INSERT OR REPLACE INTO provider_account_snapshot(id,payload) VALUES(1,?)',(json.dumps(old),))
            return old

def reconciliation(snapshot=None):
    snapshot=snapshot or read(fresh=True)
    result={'samples':0,'measured_provider_credits':0.0,'allocated_cost_usd':0.0,'cost_factor':1.0}
    if not snapshot or snapshot.get('status') not in {'active','trialing'}:
        return result
    with core.db() as c:
        rows=c.execute("""SELECT p.metadata,l.delta,j.payload FROM provider_usage p
            LEFT JOIN credit_ledger l ON l.reference=p.job_id AND l.user_id=p.user_id AND l.kind='usage'
            LEFT JOIN jobs j ON j.id=p.job_id AND j.user_id=p.user_id
            WHERE p.created>? AND p.provider_cost IS NULL
            AND NOT EXISTS(SELECT 1 FROM credit_ledger r WHERE r.reference=l.id AND r.kind='refund')
            ORDER BY p.created DESC LIMIT 500""",(time.time()-30*86400,)).fetchall()
    for row in rows:
        try:
            credits=float(json.loads(row['metadata']).get('character_cost'))
            if row['delta'] is not None:
                reserved=abs(int(row['delta']))
            elif row['payload']:
                # Admin test jobs consume upstream credits too. Use their
                # normal quote to calibrate pricing without charging the admin.
                from . import billing, voice_direction
                payload=json.loads(row['payload'])
                chars=sum(map(len,voice_direction.segments(payload)))
                multiplier=float(payload.get('billing',{}).get('voice_multiplier',1))
                reserved=max(1,math.ceil(billing.estimate('tts',chars=chars,model_id=payload.get('model_id'))*multiplier))
            else:
                continue
            if not math.isfinite(credits) or credits<0 or reserved<=0: continue
        except (TypeError,ValueError): continue
        cost=credits*snapshot['usd_per_provider_credit']
        result['samples']+=1
        result['measured_provider_credits']+=credits
        result['allocated_cost_usd']+=cost
        # A higher observed cost reduces future allowances; cheap/promotional
        # requests never lower the published normal API cost floor.
        result['cost_factor']=max(result['cost_factor'],cost/(reserved*.001))
    return result

def report():
    value=read()
    if not value: return {'available':False,'status':'unverified','cost_basis':'configured_fallback'}
    fresh=read(fresh=True)
    return {'available':True,'fresh':bool(fresh),'account':value,'reconciliation':reconciliation(fresh),
            'note':'Request costs are allocated estimates; actual invoices and overage rates require reconciliation.'}

def ensure_capacity(connection,plan,user_id):
    """Reserve existing + pending promises atomically; no speculative overage.

    Legacy configured-only installations retain their conservative margin model.
    After first successful account sync, stale or suspended accounts stop sales.
    """
    if not read():
        if os.getenv('ELEVENLABS_API_KEY','').strip():
            raise ValueError('Үйлчилгээний нөөц шалгагдаагүй байна. Түр хүлээгээд дахин оролдоно уу.')
        return
    account=read(fresh=True)
    if not account or account['status'] not in {'active','trialing'}:
        raise ValueError('Үйлчилгээний нөөц шалгагдаагүй байна. Түр хүлээгээд дахин оролдоно уу.')
    factor=reconciliation(account)['cost_factor']
    balance=connection.execute('SELECT COALESCE(SUM(balance),0) FROM credit_wallets').fetchone()[0]
    pending=connection.execute("SELECT COALESCE(SUM(q.credits),0) FROM billing_order_quotes q JOIN billing_orders o ON o.id=q.order_id WHERE o.status='pending'").fetchone()[0]
    promised=balance+pending+plan['monthly_credits']
    # A debit after the account snapshot may still be queued or running and
    # therefore absent from the upstream balance. Reserve it until next sync.
    cutoff=account.get('usage_cutoff',account['updated'])
    recent=connection.execute("SELECT COALESCE(SUM(-delta),0) FROM credit_ledger WHERE kind='usage' AND created>?",(cutoff,)).fetchone()[0]
    # Earlier queued jobs are also absent from upstream balance; conservative
    # overlap with recent reservations is intentional until fresh reconciliation.
    queued=0
    for row in connection.execute("SELECT payload FROM jobs WHERE status IN ('queued','running') AND created<=?",(cutoff,)):
        try: queued+=int(json.loads(row['payload']).get('billing',{}).get('credits',0))
        except (ValueError,TypeError): pass
    for row in connection.execute("SELECT payload FROM tool_jobs WHERE status IN ('queued','running') AND created<=?",(cutoff,)):
        try: queued+=int(json.loads(row['payload']).get('billing',{}).get('credits',0))
        except (ValueError,TypeError): pass
    available_usd=max(0,account['remaining_credits']*account['usd_per_provider_credit']-(recent+queued)*.001*factor)
    if promised*.001*factor>available_usd:
        raise ValueError('Энэ багцыг авах үйлчилгээний нөөц түр хүрэлцэхгүй байна. Дараа дахин оролдоно уу.')
