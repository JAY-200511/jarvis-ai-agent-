"""Local JARVIS bridge: Ollama chat and carefully scoped Windows actions."""

from __future__ import annotations

import json
import base64
import functools
import os
import re
import subprocess
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = int(os.environ.get("JARVIS_PORT", "8765"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
MODEL = os.environ.get("JARVIS_MODEL", "qwen3.5:4b")
MAX_BODY = 8 * 1024 * 1024
gesture_control_enabled = False
desktop_access_enabled = True
model_warm = False
website_servers: list[ThreadingHTTPServer] = []
JsonObject = dict[str, Any]


def as_json_object(value: Any) -> JsonObject:
    """Narrow decoded JSON to an object before reading model-controlled fields."""
    return cast(JsonObject, value) if isinstance(value, dict) else {}


def as_json_objects(value: Any) -> list[JsonObject]:
    """Return only object entries from a decoded JSON array."""
    if not isinstance(value, list):
        return []
    items = cast(list[Any], value)
    return [as_json_object(item) for item in items if isinstance(item, dict)]

SYSTEM = (
    "You are JARVIS, a warm, friendly, natural-sounding personal assistant and conversation partner. "
    "Talk like a relaxed person: use everyday words, natural sentence rhythm, and friendly Hinglish when it fits. "
    "If the user speaks/types Roman Hinglish, answer in Roman Hinglish; if they use Devanagari, answer in Devanagari; "
    "if they use English, answer in English. Be warm without sounding scripted. Avoid formal filler, repeated greetings, "
    "robotic status recaps, and phrases like 'Certainly' or 'As an AI'. Answer the point first; for casual chat, respond "
    "to what the user actually said and ask a natural follow-up only when useful. Keep spoken replies short by default, "
    "but give detail when asked. Never echo the user's last sentence as your answer. You run locally on the user's "
    "Windows laptop. Be honest about what you can and cannot see or do. Never claim an action "
    "succeeded unless a tool confirms it. Use tools only when the user's request calls for an action. "
    "The user wants clearly requested desktop actions to run directly without an extra approval card. "
    "Use only the smallest actions needed; never send, submit, delete, or purchase unless that exact action "
    "was directly requested. For a clear WhatsApp send command "
    "that includes a recipient and the exact message, the user's command is authorization: open "
    "WhatsApp if needed, inspect the desktop, search for the named contact, and verify the selected "
    "chat title before typing and sending the exact message without an extra JARVIS approval card. "
    "Only type recipient/message text that appears in the user's command. If the recipient or exact message "
    "is missing or the visible recipient is ambiguous, ask a short question and do not send. Never "
    "invent or rewrite message content. Never ask for passwords, API keys, or authentication "
    "codes in chat. Camera starts with the dashboard; images are sent only with a user message. "
    "If an image is provided, describe visible cues cautiously, "
    "do not claim certainty about a person's mood or mental state. Desktop screenshots are "
    "available only when Desktop View is on; use view_desktop to inspect a screen before "
    "choosing coordinates. If a target or requested action is ambiguous, ask one short question before acting."
)

TOOLS: list[JsonObject] = [
    {
        "type": "function",
        "function": {
            "name": "get_laptop_health",
            "description": "Read current Windows CPU load, RAM use, battery status, disk space, and uptime when the user asks about laptop health or performance.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_desktop",
            "description": "Capture the current Windows desktop so you can identify visible apps and controls. Available only while the user has enabled Desktop View. Call this before choosing screen coordinates.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Open one of the approved local Windows apps.",
            "parameters": {
                "type": "object",
                "properties": {"app": {"type": "string", "enum": ["notepad", "calculator", "files", "browser", "whatsapp", "gmail"]}},
                "required": ["app"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_website",
            "description": "Open a public web page in the default browser. Never use this to submit a form or send a message.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "An http or https URL"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_website",
            "description": "Create a complete responsive website project when the user explicitly asks you to make/build/code a website or web page. Generate it in the user's Jarvis-Websites folder, open the project in VS Code, start a local preview, and return its URL. Ask for no secrets and do not deploy or publish it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "The requested website purpose, content, style, and features."},
                    "project_name": {"type": "string", "description": "Short folder/site name, if the user gave one."},
                },
                "required": ["description"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "computer_input",
            "description": "Perform the computer action the user explicitly requested, without an approval card. Use only the visible desktop controls and the smallest actions needed. Do not send, submit, delete, or purchase unless the user directly asked for that exact action. Never invent text to type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["type_text", "press_key", "click", "scroll"]},
                    "text": {"type": "string"},
                    "key": {"type": "string", "enum": ["enter", "tab", "escape", "backspace", "delete", "space", "ctrl+l", "ctrl+f", "ctrl+c", "ctrl+v", "ctrl+a", "alt+tab"]},
                    "x": {"type": "integer", "minimum": 0, "maximum": 10000},
                    "y": {"type": "integer", "minimum": 0, "maximum": 10000},
                    "amount": {"type": "integer", "minimum": -8, "maximum": 8},
                    "reason": {"type": "string", "description": "Briefly explain which visible control this action targets and why."},
                },
                "required": ["action"],
            },
        },
    },
]


def ollama(path: str, payload: JsonObject | None = None, timeout: int = 180) -> JsonObject:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{OLLAMA_URL}{path}", data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def create_website(args: JsonObject) -> JsonObject:
    """Generate a self-contained website, open its project, and serve a local preview."""
    description = str(args.get("description", "")).strip()[:5000]
    if len(description) < 8:
        return {"ok": False, "message": "Please describe the website you want in a little more detail."}
    raw_name = str(args.get("project_name", "jarvis-website"))[:80].lower()
    slug = re.sub(r"[^a-z0-9]+", "-", raw_name).strip("-")[:48] or "jarvis-website"
    desktop = Path.home() / "OneDrive" / "Desktop"
    if not desktop.is_dir():
        desktop = Path.home() / "Desktop"
    output_root = desktop / "Jarvis-Websites"
    output_root.mkdir(parents=True, exist_ok=True)
    project_dir = output_root / slug
    suffix = 2
    while project_dir.exists():
        project_dir = output_root / f"{slug}-{suffix}"
        suffix += 1

    prompt = (
        "Create a polished, complete, responsive website as ONE self-contained index.html file. "
        "Return only the HTML source, beginning with <!doctype html>; no markdown fences, explanations, or external build tools. "
        "Put all CSS in a style tag and all JavaScript in a script tag. Use accessible semantic HTML, responsive mobile layout, "
        "a refined visual design, and working interactions that need no server or API keys. Do not include fake claims, credentials, "
        "or forms that transmit data. Use CSS gradients/SVG/local inline icons instead of remote images where possible. "
        "The user's requested website: " + description
    )
    generated = ollama("/api/chat", {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "keep_alive": "30m",
        "options": {"num_ctx": 8192, "num_predict": 5000, "temperature": 0.55},
    }, timeout=600)
    html = str(generated.get("message", {}).get("content", "")).strip()
    html = re.sub(r"^```(?:html)?\s*", "", html, flags=re.IGNORECASE)
    html = re.sub(r"\s*```$", "", html).strip()
    if "<html" not in html.lower() or "</html>" not in html.lower():
        return {"ok": False, "message": "The local AI did not return a complete HTML page. Try a shorter website description."}
    if len(html.encode("utf-8")) > 1_500_000:
        return {"ok": False, "message": "The generated page was too large to save safely. Try a more focused description."}
    project_dir.mkdir(parents=False, exist_ok=False)
    (project_dir / "index.html").write_text(html, encoding="utf-8")

    # Bind an isolated static preview server to a free loopback port.
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(project_dir))
    preview_server = ThreadingHTTPServer((HOST, 0), handler)
    preview_server.daemon_threads = True
    website_servers.append(preview_server)
    threading.Thread(target=preview_server.serve_forever, daemon=True, name=f"jarvis-site-{slug}").start()
    preview_url = f"http://{HOST}:{preview_server.server_port}/"

    vscode = shutil.which("code")
    if not vscode:
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe",
            Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Microsoft VS Code" / "Code.exe",
        ]
        vscode = str(next((candidate for candidate in candidates if candidate.is_file()), "")) or None
    editor_opened = False
    if vscode:
        try:
            subprocess.Popen([vscode, "--new-window", str(project_dir)], shell=False, close_fds=True)
            editor_opened = True
        except OSError:
            pass
    if not editor_opened:
        try:
            os.startfile(str(project_dir))
        except OSError:
            pass
    webbrowser.open(preview_url)
    return {
        "ok": True,
        "message": "Website created and local preview is running.",
        "project_folder": str(project_dir),
        "file": str(project_dir / "index.html"),
        "preview_url": preview_url,
        "vscode_opened": editor_opened,
    }


