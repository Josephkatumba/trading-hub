from fastapi import APIRouter,Request,HTTPException
import os
from . import service
from .report import snapshot

router=APIRouter()
@router.get('/api/quant-labs/live')
def live_models(request:Request):
    if os.getenv('TRADING_HUB_AUTH_MODE','private')!='private' or not request.client or request.client.host not in ('127.0.0.1','::1','testclient'):
        raise HTTPException(403,'Local research owner view only')
    store=service.store();report=snapshot(store);runtime=service.status()
    from .health import health
    return {**report,'runtime':runtime,'health':health(store,runtime)}


@router.get('/api/quant-labs/intelligence/{symbol}')
def market_intelligence(symbol:str,request:Request):
    """Explainable XAUUSD/BTCUSD analysis from the live closed-candle cache; internal preview, never sent."""
    if os.getenv('TRADING_HUB_AUTH_MODE','private')!='private' or not request.client or request.client.host not in ('127.0.0.1','::1','testclient'):
        raise HTTPException(403,'Local research owner view only')
    symbol=symbol.upper()
    if symbol not in ('XAUUSD','BTCUSD'):raise HTTPException(404,'Intelligence is available for XAUUSD and BTCUSD')
    from market_intel.live import intelligence
    quote=(service.status().get('latest_inputs',{}).get(symbol) or {}).get('quote')
    return intelligence(service.store(),symbol,quote)


@router.get('/api/quant-labs/intelligence-center')
def intelligence_center(request:Request):
    """Telegram Intelligence Center: all three notification categories, read-only."""
    if os.getenv('TRADING_HUB_AUTH_MODE','private')!='private' or not request.client or request.client.host not in ('127.0.0.1','::1','testclient'):
        raise HTTPException(403,'Local research owner view only')
    from .intel_center import center
    return center(service.store(),service.status())
