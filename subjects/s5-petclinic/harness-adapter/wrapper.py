"""
Spring PetClinic harness-adapter entry point.
Starts Spring Boot on port 9967, proxies on port 9966.
Serves GET /healthz → 200.
"""
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROXY_PORT = 9966
APP_PORT = 9967


class _ProxyHandler(BaseHTTPRequestHandler):
    def _do(self) -> None:
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else None
        target = f"http://127.0.0.1:{APP_PORT}{self.path}"
        hdrs = {k: v for k, v in self.headers.items()
                if k.lower() not in ("host", "transfer-encoding", "connection")}
        req = urllib.request.Request(target, data=body, method=self.command, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() not in ("transfer-encoding", "connection"):
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as exc:
            self.send_response(exc.code)
            for k, v in exc.headers.items():
                if k.lower() not in ("transfer-encoding", "connection"):
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(exc.read())
        except Exception as exc:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(f"proxy error: {exc}".encode())

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _do

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    db_url = os.environ.get("DATABASE_URL", "")
    pg_user = os.environ.get("POSTGRES_USER", "postgres")
    pg_pass = os.environ.get("POSTGRES_PASSWORD", "postgres")
    pg_db = os.environ.get("POSTGRES_DB", "postgres")

    jvm_args = [
        "java", "-jar", "/app/spring-petclinic-rest.jar",
        f"--server.port={APP_PORT}",
        f"--spring.datasource.url={db_url.replace('postgresql://', 'jdbc:postgresql://').split('?')[0]}",
        f"--spring.datasource.username={pg_user}",
        f"--spring.datasource.password={pg_pass}",
        "--spring.jpa.hibernate.ddl-auto=validate",
        "--spring.profiles.active=postgresql,spring-data-jpa",
    ]

    proc = subprocess.Popen(jvm_args, env=os.environ.copy())

    # Spring Boot typically takes ~20s to start
    time.sleep(25)

    server = ThreadingHTTPServer(("0.0.0.0", PROXY_PORT), _ProxyHandler)
    thr = threading.Thread(target=server.serve_forever, daemon=True)
    thr.start()
    print(f"[wrapper] proxy :{PROXY_PORT} → petclinic :{APP_PORT}", flush=True)

    exit(proc.wait())