def _spoken_key(text: str) -> str:
    return re.sub(r"[^\w+]", "", str(text).casefold(), flags=re.UNICODE)


def text_is_in_request(candidate: str, request: str) -> bool:
    wanted = _spoken_key(candidate)
    supplied = _spoken_key(request)
    return len(wanted) >= 2 and wanted in supplied


def whatsapp_request_state(text: str) -> tuple[bool, bool]:
    """Return whether this is a WhatsApp send request and whether its recipient/body are explicit."""
    mentions_whatsapp = bool(re.search(r"what(?:['’]?s)?\s*app|whatss?app|व्हाट्सएप|वॉट्सऐप", text, re.IGNORECASE))
    asks_to_send = bool(re.search(r"\b(send|text|bhej(?:na|o|do|de|dena)?|bhejo|bhej|likho|likh)\b|भेज|लिख", text, re.IGNORECASE))
    if not (mentions_whatsapp and asks_to_send):
        return False, False
    marker = re.search(r"\b(?:saying|that|message\s+(?:is|as)|text\s+(?:is|as)|ki|ke)\b\s*|:\s*|\bकि\s*", text, re.IGNORECASE)
    if not marker:
        return True, False
    before = text[:marker.start()]
    after = text[marker.end():].strip(" \t.,:;\"'“”‘’-")
    has_named_recipient = bool(
        re.search(r"\b(?:to|for)\s+[\w@+][\w@.+-]*", before, re.IGNORECASE)
        or re.search(r"[\w][\w\s'.-]{0,55}\s+(?:ko|को)\b", before, re.IGNORECASE)
    )
    return True, has_named_recipient and bool(re.search(r"[\w\u0900-\u097f]", after, re.UNICODE))


