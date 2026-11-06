#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
HTTPServer(("0.0.0.0", 1985), Handler).serve_forever()
