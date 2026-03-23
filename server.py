#!/usr/bin/env python3
"""
GitHub Repository Agent 
---------------------------------------------------------

Setup:
  1. Install Ollama → https://ollama.com
  2. ollama pull llama3.2
  3. python server.py
  4. Open http://localhost:8080

"""

import os, sys, json, webbrowser, threading, argparse
import urllib.request, urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

HTML_FILE         = Path(__file__).parent / "agent.html"
PORT              = 8080
OLLAMA_URL        = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL      = os.environ.get("OLLAMA_MODEL", "llama3.2")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL   = "claude-sonnet-4-20250514"
BACKEND           = "ollama"


def call_ollama(system_prompt, user_message):
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ]
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
        return data["message"]["content"]
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Cannot reach Ollama at {OLLAMA_URL}. "
            "Is it running? Try: ollama serve"
        ) from e


def call_anthropic(system_prompt, user_message):
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    payload = json.dumps({
        "model": ANTHROPIC_MODEL,
        "max_tokens": 1000,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}]
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return data["content"][0]["text"]


def call_llm(system_prompt, user_message):
    if BACKEND == "anthropic":
        return call_anthropic(system_prompt, user_message)
    return call_ollama(system_prompt, user_message)


def check_ollama():
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def get_ollama_models():
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as r:
            data = json.loads(r.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


class AgentHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        method = args[0].split()[0] if args else "?"
        path   = args[0].split()[1] if args and len(args[0].split()) > 1 else "?"
        code   = args[1] if len(args) > 1 else "?"
        if path not in ("/favicon.ico",):
            color = "\033[92m" if str(code).startswith("2") else "\033[91m"
            print(f"  {color}{code}\033[0m  {method} {path}")

    def send_json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path in ("/", "/index.html", "agent.html"):
            if not HTML_FILE.exists():
                self.send_json(404, {"error": "agent.html not found next to server.py"})
                return
            content = HTML_FILE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(content))
            self.end_headers()
            self.wfile.write(content)

        elif self.path == "/api/health":
            ollama_ok = check_ollama()
            self.send_json(200, {
                "status": "ok",
                "backend": BACKEND,
                "ollama_running": ollama_ok,
                "ollama_model": OLLAMA_MODEL,
                "anthropic_key_set": bool(ANTHROPIC_API_KEY),
            })
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path == "/api/claude":
            self._handle_llm()
        else:
            self.send_json(404, {"error": "Unknown endpoint"})

    def _handle_llm(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Invalid JSON"})
            return

        system_prompt = payload.get("system", "You are a helpful assistant.")
        user_message  = payload.get("message", "")

        if not user_message:
            self.send_json(400, {"error": "No message provided"})
            return

        try:
            text = call_llm(system_prompt, user_message)
            self.send_json(200, {"text": text})
        except RuntimeError as e:
            self.send_json(503, {"error": str(e)})
        except Exception as e:
            self.send_json(500, {"error": str(e)})


def print_banner(ollama_ok, models):
    cyan  = "\033[96m"
    green = "\033[92m"
    amber = "\033[93m"
    red   = "\033[91m"
    dim   = "\033[2m"
    reset = "\033[0m"

    if BACKEND == "ollama":
        backend_line = f"{green}Ollama{reset}  (model: {OLLAMA_MODEL})"
    else:
        backend_line = f"{cyan}Anthropic{reset}  (model: {ANTHROPIC_MODEL})"

    if ollama_ok:
        ollama_status = f"{green}running{reset}  — {len(models)} model(s): {', '.join(models[:3]) or 'none'}"
    else:
        ollama_status = f"{red}not running{reset}  →  {amber}ollama serve{reset}"

    model_warn = ""
    if ollama_ok and models and not any(OLLAMA_MODEL.split(":")[0] in m for m in models):
        model_warn = f"\n  {amber}⚠{reset}   '{OLLAMA_MODEL}' not pulled — run: {amber}ollama pull {OLLAMA_MODEL}{reset}"

    print(f"""
{cyan}╔══════════════════════════════════════════════╗
║   GitHub Repository Agent  ·                        ║
╚══════════════════════════════════════════════╝{reset}

  {green}✓{reset}  URL       http://localhost:{PORT}
  ⚙   Backend   {backend_line}
  🦙  Ollama    {ollama_status}{model_warn}

  {dim}Switch model:     OLLAMA_MODEL=mistral python server.py
  Use Anthropic:    python server.py --backend anthropic
  Ctrl+C to stop{reset}
""")


def open_browser():
    import time; time.sleep(1.0)
    webbrowser.open(f"http://localhost:{PORT}")


def main():
    global BACKEND, OLLAMA_MODEL, PORT

    parser = argparse.ArgumentParser(description="GitHub Agent — Local Server")
    parser.add_argument("--backend", choices=["ollama", "anthropic"], default="ollama")
    parser.add_argument("--model",   default=None, help="Ollama model (default: llama3.2)")
    parser.add_argument("--port",    type=int, default=8080)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    BACKEND = args.backend
    PORT    = args.port
    if args.model:
        OLLAMA_MODEL = args.model

    if not HTML_FILE.exists():
        print(f"\033[91m✗  github-agent.html not found next to server.py\033[0m")
        sys.exit(1)

    ollama_ok = check_ollama()
    models    = get_ollama_models()
    print_banner(ollama_ok, models)

    if BACKEND == "ollama" and not ollama_ok:
        print("  \033[93mOllama isn't running — requests will fail until you start it.\033[0m\n")

    if not args.no_browser:
        threading.Thread(target=open_browser, daemon=True).start()

    server = HTTPServer(("", PORT), AgentHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\033[2m  Stopped.\033[0m\n")
        server.server_close()


if __name__ == "__main__":
    main()