def run_safe_tool(name: str, args: JsonObject, *, user_request: str = "", whatsapp_send_text: str = "", whatsapp_desktop_seen: bool = False) -> JsonObject:
    if name == "create_website":
        return create_website(args)
    if name == "get_laptop_health":
        from windows_health import get_laptop_health
        health = get_laptop_health()
        return {"ok": health["available"], "message": health.get("message", "Current laptop health readings:"), "health": cast(JsonObject, health)}
    if name == "view_desktop":
        if not desktop_access_enabled:
            return {"ok": False, "message": "Desktop access is paused."}
        from windows_control import screenshot_png
        return {"ok": True, "message": "Desktop screenshot captured for local analysis.", "image": base64.b64encode(screenshot_png()).decode("ascii")}
    if name == "open_app":
        app = args.get("app")
        targets: dict[str, list[str] | str | None] = {
            "notepad": ["notepad.exe"], "calculator": ["calc.exe"],
            "files": ["explorer.exe"], "browser": None,
            "whatsapp": "https://web.whatsapp.com/", "gmail": "https://mail.google.com/",
        }
        if app not in targets:
            return {"ok": False, "message": "That app is not on the allow-list."}
        target = targets[app]
        if app == "whatsapp":
            try:
                os.startfile("whatsapp:")
            except OSError:
                webbrowser.open("https://web.whatsapp.com/")
        elif target is None:
            webbrowser.open("https://www.google.com/")
        elif isinstance(target, str):
            webbrowser.open(target)
        else:
            subprocess.Popen(target, shell=False, close_fds=True)
        return {"ok": True, "message": f"Opened {app}."}
    if name == "open_website":
        raw = str(args.get("url", "")).strip()
        parsed = urllib.parse.urlsplit(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return {"ok": False, "message": "I can only open a valid public http/https URL."}
        webbrowser.open(raw)
        return {"ok": True, "message": f"Opened {parsed.hostname} in your browser."}
    if name == "computer_input":
        action = args.get("action")
        if action not in {"type_text", "press_key", "click", "scroll"}:
            return {"ok": False, "message": "Unsupported computer action."}
        clean: JsonObject = {"action": action}
        clean["reason"] = str(args.get("reason", "Requested by you"))[:180]
        if action == "type_text":
            clean["text"] = str(args.get("text", ""))[:1000]
        elif action == "press_key":
            key = str(args.get("key", ""))
            if key not in {"enter", "tab", "escape", "backspace", "delete", "space", "ctrl+l", "ctrl+f", "ctrl+c", "ctrl+v", "ctrl+a", "alt+tab"}:
                return {"ok": False, "message": "That key combination is not allowed."}
            clean["key"] = key
        elif action == "click":
            clean["x"] = max(0, min(int(args.get("x", 0)), 10000))
            clean["y"] = max(0, min(int(args.get("y", 0)), 10000))
        else:
            clean["amount"] = max(-8, min(int(args.get("amount", 0)), 8))
        reason_mentions_whatsapp = "whatsapp" in clean["reason"].casefold()
        typed_text_is_user_supplied = action != "type_text" or text_is_in_request(clean.get("text", ""), whatsapp_send_text or user_request)
        if not typed_text_is_user_supplied:
            return {"ok": False, "message": "I can only type text that you explicitly provided."}
        if whatsapp_send_text and reason_mentions_whatsapp and not whatsapp_desktop_seen:
            return {"ok": False, "message": "Inspect the current WhatsApp desktop with view_desktop before continuing this direct send."}
        if whatsapp_send_text and reason_mentions_whatsapp and not typed_text_is_user_supplied:
            return {"ok": False, "message": "I can only type the exact WhatsApp message you asked me to send."}
        return execute_computer_action(clean)
    return {"ok": False, "message": "Unknown tool."}


def direct_command(text: str) -> JsonObject | None:
    """Handle reliable everyday app-open and laptop-health commands without an LLM tool call."""
    spoken = text.lower().strip()
    if not spoken:
        return None
    health_terms = ("laptop health", "system health", "battery", "cpu", "ram usage", "memory usage", "disk space", "laptop temperature")
    if any(term in spoken for term in health_terms) or ("health" in spoken and any(word in spoken for word in ("laptop", "computer", "system"))):
        from windows_health import get_laptop_health
        health = get_laptop_health()
        result: JsonObject = {"ok": health["available"], "message": health.get("message", "Current laptop health readings:"), "health": cast(JsonObject, health)}
        if not health["available"]:
            reply = "Laptop health readings abhi available nahi hain."
        else:
            cpu_percent = health.get("cpu_percent")
            cpu = "abhi measure ho raha hai" if cpu_percent is None else f"{cpu_percent} percent"
            ram = health.get("ram")
            battery = health.get("battery")
            disk = health.get("disk")
            ram_text = f"memory ka {ram['used_percent']} percent use ho raha hai" if ram else "memory reading available nahi hai"
            battery_percent = battery["percent"] if battery else None
            battery_text = f"battery {battery_percent} percent hai" if battery and battery["available"] and battery_percent is not None else "battery ka reading available nahi hai"
            disk_free = disk["free_gb"] if disk else "--"
            reply = f"Abhi CPU {cpu}, {ram_text}, {battery_text}, aur disk mein {disk_free} GB khaali hai."
        return {"reply": reply, "actions": [{"name": "get_laptop_health", "result": result}]}

    open_intent = ("open", "launch", "start", "run", "kholo", "khol", "chalao", "chala do", "open kar", "launch kar", "start karo", "on kar", "on karo", "chalu kar", "dikhao", "dikhana", "khol do", "खोलो", "खोल", "चलाओ")
    if not any(phrase in spoken for phrase in open_intent):
        return None
    apps: list[tuple[str, tuple[str, ...]]] = [
        ("whatsapp", ("whatsapp", "what's app", "whats app", "whatssapp", "वॉट्सऐप", "व्हाट्सएप")),
        ("gmail", ("gmail", "जीमेल")),
        ("calculator", ("calculator", "calc", "कैलकुलेटर")),
        ("notepad", ("notepad", "notes", "नोटपैड")),
        ("files", ("file explorer", "explorer", "files", "folder", "फाइल एक्सप्लोरर")),
        ("browser", ("browser", "chrome", "edge", "ब्राउज़र")),
    ]
    for app, names in apps:
        if any(name in spoken for name in names):
            result = run_safe_tool("open_app", {"app": app})
            friendly = {"whatsapp": "WhatsApp khol diya.", "gmail": "Gmail khol diya.", "calculator": "Calculator khol diya.", "notepad": "Notepad khol diya.", "files": "File Explorer khol diya.", "browser": "Browser khol diya."}
            reply = friendly.get(app, result.get("message", f"{app} kholne ki koshish ki.")) if result.get("ok") else result.get("message", "App open nahi ho paaya.")
            return {"reply": reply, "actions": [{"name": "open_app", "result": result}]}
    return None


def execute_computer_action(action: JsonObject) -> JsonObject:
    import windows_control
    kind = action.get("action")
    if kind == "type_text":
        text = str(action.get("text", ""))[:1000]
        windows_control.type_text(text)
    elif kind == "press_key":
        key = str(action.get("key", ""))
        if key not in {"enter", "tab", "escape", "backspace", "delete", "space", "ctrl+l", "ctrl+f", "ctrl+c", "ctrl+v", "ctrl+a", "alt+tab"}:
            return {"ok": False, "message": "That key combination is not allowed."}
        windows_control.press_key(key)
    elif kind == "click":
        width, height = windows_control.screen_size()
        x, y = int(action.get("x", 0)), int(action.get("y", 0))
        if x >= width or y >= height:
            return {"ok": False, "message": f"Coordinates must be inside this screen ({width}×{height})."}
        windows_control.move_pointer(x, y)
        windows_control.click_pointer()
    elif kind == "scroll":
        windows_control.scroll_wheel(int(action.get("amount", 0)))
    else:
        return {"ok": False, "message": "Unsupported computer action."}
    return {"ok": True, "message": "Done."}


def startup_shortcut_path() -> Path:
    appdata = os.environ.get("APPDATA", "")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "JARVIS.lnk"


def set_startup(enabled: bool) -> JsonObject:
    shortcut = startup_shortcut_path()
    if enabled:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "enable_startup.ps1")], capture_output=True, text=True, timeout=15, check=False)
        if result.returncode:
            return {"ok": False, "enabled": shortcut.exists(), "message": result.stderr.strip() or "Could not create the Windows Startup shortcut."}
        return {"ok": True, "enabled": shortcut.exists(), "message": "JARVIS will open when you sign in to Windows."}
    shortcut.unlink(missing_ok=True)
    return {"ok": True, "enabled": False, "message": "JARVIS auto-start is off."}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def _send(self, payload: JsonObject, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> JsonObject:
        size = int(self.headers.get("Content-Length", "0"))
        if size < 0 or size > MAX_BODY:
            raise ValueError("Request is too large.")
        return json.loads(self.rfile.read(size) or b"{}")

    def do_GET(self):
        if self.path == "/api/startup-status":
            self._send({"enabled": startup_shortcut_path().exists()})
            return
        if self.path == "/api/system-health":
            from windows_health import get_laptop_health
            self._send(cast(JsonObject, get_laptop_health()))
            return
        if self.path == "/api/health":
            try:
                tags = ollama("/api/tags", timeout=2).get("models", [])
                available: list[str] = [item.get("name", "") for item in tags]
                self._send({"ok": True, "ollama": True, "model": MODEL, "model_ready": any(m == MODEL or m.startswith(MODEL + ":") for m in available), "model_warm": model_warm})
            except Exception:
                self._send({"ok": True, "ollama": False, "model": MODEL, "model_ready": False, "model_warm": False})
            return
        return super().do_GET()

    def do_POST(self):
        try:
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"}:
                return self._send({"error": "Cross-origin local requests are blocked."}, 403)
            data = self._body()
            if self.path == "/api/chat":
                messages = as_json_objects(data.get("messages"))[-14:]
                if not messages or messages[-1].get("role") != "user":
                    return self._send({"error": "A user message is required."}, 400)
                user_text = str(messages[-1].get("content", ""))
                whatsapp_intent, whatsapp_complete = whatsapp_request_state(user_text)
                whatsapp_send_text = user_text if whatsapp_intent and whatsapp_complete else ""
                if not whatsapp_intent and len(messages) >= 3:
                    previous_assistant = next((str(item.get("content", "")) for item in reversed(messages[:-1]) if item.get("role") == "assistant"), "")
                    previous_user = next((str(item.get("content", "")) for item in reversed(messages[:-1]) if item.get("role") == "user"), "")
                    if "kisko whatsapp bhejna hai" in previous_assistant.casefold() and whatsapp_request_state(previous_user)[0]:
                        combined_request = previous_user + " " + user_text
                        followup_intent, followup_complete = whatsapp_request_state(combined_request)
                        if followup_intent:
                            whatsapp_intent, whatsapp_complete = followup_intent, followup_complete
                            whatsapp_send_text = combined_request if followup_complete else ""
                if whatsapp_intent and not whatsapp_complete:
                    reply = "Kisko WhatsApp bhejna hai, aur exact message kya likhun? Aise bolo: ‘WhatsApp par Rahul ko bhejo: main 10 minute mein aa raha hoon.’"
                    self._send({"reply": reply, "actions": []})
                    return
                quick = None if whatsapp_intent else direct_command(user_text)
                if quick is not None:
                    self._send(quick)
                    return
                prompt: list[JsonObject] = [{"role": "system", "content": SYSTEM}]
                for item in messages:
                    role = item.get("role")
                    if role not in {"user", "assistant"}:
                        continue
                    msg: JsonObject = {"role": role, "content": str(item.get("content", ""))[:8000]}
                    if role == "user" and item.get("image"):
                        image = str(item["image"])
                        if re.fullmatch(r"[A-Za-z0-9+/=]{1,7000000}", image):
                            msg["images"] = [image]
                    prompt.append(msg)
                outcomes: list[JsonObject] = []
                message: JsonObject = {}
                desktop_image_in_prompt = False
                for _ in range(14 if whatsapp_send_text else 4):
                    response = ollama("/api/chat", {"model": MODEL, "messages": prompt, "tools": TOOLS, "stream": False, "think": False, "keep_alive": "30m", "options": {"num_ctx": 4096, "num_predict": 220, "temperature": 0.45}}, timeout=180)
                    message = as_json_object(response.get("message", {}))
                    calls = as_json_objects(message.get("tool_calls"))[:3]
                    if not calls:
                        break
                    prompt.append(message)
                    desktop_image = None
                    for call in calls:
                        fn = as_json_object(call.get("function", {}))
                        tool_name = str(fn.get("name", ""))
                        tool_args = as_json_object(fn.get("arguments", {}))
                        result = run_safe_tool(tool_name, tool_args, user_request=user_text, whatsapp_send_text=whatsapp_send_text, whatsapp_desktop_seen=desktop_image_in_prompt)
                        if result.get("image"):
                            desktop_image = result.pop("image")
                        if whatsapp_send_text and ((tool_name == "open_app" and tool_args.get("app") == "whatsapp") or (tool_name == "computer_input" and result.get("ok"))):
                            desktop_image_in_prompt = False
                        outcomes.append({"name": fn.get("name"), "result": result})
                        prompt.append({"role": "tool", "tool_name": fn.get("name", ""), "content": json.dumps(result, ensure_ascii=False)})
                    if desktop_image:
                        prompt = [item for item in prompt if not (item.get("role") == "user" and str(item.get("content", "")).startswith("Inspect this current desktop screenshot"))]
                        prompt.append({"role": "user", "content": "Inspect this current desktop screenshot and continue the user's request. The screenshot is private and was captured only because Desktop View is enabled.", "images": [desktop_image]})
                        desktop_image_in_prompt = True
                self._send({"reply": message.get("content", "I'm here. What should we do?"), "actions": outcomes})
                return
            if self.path == "/api/approve":
                action = data.get("action", {})
                result = execute_computer_action(action)
                self._send(result, 200 if result.get("ok") else 400)
                return
            if self.path == "/api/gesture-mode":
                global gesture_control_enabled
                gesture_control_enabled = bool(data.get("enabled"))
                self._send({"ok": True, "enabled": gesture_control_enabled})
                return
            if self.path == "/api/desktop-access":
                global desktop_access_enabled
                desktop_access_enabled = bool(data.get("enabled"))
                self._send({"ok": True, "enabled": desktop_access_enabled})
                return
            if self.path == "/api/startup":
                result = set_startup(bool(data.get("enabled")))
                self._send(result, 200 if result.get("ok") else 500)
                return
            if self.path == "/api/gesture":
                if not gesture_control_enabled:
                    return self._send({"error": "Hand control is not enabled."}, 403)
                import windows_control
                width, height = windows_control.screen_size()
                x = round(max(0.0, min(1.0, float(data.get("x", 0.5)))) * (width - 1))
                y = round(max(0.0, min(1.0, float(data.get("y", 0.5)))) * (height - 1))
                scroll = max(-8, min(8, int(data.get("scroll", 0))))
                if scroll:
                    windows_control.scroll_wheel(scroll)
                else:
                    windows_control.move_pointer(x, y)
                if data.get("click") is True:
                    windows_control.click_pointer()
                self._send({"ok": True, "x": x, "y": y})
                return
            if self.path == "/api/open-app":
                result = run_safe_tool("open_app", {"app": data.get("app")})
                self._send(result, 200 if result.get("ok") else 400)
                return
            self._send({"error": "Not found"}, 404)
        except urllib.error.URLError as exc:
            self._send({"error": f"I can't reach Ollama at {OLLAMA_URL}. Start Ollama and download {MODEL} first."}, 503)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send({"error": str(exc)}, 400)
        except Exception as exc:
            self._send({"error": f"JARVIS encountered an error: {exc}"}, 500)


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"JARVIS is running at http://{HOST}:{PORT}")
    print(f"AI model: {MODEL} (make sure Ollama is running and the model is downloaded)")
    print("Press Ctrl+C to stop JARVIS.")
    def warm_model() -> None:
        global model_warm
        for _ in range(12):
            try:
                ollama("/api/chat", {"model": MODEL, "messages": [{"role": "user", "content": "Say ready."}], "stream": False, "think": False, "keep_alive": "30m", "options": {"num_ctx": 4096, "num_predict": 4, "temperature": 0}}, timeout=90)
                model_warm = True
                print(f"{MODEL} is warm and ready.")
                return
            except Exception:
                time.sleep(5)
        print("Model warm-up failed. Check Ollama and rerun setup.bat if needed.")
    threading.Thread(target=warm_model, daemon=True, name="jarvis-model-warmup").start()
    threading.Timer(1.0, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down JARVIS...")
        server.shutdown()
        server.server_close()
