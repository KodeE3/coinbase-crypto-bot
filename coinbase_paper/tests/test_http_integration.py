"""Real localhost HTTP checks; no external service or broker connectivity."""
import http.client
import json
import queue
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from gate import PaperGate
from server import make_handler

class HttpIntegrationTests(unittest.TestCase):
    def test_health_auth_status_and_no_order_route(self):
        with tempfile.TemporaryDirectory() as temp:
            ready=queue.Queue();token='test-only-token-for-localhost-123456789'
            def serve():
                gate=PaperGate(Path(temp)/'db.sqlite')
                handler=make_handler(gate,token)
                handler.log_message=lambda *args:None
                server=HTTPServer(('127.0.0.1',0),handler);ready.put(server)
                try:server.serve_forever(poll_interval=0.01)
                finally:server.server_close();gate.close()
            thread=threading.Thread(target=serve,daemon=True);thread.start()
            server=ready.get(timeout=5)
            try:
                def request(path,method='GET',authorized=False):
                    connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                    try:
                        headers={'Authorization':'Bearer '+token} if authorized else {}
                        if method=='POST':headers['Content-Type']='application/json'
                        connection.request(method,path,body='{}' if method=='POST' else None,headers=headers)
                        response=connection.getresponse();return response.status,json.loads(response.read())
                    finally:connection.close()
                self.assertEqual(request('/health')[0],200)
                self.assertEqual(request('/status')[0],401)
                code,state=request('/status',authorized=True)
                self.assertEqual(code,200);self.assertTrue(state['reconciled'])
                self.assertEqual(request('/orders','POST',True)[0],404)
            finally:server.shutdown();thread.join(timeout=5)
