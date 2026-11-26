"""Nova ponte autenticada Mahoraga-Blender."""

import hmac
import json
import os
import secrets
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .integration_core import IntegratedCore

HOST = "127.0.0.1"
PORT = 8766
MAX_BODY = 65536

ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / "memory" / "blender_bridge_v2.token"


def load_or_create_token():
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)

    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if len(token) < 40:
            raise RuntimeError("Arquivo de autenticação inválido.")
        return token

    token = secrets.token_urlsafe(48)

    fd = os.open(
        str(TOKEN_FILE),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(token + "\n")

    return token


def create_handler(core, token):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "MahoragaBridge/2.0"

        def log_message(self, fmt, *args):
            print("[MahoragaBridgeV2]", fmt % args)

        def send_json(self, status, data):
            body = json.dumps(
                data,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")

            self.send_response(status)
            self.send_header(
                "Content-Type",
                "application/json; charset=utf-8",
            )
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def authorized(self):
            supplied = self.headers.get("Authorization", "")
            expected = "Bearer " + token
            return hmac.compare_digest(supplied, expected)

        def do_GET(self):
            if not self.authorized():
                self.send_json(401, {"error": "unauthorized"})
                return

            path = urlsplit(self.path).path

            try:
                if path == "/health":
                    self.send_json(200, {
                        "ok": True,
                        "service": "Mahoraga Blender Bridge V2",
                    })

                elif path == "/status":
                    self.send_json(
                        200,
                        core.blender_bridge.status(),
                    )

                elif path == "/next":
                    task = core.blender_bridge.queue.claim_next(
                        "mahoraga-blender-android-v2"
                    )
                    self.send_json(200, {"task": task})

                else:
                    self.send_json(404, {"error": "not_found"})

            except Exception as exc:
                self.send_json(500, {
                    "error": type(exc).__name__,
                    "message": str(exc)[:500],
                })

        def do_POST(self):
            if not self.authorized():
                self.send_json(401, {"error": "unauthorized"})
                return

            path = urlsplit(self.path).path

            try:
                length = int(self.headers.get("Content-Length", "0"))

                if length < 1 or length > MAX_BODY:
                    self.send_json(413, {
                        "error": "invalid_body_size"
                    })
                    return

                raw = self.rfile.read(length)
                data = json.loads(raw.decode("utf-8"))

                if not isinstance(data, dict):
                    raise ValueError("O corpo deve ser um objeto JSON.")

                task_id = int(data["task_id"])

                if path == "/complete":
                    result = data.get("result", {})

                    if not isinstance(result, dict):
                        raise ValueError("result deve ser um objeto.")

                    core.blender_bridge.queue.complete(
                        task_id,
                        result,
                    )

                    self.send_json(200, {
                        "ok": True,
                        "task_id": task_id,
                        "status": "completed",
                    })

                elif path == "/fail":
                    error = str(data.get("error", "")).strip()

                    core.blender_bridge.queue.fail(
                        task_id,
                        error,
                    )

                    self.send_json(200, {
                        "ok": True,
                        "task_id": task_id,
                        "status": "failed",
                    })

                else:
                    self.send_json(404, {"error": "not_found"})

            except (ValueError, KeyError, TypeError) as exc:
                self.send_json(400, {
                    "error": type(exc).__name__,
                    "message": str(exc)[:500],
                })

            except Exception as exc:
                self.send_json(500, {
                    "error": type(exc).__name__,
                    "message": str(exc)[:500],
                })

        def do_PUT(self):
            self.send_json(405, {"error": "method_not_allowed"})

        def do_DELETE(self):
            self.send_json(405, {"error": "method_not_allowed"})

    return Handler


def main():
    token = load_or_create_token()
    core = IntegratedCore()

    class LocalServer(ThreadingHTTPServer):
        allow_reuse_address = True

    server = LocalServer(
        (HOST, PORT),
        create_handler(core, token),
    )
    server.daemon_threads = True

    print("\n=== MAHORAGA BLENDER BRIDGE V2 ===")
    print(f"Endereço: http://{HOST}:{PORT}")
    print("Autenticação: token persistente")
    print(f"Arquivo protegido: {TOKEN_FILE}")
    print("Acesso restrito ao próprio aparelho.")
    print("Servidor pronto.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando servidor V2...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
