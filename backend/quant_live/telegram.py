"""Existing Telegram client adapter, with a separate disabled experimental outbox."""
from datetime import datetime,timezone,timedelta
from html import escape
import json
import time

def message(s):
    timestamp=datetime.fromtimestamp(s['entry_at'],timezone.utc)
    eat=timestamp.astimezone(timezone(timedelta(hours=3)))
    return '\n'.join([
        '🧪 <b>EXPERIMENTAL · '+escape(s['lab_name'])+'</b>',
        escape(s['model_name'])+' v'+escape(s['model_version']),
        '<b>'+escape(s['symbol'])+' · '+('BUY' if s['direction']=='LONG' else 'SELL')+'</b>',
        'Time: '+timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')+' / '+eat.strftime('%H:%M:%S EAT'),
        'Entry type: MARKET paper quote (not an executed order)',
        'Entry: '+format(s['entry'],'.10g'),
        'SL: '+format(s['stop_loss'],'.10g'),
        'TP: '+format(s['take_profit'],'.10g'),
        'Planned RR: 1:'+format(s['planned_rr'],'.3f'),
        'Signal ID: '+escape(s['signal_id']),
        'Input bar closed: '+datetime.fromtimestamp(s['signal_bar_closed_at'],timezone.utc).isoformat(),
        'Status: EXPERIMENTAL — no verified profitability. No broker order placed.'
    ])

class ExperimentalNotifier:
    """At most one automatic remote attempt; uncertain delivery is never replayed."""
    def __init__(self,store,client=None,chat_id=None):self.store,self.client,self.chat_id=store,client,chat_id
    def process(self,now=None,snapshots=None):
        now=time.time() if now is None else now;count=0
        for row in self.store.outbox():
            if row['state']!='QUEUED':continue
            s=self.store.signal(row['signal']);m=self.store.model(s['lab'],s['model_key'],s['model_version'])
            if not m or m['status']!='EXPERIMENTAL' or not m['scan_enabled']:state='SUPPRESSED'
            elif now-s['entry_at']>120 or now<s['entry_at']-5:state='EXPIRED'
            else:state='DRY_RUN'
            # This release deliberately has NO activation path. Existing Telegram
            # environment flags cannot enable new lab delivery, even if set to 1.
            with self.store.db() as c:
                c.execute('UPDATE outbox SET state=?,body=?,updated=? WHERE signal=? AND state="QUEUED"',
                          (state,json.dumps({'outbound_calls':0,'approval':'CEO_DRY_RUN_REVIEW_REQUIRED','model_alert_permission':bool(m and m['alert_enabled'])}),now,s['signal_id']))
            count+=1
        return count

class ApprovedTelegramAdapter:
    """Formatting/transport contract for future approved activation; not wired to runtime."""
    def __init__(self,existing_client,chat_id,approval=None):self.client,self.chat_id,self.approval=existing_client,chat_id,approval
    def send(self,text):
        if not self.approval or self.approval.get('activation_approved') is not True:raise PermissionError('CEO activation approval is required')
        return self.client.send_message(self.chat_id,text,parse_mode='HTML')
