"""Read-only localhost preview and self-contained export. No production web routes."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
from .bootstrap import DEFAULT_STATE
from .control import ControlPlane

BASE=Path(__file__).resolve().parent
def export(control,destination=None):
    destination=Path(destination) if destination else BASE/'dashboard.html'
    html=(BASE/'dashboard/index.html').read_text(encoding='utf-8')
    css=(BASE/'dashboard/styles.css').read_text(encoding='utf-8');js=(BASE/'dashboard/dashboard.js').read_text(encoding='utf-8')
    state=json.dumps(control.public()).replace('<','\\u003c')
    html=html.replace('<link rel="stylesheet" href="/styles.css">','<style>'+css+'</style>').replace('<script src="/dashboard.js"></script>','<script>'+js+'</script>')
    html=html.replace('type="application/json">null</script>','type="application/json">'+state+'</script>')
    destination.write_text(html,encoding='utf-8');return destination

def server(control,port=8766):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            host=self.headers.get('Host','')
            if host not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'):
                self.send_error(403);return
            routes={'/':('text/html','index.html'),'/styles.css':('text/css','styles.css'),'/dashboard.js':('text/javascript','dashboard.js')}
            if self.path=='/api/research':body=json.dumps(control.public()).encode();kind='application/json'
            elif self.path in routes:
                kind,name=routes[self.path];body=(BASE/'dashboard'/name).read_bytes()
            else:self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',kind+'; charset=utf-8');self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
        def do_POST(self):self.send_error(405,'Read-only prototype')
        def log_message(self,*args):pass
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--root',default=str(DEFAULT_STATE));p.add_argument('--export',action='store_true');p.add_argument('--port',type=int,default=8766);args=p.parse_args()
    control=ControlPlane(args.root)
    if args.export:print(export(control))
    else:
        http=server(control,args.port);print(f'Isolated read-only preview: http://127.0.0.1:{http.server_port}',flush=True)
        try:http.serve_forever()
        finally:http.server_close()
