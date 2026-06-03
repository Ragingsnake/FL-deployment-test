import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from zkp_utils import (
    PROOF_VERSION,
    _generate_statement_proof,
    _verify_statement_proof,
)


HOST = os.environ.get("ZKP_NODE_HOST", "0.0.0.0")
PORT = int(os.environ.get("ZKP_NODE_PORT", "8090"))
BACKEND = os.environ.get("ZKP_BACKEND", PROOF_VERSION)


class ZKPHandler(BaseHTTPRequestHandler):
    server_version = "zkp-node/1.0"

    def do_GET(self):
        if self.path == "/healthz":
            self._send_json({"status": "ok", "backend": BACKEND})
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self):
        try:
            payload = self._read_json()
            if self.path == "/prove":
                self._handle_prove(payload)
            elif self.path == "/verify":
                self._handle_verify(payload)
            else:
                self._send_json({"error": "not found"}, status=404)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def log_message(self, fmt, *args):
        print(f"{self.client_address[0]} - {fmt % args}")

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("missing request body")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _handle_prove(self, payload):
        statement = payload.get("statement")
        if not isinstance(statement, dict):
            raise ValueError("statement must be an object")
        proof = _generate_statement_proof(statement)
        self._send_json({"backend": BACKEND, "proof": proof})

    def _handle_verify(self, payload):
        statement = payload.get("statement")
        proof = payload.get("proof")
        if not isinstance(statement, dict):
            raise ValueError("statement must be an object")
        valid = _verify_statement_proof(statement, proof)
        self._send_json({"backend": BACKEND, "valid": valid})

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    print(f"Starting ZKP node on {HOST}:{PORT} with backend={BACKEND}")
    ThreadingHTTPServer((HOST, PORT), ZKPHandler).serve_forever()


if __name__ == "__main__":
    main()
