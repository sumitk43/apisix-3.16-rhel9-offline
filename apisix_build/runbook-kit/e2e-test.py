#!/usr/bin/env python3
"""Usage: python3 e2e-test.py APISIX_HOME LOG_DIRECTORY"""
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import sys,threading,time,urllib.request,urllib.error
home=Path(sys.argv[1]).resolve(); logs=Path(sys.argv[2]).resolve(); logs.mkdir(parents=True,exist_ok=True)
error=home/'logs/error.log'; offset=error.stat().st_size
backend=logs/'backend'; backend.mkdir(exist_ok=True)
expected=b'APISIX 3.18 + OpenResty 1.31.1.1 route OK\n'
(backend/'build-check.txt').write_bytes(expected)
class Handler(SimpleHTTPRequestHandler):
    def log_message(self,*args): pass
server=ThreadingHTTPServer(('127.0.0.1',18080),partial(Handler,directory=str(backend)))
threading.Thread(target=server.serve_forever,daemon=True).start()
client=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def request(port):
    with client.open(f'http://127.0.0.1:{port}/build-check.txt',timeout=15) as r:
        if r.status!=200 or r.read()!=expected: raise RuntimeError('Unexpected response')
try:
    request(18080); print('Direct backend: PASS')
    for i in range(1,11):
        request(9080); print(f'APISIX request {i}/10: HTTP 200, body verified')
    try:
        with client.open('http://127.0.0.1:9080/no-such-build-route',timeout=10) as r:
            raise RuntimeError('Unmatched route succeeded')
    except urllib.error.HTTPError as r:
        if r.code!=404: raise
        print('Unmatched route: HTTP 404, PASS')
    time.sleep(2)
    with error.open('rb') as f:
        f.seek(offset); new=f.read().decode(errors='replace')
    (logs/'e2e-new-log.txt').write_text(new)
    errors=[x for x in new.splitlines() if any(level in x for level in ('[error]','[crit]','[alert]','[emerg]'))]
    if errors: raise RuntimeError('\n'.join(errors))
    print('New runtime error check: PASS'); print('FINAL END-TO-END TEST PASSED')
finally:
    server.shutdown(); server.server_close()
