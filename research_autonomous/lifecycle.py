"""Research-only lifecycle and current-status alert gate for later approved integration."""
from .foundation import alert_authorized,confirmation_valid

STAGES=('IDEA','RESEARCH','IMPLEMENTATION','BACKTEST','OUT_OF_SAMPLE_VALIDATION','SHADOW_FORWARD_TEST',
        'QUALIFICATION_REVIEW','CEO_APPROVAL','PRODUCTION_SIGNALS')

def transition_allowed(before,after,evidence):
    if after in ('REJECTED','NEEDS_DATA','ARCHIVED'):return bool(evidence.get('reason'))
    if before is None:return after=='IDEA'
    if before not in STAGES or after not in STAGES or STAGES.index(after)!=STAGES.index(before)+1:return False
    if after=='OUT_OF_SAMPLE_VALIDATION':return bool(evidence.get('backtest_run_id'))
    if after=='QUALIFICATION_REVIEW':return bool(evidence.get('forward_evidence_id'))
    if after=='CEO_APPROVAL':return bool(str(evidence.get('ceo_approval') or '').strip())
    if after=='PRODUCTION_SIGNALS':return bool(evidence.get('ceo_approval')) and bool(evidence.get('approved_deployment'))
    return True

def delivery_allowed(spec_key,current_record,quote_age,bar_closed_at,entry_at,enabled=True):
    """Current lifecycle record, never stale signal flags or static EXPERIMENTAL labels."""
    row=current_record(spec_key)
    if not row:return False
    return alert_authorized(row.get('to'),row.get('approval'),enabled) and confirmation_valid(bar_closed_at,entry_at,quote_age)
