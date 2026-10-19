"""Pure functional provider protocol and a restricted arithmetic model language.

Models get immutable data and safe numerical/container operations, not Python's
general I/O/import capabilities. The bounded worker is defense in depth; this is
not permission to run unrestricted same-account laboratory shells.
"""
import ast
import math
import statistics
from .adapter import immutable

SAFE_MODULES={'math':math,'statistics':statistics}
ATTRS={'get','append','extend','items','values','keys','sort','pop','copy','count','index',
       'sqrt','isfinite','log','exp','floor','ceil','fabs','mean','median','pstdev','stdev','fmean'}
BUILTINS={k:globals()['__builtins__'][k] if isinstance(globals()['__builtins__'],dict) else getattr(globals()['__builtins__'],k)
          for k in ('abs','min','max','sum','len','range','enumerate','zip','sorted','round','all','any','float','int','bool','str','dict','list','tuple','set','Exception','ValueError','RuntimeError')}

def validate_source(source):
    if len(source.encode())>131072:raise ValueError('model source exceeds bounded protocol size')
    tree=ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node,(ast.ClassDef,ast.Global,ast.Nonlocal,ast.With,ast.AsyncWith,ast.AsyncFunctionDef,ast.Await,ast.Yield,ast.YieldFrom,ast.Delete)):
            raise ValueError('model protocol supports pure functions, numerical loops and containers only')
        if isinstance(node,ast.Name) and (node.id.startswith('_') or node.id in {'open','eval','exec','compile','getattr','setattr','globals','locals','vars','type','object','dir','input','breakpoint','help'}):
            raise ValueError('I/O, introspection or broker access is forbidden')
        if isinstance(node,ast.Attribute) and node.attr not in ATTRS:raise ValueError('unsupported model attribute: '+node.attr)
        if isinstance(node,ast.Import):
            if any(x.name not in SAFE_MODULES or x.asname for x in node.names):raise ValueError('only math/statistics imports are supported')
        if isinstance(node,ast.ImportFrom):
            if node.module not in SAFE_MODULES or node.level or any(x.name not in ATTRS or x.asname for x in node.names):raise ValueError('unsupported import')
    if not any(isinstance(n,ast.FunctionDef) and n.name=='detect' for n in tree.body):raise ValueError('detect(snapshot) function is required')
    return tree
def safe_import(name,*args,**kwargs):
    if name not in SAFE_MODULES:raise ImportError('broker/network/filesystem modules are unavailable')
    return SAFE_MODULES[name]
def execute(source,snapshot):
    tree=validate_source(source)
    namespace={'__builtins__':{**BUILTINS,'__import__':safe_import}}
    exec(compile(tree,'<lab-pure-model>','exec'),namespace)
    result=namespace['detect'](immutable(snapshot))
    if result is None:return []
    if not isinstance(result,list) or len(result)>4:raise ValueError('detect must return at most four structured decisions')
    allowed={'direction','stop_loss','take_profit','horizon_seconds','rationale','atr'}
    for item in result:
        if not isinstance(item,dict) or set(item)!=allowed:raise ValueError('unexpected decision fields')
    return result

class LaboratoryProvider:
    def __init__(self,lab,store):
        if lab not in ('codex','claude','kimi'):raise ValueError('unknown provider')
        self.lab,self.store=lab,store
    def models(self):return [m for m in self.store.models() if m['lab']==self.lab and m['scan_enabled'] and m['status']=='EXPERIMENTAL']
    def status(self):return 'READY' if self.models() else 'PENDING_ACTUAL_AI_MODEL'
