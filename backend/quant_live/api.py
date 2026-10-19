from fastapi import APIRouter,Request,HTTPException
import os
from . import service
from .report import snapshot

router=APIRouter()
@router.get('/api/quant-labs/live')
def live_models(request:Request):
    if os.getenv('TRADING_HUB_AUTH_MODE','private')!='private' or not request.client or request.client.host not in ('127.0.0.1','::1','testclient'):
        raise HTTPException(403,'Local research owner view only')
    report=snapshot(service.store());return {**report,'runtime':service.status()}
