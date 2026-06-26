import json
import os
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ["ZKP_LOCAL_ONLY"] = "1"

from zkp_utils import VK_PATH, WASM_PATH, WITNESS_JS, ZKEY_PATH, _local_generate, _local_verify  # noqa: E402


HOST = os.environ.get("ZKP_NODE_HOST", "0.0.0.0")
PORT = int(os.environ.get("ZKP_NODE_PORT", "8090"))
BACKEND = os.environ.get("ZKP_BACKEND", "groth16")


class ZKPHandler(BaseHTTPRequestHandler):
    server_version = "zkp-node/1.0"

    def do_GET(self):
        if self.path == "/healthz":
            missing = [
                path
                for path in (ZKEY_PATH, VK_PATH, WASM_PATH, WITNESS_JS)
                if not os.path.exists(path)
            ]
            missing_tools = [tool for tool in ("node", "snarkjs") if shutil.which(tool) is None]
            if missing or missing_tools:
                self._send_json(
                    {
                        "status": "error",
                        "backend": BACKEND,
                        "missing_files": missing,
                        "missing_tools": missing_tools,
                    },
                    status=503,
                )
                return
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
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _handle_prove(self, payload):
        input_json = payload.get("input")
        if not isinstance(input_json, dict):
            raise ValueError("input must be an object")
        proof_data = _local_generate(input_json)
        self._send_json({"backend": BACKEND, "proof_data": proof_data})

    def _handle_verify(self, payload):
        proof_data = payload.get("proof_data")
        if not isinstance(proof_data, dict):
            raise ValueError("proof_data must be an object")
        self._send_json({"backend": BACKEND, "valid": _local_verify(proof_data)})

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
