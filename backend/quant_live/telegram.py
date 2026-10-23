"""Quant Labs paper-signal Telegram delivery through the existing TradeDen bot client.

Delivery is fail-closed. A queued preview is SENT only when ALL hold at delivery time:
  * TRADEDEN_QUANT_LIVE_TELEGRAM_ENABLED=1 (dedicated flag; legacy Telegram flags cannot enable it);
  * a recorded CEO delivery approval in the store (EXPERIMENTAL only; production cannot be approved);
  * the model is EXPERIMENTAL, scan-enabled, alert-enabled and inside the approval scope;
  * the signal is at most 120 seconds old;
  * the outbox row is atomically claimed QUEUED -> IN_FLIGHT (one attempt per signal).
Uncertain network outcomes become DELIVERY_UNKNOWN and are never replayed, so a signal can
never be sent twice, including across restarts. Otherwise the preview is recorded as DRY_RUN.
"""
from datetime import datetime,timezone,timedelta
from html import escape
import json
import os
import time
from .store import TIERS

DELIVERY_ENV='TRADEDEN_QUANT_LIVE_TELEGRAM_ENABLED'
MAX_AGE=120
MIN_INTERVAL=1.1
EAT=timezone(timedelta(hours=3))

def delivery_enabled():return os.getenv(DELIVERY_ENV,'').strip()=='1'

def _p(x):return format(x,'.10g')

RESEARCHERS={'claude':'Claude','codex':'Codex','kimi':'Kimi'}
OUTCOME_MAX_AGE=1800
SESSIONS={'UTC_00_07':'Asia (00-07 UTC)','UTC_07_12':'London (07-12 UTC)','UTC_12_16':'London/New York overlap (12-16 UTC)','UTC_16_24':'New York afternoon (16-24 UTC)'}

def message(s,tier=None):
    """CEO-specified format (directive of 2026-10-23, section 1.3). Only complete, confirmed signals."""
    for k in ('signal_id','lab','symbol','direction','model_name','model_version','timeframe','entry','stop_loss','take_profit','planned_rr','entry_at','deadline','risk'):
        if s.get(k) is None:raise ValueError('incomplete signal; not formatted: '+k)
    at=datetime.fromtimestamp(s['entry_at'],timezone.utc);deadline=datetime.fromtimestamp(s['deadline'],timezone.utc)
    rr='1:'+format(s['planned_rr'],'.2f')
    if s.get('net_planned_rr') is not None:rr+=' (after est. costs 1:'+format(s['net_planned_rr'],'.2f')+')'
    context=['Session: '+SESSIONS.get(s.get('session'),'unknown')]
    if s.get('atr'):context.append('risk '+_p(s['risk'])+' = '+format(s['risk']/s['atr'],'.2f')+'x model ATR')
    if s.get('spread') is not None:context.append('spread at signal '+_p(s['spread']))
    classification='EXPERIMENTAL PAPER SIGNAL'+(' · RESEARCH ONLY (no positive out-of-sample evidence)' if tier=='RESEARCH_ONLY' else '')
    return '\n'.join([
        '🔬 <b>TRADEDEN QUANT LABS SIGNAL</b>',
        '🤖 Researcher: '+RESEARCHERS.get(s['lab'],escape(s['lab'])),
        '🧠 Strategy: '+escape(s['model_name'])+' v'+escape(s['model_version']),
        '📊 Instrument: <b>'+escape(s['symbol'])+'</b>',
        '📈 Direction: <b>'+('BUY' if s['direction']=='LONG' else 'SELL')+'</b>',
        '⏰ Timeframe: '+escape(s['timeframe']),
        '🎯 Entry: '+_p(s['entry'])+' (market quote at confirmation)',
        '🛑 Stop Loss: '+_p(s['stop_loss']),
        '💰 Take Profit: '+_p(s['take_profit']),
        '⚖️ Risk/Reward: '+rr,
        '📋 <b>WHY THIS SIGNAL?</b>',
        escape(str(s.get('rationale') or 'The model supplied no rationale.')),
        escape('; '.join(context))+'.',
        '🔬 Classification: '+escape(classification),
        '⚠️ Research observation only. Not a validated trading recommendation. No broker order placed.',
        '🕒 '+at.strftime('%Y-%m-%d %H:%M UTC')+' / '+at.astimezone(EAT).strftime('%H:%M EAT')+' · time limit '+deadline.strftime('%Y-%m-%d %H:%M UTC'),
        '🆔 '+escape(s['signal_id'])])

def outcome_message(s,o):
    labels={'TP':'TAKE PROFIT hit','SL':'STOP LOSS hit','TIME_EXIT':'TIME LIMIT reached (closed at market)'}
    if o.get('status') not in labels or o.get('simulated_net_r') is None:raise ValueError('only final, resolved outcomes are reported')
    exit_at=datetime.fromtimestamp(o['exit_at'],timezone.utc) if o.get('exit_at') else None
    return '\n'.join([
        '🔬 <b>TRADEDEN QUANT LABS · SIGNAL OUTCOME</b>',
        '🤖 Researcher: '+RESEARCHERS.get(s['lab'],escape(s['lab'])),
        '🧠 Strategy: '+escape(s['model_name'])+' v'+escape(s['model_version']),
        '📊 '+escape(s['symbol'])+' · '+('BUY' if s['direction']=='LONG' else 'SELL')+' · entry '+_p(s['entry']),
        '🏁 Result: <b>'+labels[o['status']]+'</b>'+(' at '+exit_at.strftime('%Y-%m-%d %H:%M UTC') if exit_at else ''),
        '📐 Simulated result after estimated costs: <b>'+format(o['simulated_net_r'],'+.2f')+'R</b>',
        '⚠️ Paper outcome simulated from MT5 prices, not an executed trade.',
        '🆔 '+escape(s['signal_id'])])

