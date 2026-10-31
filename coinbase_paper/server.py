"""Authenticated, paper-only HTTP API. No Coinbase trade endpoints."""
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from gate import PaperGate, GateError

MAX_BODY = 16384

def dispatch(gate, method, path, body):
    if method == 'GET' and path == '/health':
        return 200, {'status': 'ok', 'mode': 'paper-only'}
    if method == 'GET' and path == '/proposals':
        rows = gate.db.execute('SELECT * FROM proposals ORDER BY created DESC LIMIT 100').fetchall()
        return 200, {'proposals': [dict(r) for r in rows]}
    if method == 'GET' and path == '/status':
        return 200, gate.status()
    if method != 'POST':
        return 404, {'error': 'not found'}
    try:
        if path == '/proposals':
            return 201, gate.propose(body['id'], body['pair'], body['entry'], body['stop'], body['target'], body['quantity'], body['expires'])
        if path.startswith('/proposals/'):
            parts = path.split('/')
            if len(parts) != 4 or not parts[2]: return 404, {'error': 'not found'}
            pid, action = parts[2], parts[3]
            if action == 'decision':
                if type(body.get('approve')) is not bool: return 400, {'error': 'approve must be boolean'}
                return 200, {'id': pid, 'status': gate.decide(pid, body['approve'])}
            if action == 'simulate':
                return 200, gate.simulate_entry(pid, body['market_price'], body['candle_utc'],quote_utc=body.get('quote_utc'))
            if action == 'evaluate-exit':
                return 200, gate.evaluate_exit(pid, body['market_price'],body['quote_utc'])
        return 404, {'error': 'not found'}
    except (GateError, ValueError, KeyError, TypeError) as e:
        return 400, {'error': str(e)}


def make_handler(gate, token):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, obj):
            payload = json.dumps(obj, default=str).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(payload)
        def handle_request(self):
            path = urlparse(self.path).path
            if path == '/health' and self.command == 'GET':
                return self.respond(200, {'status': 'ok', 'mode': 'paper-only'})
            provided = self.headers.get('Authorization', '')
            if not hmac.compare_digest(provided, 'Bearer ' + token):
                return self.respond(401, {'error': 'unauthorized'})
            if self.command == 'POST':
                try:
                    size = int(self.headers.get('Content-Length', '-1'))
                    if size < 0 or size > MAX_BODY: return self.respond(413, {'error': 'invalid request size'})
                    data = json.loads(self.rfile.read(size))
                    if not isinstance(data, dict): return self.respond(400, {'error': 'JSON object required'})
                except (ValueError, UnicodeDecodeError):
                    return self.respond(400, {'error': 'invalid JSON'})
            else: data = {}
            status, obj = dispatch(gate, self.command, path, data)
            self.respond(status, obj)
        def do_GET(self): self.handle_request()
        def do_POST(self): self.handle_request()
        def do_PUT(self): self.respond(405, {'error': 'method not allowed'})
        def do_DELETE(self): self.respond(405, {'error': 'method not allowed'})
    return Handler

if __name__ == '__main__':
    token = os.environ.get('PAPER_API_TOKEN', '')
    if len(token) < 32: raise SystemExit('PAPER_API_TOKEN must be >=32 characters')
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '8000'))
    db = os.environ.get('PAPER_DB_PATH', 'paper_gate.sqlite')
    print('Paper-only API listening on', host, port, flush=True)
    HTTPServer((host, port), make_handler(PaperGate(db), token)).serve_forever()
