"""
Spring PetClinic harness-adapter entry point.
Starts Spring Boot (Jib-exploded) on port 9967, proxies on port 9966.
Serves GET /healthz → 200.
"""
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROXY_PORT = 9966
APP_PORT = 9967
JAVA = "/opt/java/openjdk/bin/java"


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
    env = os.environ.copy()
    env["JAVA_HOME"] = "/opt/java/openjdk"
    env["PATH"] = "/opt/java/openjdk/bin:" + env.get("PATH", "")

    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        u = urllib.parse.urlparse(db_url)
        jdbc_url = f"jdbc:postgresql://{u.hostname}:{u.port or 5432}{u.path}"
        env["SPRING_DATASOURCE_URL"] = jdbc_url
        env["SPRING_DATASOURCE_USERNAME"] = u.username or "postgres"
        env["SPRING_DATASOURCE_PASSWORD"] = u.password or ""
    env["SPRING_PROFILES_ACTIVE"] = "postgresql,spring-data-jpa"
    env["SERVER_PORT"] = str(APP_PORT)

    proc = subprocess.Popen(
        [JAVA, "-cp", "@/app/jib-classpath-file",
         "org.springframework.samples.petclinic.PetClinicApplication"],
        env=env,
    )

    time.sleep(25)

    server = ThreadingHTTPServer(("0.0.0.0", PROXY_PORT), _ProxyHandler)
    thr = threading.Thread(target=server.serve_forever, daemon=True)
    thr.start()
    print(f"[wrapper] proxy :{PROXY_PORT} → petclinic :{APP_PORT}", flush=True)

    exit(proc.wait())