class ExperimentalNotifier:
    def __init__(self,store,client=None,chat_id=None,sleep=time.sleep):
        self.store,self.client,self.chat_id,self.sleep=store,client,chat_id,sleep;self.calls=0;self.live=False;self._last=0.0
    def _transport(self):
        if self.client is None:
            import telegram_notifier as tn
            token,chat=os.getenv(tn.TOKEN_ENV,''),os.getenv(tn.CHAT_ENV,'').strip()
            if not token or not chat:return None
            self.client,self.chat_id=tn.TelegramClient(token),chat
        return self.client
    def process(self,now=None,snapshots=None):
        now=time.time() if now is None else now;count=0
        approval=self.store.delivery_approval();self.live=bool(delivery_enabled() and approval)
        for row in sorted(self.store.outbox(),key=lambda r:r['updated']):
            if row['state']!='QUEUED':continue
            if row['signal'].endswith('#outcome'):count+=self._outcome(row,approval,now);continue
            s=self.store.signal(row['signal']);m=self.store.model(s['lab'],s['model_key'],s['model_version'])
            tier=self.store.tier(s['lab'],s['model_key'],s['model_version']) if m else None
            if not m or m['status']!='EXPERIMENTAL' or not m['scan_enabled']:state='SUPPRESSED'
            elif now-s['entry_at']>MAX_AGE or now<s['entry_at']-5:state='EXPIRED'
            elif self.live and m['alert_enabled'] and tier and s.get('confirmed'):
                count+=self._send(s,tier,now);continue
            else:state='DRY_RUN'
            with self.store.db() as c:
                c.execute('UPDATE outbox SET state=?,body=?,updated=? WHERE signal=? AND state="QUEUED"',
                          (state,json.dumps({'outbound_calls':0,'approval':'APPROVED' if approval else 'CEO_DRY_RUN_REVIEW_REQUIRED',
                                             'delivery_flag':delivery_enabled(),'model_alert_permission':bool(m and m['alert_enabled']),'tier':tier}),now,s['signal_id']))
            count+=1
        return count
    def _outcome(self,row,approval,now):
        base=row['signal'][:-len('#outcome')];s=self.store.signal(base)
        m=self.store.model(s['lab'],s['model_key'],s['model_version']) if s else None
        tier=self.store.tier(s['lab'],s['model_key'],s['model_version']) if m else None
        if not (self.live and m and m['status']=='EXPERIMENTAL' and m['alert_enabled'] and tier):state='DRY_RUN'
        elif now-row['updated']>OUTCOME_MAX_AGE:state='EXPIRED'
        else:
            transport=self._transport()
            if transport and self.store.claim_delivery(row['signal'],now):
                self.calls+=1
                try:result=transport.send_message(self.chat_id,row['message'],parse_mode='HTML')
                except Exception as exc:
                    status=getattr(exc,'status',None)
                    self.store.finish_delivery(row['signal'],'DELIVERY_UNKNOWN' if status is None else 'FAILED',{'error':str(exc)[:300],'status':status},time.time());return 1
                self.store.finish_delivery(row['signal'],'SENT',{'message_id':(result or {}).get('message_id'),'sent_at':time.time()},time.time());return 1
            state='DRY_RUN'
        with self.store.db() as c:c.execute('UPDATE outbox SET state=?,body=?,updated=? WHERE signal=? AND state="QUEUED"',(state,json.dumps({'outbound_calls':0,'kind':'OUTCOME'}),now,row['signal']))
        return 1
    def _send(self,s,tier,now):
        transport=self._transport()
        if transport is None:
            with self.store.db() as c:c.execute('UPDATE outbox SET state="DRY_RUN",body=?,updated=? WHERE signal=? AND state="QUEUED"',(json.dumps({'reason':'TELEGRAM_NOT_CONFIGURED','outbound_calls':0}),now,s['signal_id']))
            return 1
        try:text=message(s,tier)
        except ValueError as exc:
            with self.store.db() as c:c.execute('UPDATE outbox SET state="SUPPRESSED",body=?,updated=? WHERE signal=? AND state="QUEUED"',(json.dumps({'reason':str(exc)}),now,s['signal_id']))
            return 1
        if not self.store.claim_delivery(s['signal_id'],now):return 0
        wait=MIN_INTERVAL-(time.monotonic()-self._last)
        if wait>0:self.sleep(wait)
        self._last=time.monotonic();self.calls+=1
        try:result=transport.send_message(self.chat_id,text,parse_mode='HTML')
        except Exception as exc:
            status=getattr(exc,'status',None)
            # No HTTP status: the request may have reached Telegram. Never replay it.
            state='DELIVERY_UNKNOWN' if status is None else 'FAILED'
            self.store.finish_delivery(s['signal_id'],state,{'error':str(exc)[:300],'status':status,'tier':tier},time.time());return 1
        self.store.finish_delivery(s['signal_id'],'SENT',{'message_id':(result or {}).get('message_id'),'tier':tier,'sent_at':time.time()},time.time())
        return 1

class ApprovedTelegramAdapter:
    """Retained contract: refuses to send without an explicit activation approval object."""
    def __init__(self,existing_client,chat_id,approval=None):self.client,self.chat_id,self.approval=existing_client,chat_id,approval
    def send(self,text):
        if not self.approval or self.approval.get('activation_approved') is not True:raise PermissionError('CEO activation approval is required')
        return self.client.send_message(self.chat_id,text,parse_mode='HTML')
