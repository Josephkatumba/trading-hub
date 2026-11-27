"""Write phase-2 manifests (frequency-expansion directive, 2026-10-20)."""
import json
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
ALL = ['XAUUSD', 'XAGUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'NZDUSD', 'USDCAD', 'USDCHF', 'EURJPY', 'GBPJPY',
       'BTCUSD', 'ETHUSD', 'NAS100', 'US500', 'GER40']
FX_METALS = ['XAUUSD', 'XAGUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF', 'EURJPY', 'GBPJPY']
AUTHOR = {'lab': 'claude', 'session_reference': 'Claude Code (claude-opus-5-5) desktop session 14e835e0-e7e8-43cf-b286-855a18365bd7, 2026-10-20',
          'statement': 'Created by this actual Claude Code session; not attributed to Codex or Kimi.'}
COMMON_LIMITS = ('No verified edge. M15 both-barrier candles need M1 (only since Jul 2026) and are otherwise AMBIGUOUS; '
                 'CFD spread proxies; correlated instruments; broker holiday calendar unverified.')
MODELS = {
    'fvg_retest': dict(name='Fair-Value-Gap Retest Continuation', requirements={'M15': 80, 'H1': 100}, instruments=ALL,
        hypothesis='First retest of an unfilled three-candle M15 imbalance left by a >=1 ATR displacement, rejected in the H1 EMA-trend direction, resumes the displacement.',
        risk_model='One planned risk unit; stop beyond the far side of the gap plus 0.25 M15 ATR; 2.5R objective; exit by min(8h, next broker gap).',
        planned_rr='2.5R fixed target'),
    'pdhl_acceptance': dict(name='Prior-Day Level Acceptance Retest', requirements={'M15': 120, 'H1': 60}, instruments=ALL,
        hypothesis='After an M15 close beyond the prior broker-day high/low, the first retest that holds the level signals acceptance outside prior value and extension.',
        risk_model='One planned risk unit; stop beyond the retest extreme plus 0.3 M15 ATR; 2.5R objective; exit by min(8h, next broker gap); 06-19 UTC except crypto.',
        planned_rr='2.5R fixed target'),
    'session_mean_reversion': dict(name='Session-Mean Stretch Reversion', requirements={'M15': 120, 'H1': 40}, instruments=ALL,
        hypothesis='In range-bound H1 regimes, a 2.5 SD stretch from the broker-day mean rejected at a new session extreme reverts to the mean.',
        risk_model='One planned risk unit; stop beyond the session extreme plus 0.25 M15 ATR; target = session mean, admitted only at >=2.2R; exit by min(6h, next broker gap).',
        planned_rr='Variable, >=2.2R (session-mean target)'),
    'london_momentum': dict(name='London-Session Momentum Carry', requirements={'M15': 40, 'H4': 120}, instruments=FX_METALS,
        hypothesis='FX/metals that trend >=0.5 daily ATR through the London morning and sit in the outer quarter of the session range at 13:00 London extend into the 16:00 London fix.',
        risk_model='One planned risk unit; fixed 0.30 daily-ATR stop; 2.2R objective; one decision per instrument per day; flat by 16:30 London.',
        planned_rr='2.2R fixed target'),
}
for key, m in MODELS.items():
    manifest = {'lab': 'claude', 'key': key, 'version': '0.1.0', 'name': m['name'], 'timeframe': 'M15',
                'requirements': m['requirements'], 'instruments': m['instruments'], 'classification': 'EXPERIMENTAL',
                'entry_type': 'MARKET_PAPER_QUOTE', 'hypothesis': m['hypothesis'], 'risk_model': m['risk_model'],
                'planned_rr': m['planned_rr'], 'known_limitations': COMMON_LIMITS, 'declared_trials_in_phase': 1, 'authorship': AUTHOR}
    (LAB / 'strategies' / key / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('manifest', key)
