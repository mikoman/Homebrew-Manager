#!/usr/bin/env python3
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import threading
from typing import Dict, List, Optional, Union
import time
import pty
import select
from http.server import SimpleHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")


# Basic keyword-based categories for packages
CATEGORY_KEYWORDS = {
    "development": [
        "compiler",
        "build",
        "code",
        "programming",
        "sdk",
        "language",
        "git",
        "deploy",
    ],
    "utilities": [
        "utility",
        "tool",
        "command-line",
        "helper",
        "file",
        "archive",
        "compression",
        "encrypt",
        "monitor",
    ],
    "networking": [
        "network",
        "ssh",
        "http",
        "dns",
        "server",
        "proxy",
        "ftp",
        "socket",
        "vpn",
        "web",
    ],
    "database": [
        "database",
        "sql",
        "mysql",
        "postgres",
        "mongo",
        "sqlite",
        "redis",
        "cassandra",
    ],
    "media": [
        "audio",
        "video",
        "image",
        "media",
        "music",
        "photo",
        "graphics",
        "ffmpeg",
    ],
    "system": [
        "system",
        "kernel",
        "hardware",
        "driver",
        "daemon",
        "process",
    ],
}
DEFAULT_CATEGORY = "other"


def categorize_item(item: Dict[str, Union[str, List[str]]]) -> str:
    """Assign a simple category based on name/description keywords."""
    text = f"{item.get('name', '')} {item.get('desc', '')}".lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return category
    return DEFAULT_CATEGORY


def find_brew_path() -> str:
    # Try PATH first
    path = shutil.which("brew")
    if path:
        return path
    # Common locations
    candidates = [
        "/opt/homebrew/bin/brew",  # Apple Silicon
        "/usr/local/bin/brew",     # Intel
        "/home/linuxbrew/.linuxbrew/bin/brew",  # Linuxbrew (just in case)
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return "brew"  # fallback to PATH; will fail later if missing


class BrewError(Exception):
    def __init__(self, message: str, needs_sudo: bool = False, permission_issue: bool = False):
        super().__init__(message)
        self.needs_sudo = needs_sudo
        self.permission_issue = permission_issue


class BrewManager:
    def __init__(self, timeout_seconds: int = 120):
        self.brew_path = find_brew_path()
        self.timeout_seconds = timeout_seconds
        self.lock = threading.Lock()

    def run(self, args, capture_json: bool = False, sudo_password: str = None) -> Union[dict, str]:
        cmd = [self.brew_path] + args
        env = os.environ.copy()
        env.setdefault("LC_ALL", "C.UTF-8")
        env.setdefault("LANG", "C.UTF-8")
        try:
            # Some brew commands mutate shared state; serialize to avoid overlapping runs
            with self.lock:
                if sudo_password:
                    # If we have a sudo password, set up the environment to use it
                    env['SUDO_ASKPASS'] = '/bin/echo'
                    # Use expect-like approach or write password to stdin
                    proc = subprocess.Popen(
                        cmd,
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        stdin=subprocess.PIPE,
                        text=True,
                    )
                    stdout, stderr = proc.communicate(input=f"{sudo_password}\n", timeout=self.timeout_seconds)
                    result = type('Result', (), {
                        'returncode': proc.returncode,
                        'stdout': stdout,
                        'stderr': stderr
                    })()
                    # Clear password from memory
                    sudo_password = None
                    del sudo_password
                else:
                    result = subprocess.run(
                        cmd,
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=self.timeout_seconds,
                        text=True,
                    )
        except FileNotFoundError as e:
            raise BrewError("Homebrew not found. Please install Homebrew from https://brew.sh") from e
        except subprocess.TimeoutExpired as e:
            raise BrewError(f"Command timed out: {' '.join(cmd)}") from e

        if result.returncode != 0:
            error_output = result.stderr.strip()
            stdout_output = result.stdout.strip()
            combined_output = f"{error_output}\n{stdout_output}".strip()
            
            # Detect permission-related issues
            needs_sudo = False
            permission_issue = False
            
            permission_indicators = [
                "Permission denied",
                "Operation not permitted", 
                "You don't have write permissions",
                "requires administrator access",
                "sudo",
                "privilege"
            ]
            
            sudo_indicators = [
                "installer: Package name is",  # System installer requiring sudo
                "requires administrator access", 
                "must be run as root",
                "sudo required",
                "sudo: a terminal is required to read the password",
                "sudo: a password is required", 
                "either use the -S option to read from standard input",
                "configure an askpass helper"
            ]
            
            for indicator in permission_indicators:
                if indicator.lower() in combined_output.lower():
                    permission_issue = True
                    break
                    
            for indicator in sudo_indicators:
                if indicator.lower() in combined_output.lower():
                    needs_sudo = True
                    break
            
            # Create enhanced error message
            if needs_sudo or permission_issue:
                if needs_sudo:
                    enhanced_message = f"Administrative privileges required: {combined_output}"
                else:
                    enhanced_message = f"Permission issue detected: {combined_output}"
            else:
                enhanced_message = combined_output or f"Command failed: {' '.join(cmd)}"
            
            raise BrewError(enhanced_message, needs_sudo=needs_sudo, permission_issue=permission_issue)

        output = result.stdout
        if capture_json:
            try:
                return json.loads(output)
            except json.JSONDecodeError:
                raise BrewError("Failed to parse JSON output from brew")
        return output

    def validate_sudo(self, password: str) -> None:
        """Validate sudo timestamp using the provided password (non-interactive)."""
        if not password:
            raise BrewError("Sudo password required", needs_sudo=True)
        try:
            proc = subprocess.run(
                ["/usr/bin/sudo", "-S", "-v"],
                input=f"{password}\n",
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
            )
        except Exception as e:
            raise BrewError("Failed to validate sudo", needs_sudo=True) from e
        finally:
            # Best-effort clear
            password = None
        if proc.returncode != 0:
            raise BrewError(proc.stderr.strip() or "Invalid sudo password", needs_sudo=True)

    def run_streaming(self, args, sudo_password: str = None):
        """Run a brew command and yield output lines progressively.

        Combines stdout and stderr to preserve order. Yields text lines as they arrive.
        """
        cmd = [self.brew_path] + args
        env = os.environ.copy()
        env.setdefault("LC_ALL", "C.UTF-8")
        env.setdefault("LANG", "C.UTF-8")
        # Serialize brew invocations to avoid state corruption
        with self.lock:
            try:
                # Always allocate a PTY so that any sudo prompts go to the PTY, not the server terminal
                if sudo_password:
                    self.validate_sudo(sudo_password)
                master_fd, slave_fd = pty.openpty()
                proc = subprocess.Popen(
                    cmd,
                    env=env,
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    bufsize=0,
                    close_fds=True,
                )
                # We will read from master_fd below
            except FileNotFoundError as e:
                raise BrewError("Homebrew not found. Please install Homebrew from https://brew.sh") from e
            # Stream lines and collect output for error analysis
            collected_output = []
            try:
                # Read bytes from PTY master and decode incrementally
                buffer = ""
                while True:
                    r, _, _ = select.select([master_fd], [], [], 0.1)
                    if master_fd in r:
                        try:
                            chunk = os.read(master_fd, 4096)
                        except OSError:
                            chunk = b""
                        if not chunk:
                            if proc.poll() is not None:
                                break
                            continue
                        buffer += chunk.decode("utf-8", errors="replace")
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line_clean = line.rstrip("\r")
                            collected_output.append(line_clean)
                            yield line_clean
                    if proc.poll() is not None:
                        # drain remaining buffer
                        if buffer:
                            for rem_line in buffer.splitlines():
                                line_clean = rem_line.rstrip("\r")
                                collected_output.append(line_clean)
                                yield line_clean
                        break
            finally:
                # Ensure process completes
                proc.wait()
                try:
                    os.close(master_fd)
                    os.close(slave_fd)
                except Exception:
                    pass
            if proc.returncode != 0:
                # Analyze collected output for sudo/permission issues (same logic as run method)
                combined_output = "\n".join(collected_output)
                needs_sudo = False
                permission_issue = False
                
                permission_indicators = [
                    "Permission denied",
                    "Operation not permitted", 
                    "You don't have write permissions",
                    "requires administrator access",
                    "sudo",
                    "privilege"
                ]
                
                sudo_indicators = [
                    "installer: Package name is",  # System installer requiring sudo
                    "requires administrator access", 
                    "must be run as root",
                    "sudo required",
                    "sudo: a terminal is required to read the password",
                    "sudo: a password is required", 
                    "either use the -S option to read from standard input",
                    "configure an askpass helper"
                ]
                
                for indicator in permission_indicators:
                    if indicator.lower() in combined_output.lower():
                        permission_issue = True
                        break
                        
                for indicator in sudo_indicators:
                    if indicator.lower() in combined_output.lower():
                        needs_sudo = True
                        break
                
                # Create enhanced error message
                if needs_sudo or permission_issue:
                    if needs_sudo:
                        enhanced_message = f"Administrative privileges required: Command failed ({proc.returncode}): {' '.join(cmd)}"
                    else:
                        enhanced_message = f"Permission issue detected: Command failed ({proc.returncode}): {' '.join(cmd)}"
                else:
                    enhanced_message = f"Command failed ({proc.returncode}): {' '.join(cmd)}"
                
                raise BrewError(enhanced_message, needs_sudo=needs_sudo, permission_issue=permission_issue)

    # Data fetchers
    def outdated(self) -> dict:
        data = self.run(["outdated", "--greedy", "--json=v2"], capture_json=True)
        
        # Enhance with descriptions by getting info for each outdated package
        formulae = data.get("formulae", [])
        casks = data.get("casks", [])
        
        # Get descriptions for outdated formulae
        for formula in formulae:
            try:
                # Get info for each formula individually to be more reliable
                formula_info = self.run(["info", "--json=v2", "--formula", formula["name"]], capture_json=True)
                formulae_list = formula_info.get("formulae", [])
                if formulae_list:
                    formula["desc"] = formulae_list[0].get("desc", "")
                else:
                    formula["desc"] = ""
            except Exception as e:
                print(f"Failed to fetch description for formula {formula['name']}: {e}")
                formula["desc"] = ""
        
        # Get descriptions for outdated casks
        for cask in casks:
            try:
                # Get info for each cask individually to be more reliable
                cask_info = self.run(["info", "--json=v2", "--cask", cask["name"]], capture_json=True)
                casks_list = cask_info.get("casks", [])
                if casks_list:
                    cask["desc"] = casks_list[0].get("desc", "")
                else:
                    cask["desc"] = ""
            except Exception as e:
                print(f"Failed to fetch description for cask {cask['name']}: {e}")
                cask["desc"] = ""
        
        return {
            "formulae": formulae,
            "casks": casks,
        }

    def installed_info(self) -> dict:
        formulae = self.run(["info", "--json=v2", "--installed", "--formula"], capture_json=True)
        casks = self.run(["info", "--json=v2", "--installed", "--cask"], capture_json=True)
        formulae_list = formulae.get("formulae", [])
        casks_list = casks.get("casks", [])
        for item in formulae_list:
            item["category"] = categorize_item(item)
        for item in casks_list:
            item["category"] = categorize_item(item)
        return {
            "formulae": formulae_list,
            "casks": casks_list,
        }

    def leaves(self) -> List[str]:
        output = self.run(["leaves"])  # lists leaf formulae
        return [line.strip() for line in output.splitlines() if line.strip()]

    def deprecated(self) -> dict:
        info = self.installed_info()
        def pick_deprecated(items, kind: str):
            deprecated_items = []
            for item in items:
                # formula JSON uses keys directly; cask JSON nests fewer details
                is_deprecated = bool(item.get("deprecated")) or bool(item.get("disabled"))
                if is_deprecated:
                    deprecated_items.append({
                        "name": item.get("name"),
                        "full_name": item.get("full_name") or item.get("token"),
                        "token": item.get("token"),
                        "versions": item.get("versions"),
                        "desc": item.get("desc"),
                        "homepage": item.get("homepage"),
                        "deprecated": item.get("deprecated", False),
                        "disabled": item.get("disabled", False),
                        "deprecation_date": item.get("deprecation_date"),
                        "deprecation_reason": item.get("deprecation_reason"),
                        "type": kind,
                    })
            return deprecated_items
        return {
            "formulae": pick_deprecated(info.get("formulae", []), "formula"),
            "casks": pick_deprecated(info.get("casks", []), "cask"),
        }

    def orphaned(self) -> dict:
        # Orphaned = leaves that were installed as dependency, not on request
        leaves = set(self.leaves())
        installed = self.installed_info().get("formulae", [])
        orphaned_list = []
        for item in installed:
            name = item.get("name")
            if name not in leaves:
                continue
            installed_meta = item.get("installed", [])
            if not installed_meta:
                continue
            # If all installed entries are dependency-only and not on-request -> orphaned
            all_dependency_only = True
            for inst in installed_meta:
                if inst.get("installed_on_request"):
                    all_dependency_only = False
                    break
                if not inst.get("installed_as_dependency"):
                    all_dependency_only = False
                    break
            if all_dependency_only:
                orphaned_list.append({
                    "name": name,
                    "full_name": item.get("full_name", name),
                    "desc": item.get("desc"),
                    "versions": item.get("versions"),
                    "type": "formula",
                })
        return {"formulae": orphaned_list, "casks": []}

    # Actions
    def needs_update(self) -> bool:
        # Check if homebrew needs updating by checking outdated status
        try:
            # Use 'brew outdated --greedy --verbose' to check if brew itself needs updating
            output = self.run(["outdated", "--greedy", "--verbose"])
            # If there's any output, homebrew or its dependencies need updating
            return bool(output.strip())
        except:
            # If command fails, assume no update needed
            return False

    def update(self) -> str:
        # Update brew metadata
        return self.run(["update"])  # textual output

    def upgrade(self, formulae: Optional[List[str]] = None, casks: Optional[List[str]] = None, sudo_password: Optional[str] = None) -> dict:
        logs: Dict[str, str] = {}
        if sudo_password:
            # Validate once so casks can leverage cached sudo in the session
            self.validate_sudo(sudo_password)
        if formulae:
            logs["formulae"] = self.run(["upgrade", "--formula", *formulae])
        if casks:
            logs["casks"] = self.run(["upgrade", "--cask", *casks])
        if not formulae and not casks:
            logs["all"] = self.run(["upgrade"])  # upgrade everything outdated
        return logs

    def backup(self) -> dict:
        """Return lists of installed formulae and casks for backup purposes."""
        formulae_out = self.run(["list", "--formula", "-1"])
        casks_out = self.run(["list", "--cask", "-1"])
        return {
            "formulae": [line.strip() for line in formulae_out.splitlines() if line.strip()],
            "casks": [line.strip() for line in casks_out.splitlines() if line.strip()],
        }

    def restore(self, formulae: Optional[List[str]] = None, casks: Optional[List[str]] = None, sudo_password: Optional[str] = None) -> dict:
        """Install packages from a backup list."""
        logs: Dict[str, str] = {}
        if formulae:
            logs["formulae"] = self.run(["install", *formulae], sudo_password=sudo_password)
        if casks:
            logs["casks"] = self.run(["install", "--cask", *casks], sudo_password=sudo_password)
        return logs

    def search(self, query: str) -> dict:
        # Simple name search for both kinds
        f_out = self.run(["search", "--formula", query])
        c_out = self.run(["search", "--cask", query])
        def parse_list(text):
            items = []
            for line in text.splitlines():
                name = line.strip()
                if name and not name.startswith("==>"):
                    items.append(name)
            return items
        
        formulae = parse_list(f_out)
        casks = parse_list(c_out)
        
        # Enhance with descriptions (limit to first 20 results for performance)
        enhanced_formulae = []
        for name in formulae[:20]:
            try:
                info = self.run(["info", "--json=v2", "--formula", name], capture_json=True)
                formula_info = info.get("formulae", [])
                if formula_info:
                    enhanced_formulae.append({
                        "name": name,
                        "desc": formula_info[0].get("desc", "")
                    })
                else:
                    enhanced_formulae.append({"name": name, "desc": ""})
            except:
                enhanced_formulae.append({"name": name, "desc": ""})
        
        enhanced_casks = []
        for name in casks[:20]:
            try:
                info = self.run(["info", "--json=v2", "--cask", name], capture_json=True)
                cask_info = info.get("casks", [])
                if cask_info:
                    enhanced_casks.append({
                        "name": name,
                        "desc": cask_info[0].get("desc", "")
                    })
                else:
                    enhanced_casks.append({"name": name, "desc": ""})
            except:
                enhanced_casks.append({"name": name, "desc": ""})
        
        return {"formulae": enhanced_formulae, "casks": enhanced_casks}

    def install(self, name: str, kind: str) -> str:
        if kind == "cask":
            return self.run(["install", "--cask", name])
        return self.run(["install", name])

    def uninstall(self, name: str, kind: str) -> str:
        if kind == "cask":
            return self.run(["uninstall", "--cask", name])
        return self.run(["uninstall", name])

    def info(self, name: str, kind: str) -> dict:
        if kind == "cask":
            data = self.run(["info", "--json=v2", "--cask", name], capture_json=True)
            # Normalize
            items = data.get("casks", [])
            return items[0] if items else {}
        data = self.run(["info", "--json=v2", "--formula", name], capture_json=True)
        items = data.get("formulae", [])
        return items[0] if items else {}


brew = BrewManager(timeout_seconds=10 * 60)  # allow long upgrades


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def translate_path(self, path):
        # Serve files from STATIC_DIR for non-API paths
        path = urlparse(path).path
        path = posixpath.normpath(path)
        if path.startswith("/api/"):
            return ""  # not used
        if path == "/":
            return os.path.join(STATIC_DIR, "index.html")
        # sanitize
        parts = [p for p in path.split("/") if p and p not in ("..", ".")]
        return os.path.join(STATIC_DIR, *parts)

    def end_headers(self):
        # Basic CORS for local use
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/api/"):
            self._handle_api_get()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            self._handle_api_post()
        else:
            self.send_error(404, "Not Found")

    def _send_json(self, payload: dict, status: int = 200):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _parse_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _handle_api_get(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        try:
            if path == "/api/update_stream":
                # SSE stream for `brew update`
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                # Helper to send SSE event
                def send_event(event: str, data: str):
                    payload = f"event: {event}\n" + "\n".join(f"data: {line}" for line in data.splitlines() or [""]) + "\n\n"
                    self.wfile.write(payload.encode("utf-8"))
                    self.wfile.flush()
                try:
                    send_event("start", "Updating Homebrew metadata...")
                    for line in brew.run_streaming(["update"]):
                        send_event("log", line)
                    send_event("end", "ok")
                except BrewError as e:
                    error_msg = str(e)
                    if getattr(e, 'needs_sudo', False):
                        error_msg += " | REQUIRES_SUDO"
                    elif getattr(e, 'permission_issue', False):
                        error_msg += " | PERMISSION_ISSUE"
                    send_event("error", error_msg)
                except Exception as e:
                    send_event("error", f"Unexpected error: {e}")
                return
            if path == "/api/install_stream":
                name = (qs.get("name", [""])[0] or "").strip()
                kind = (qs.get("type", ["formula"])[0] or "formula").strip()
                if not name:
                    self.send_response(400)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    self.wfile.write(b"event: error\ndata: name is required\n\n")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                def send_event(event: str, data: str):
                    payload = f"event: {event}\n" + "\n".join(f"data: {line}" for line in data.splitlines() or [""]) + "\n\n"
                    self.wfile.write(payload.encode("utf-8"))
                    self.wfile.flush()
                try:
                    send_event("start", f"Installing {name} ({kind})...")
                    args = ["install"]
                    if kind == "cask":
                        args += ["--cask", name]
                    else:
                        args += [name]
                    for line in brew.run_streaming(args):
                        send_event("log", line)
                    send_event("end", "ok")
                except BrewError as e:
                    error_msg = str(e)
                    if getattr(e, 'needs_sudo', False):
                        error_msg += " | REQUIRES_SUDO"
                    elif getattr(e, 'permission_issue', False):
                        error_msg += " | PERMISSION_ISSUE"
                    send_event("error", error_msg)
                except Exception as e:
                    send_event("error", f"Unexpected error: {e}")
                return
            if path == "/api/uninstall_stream":
                name = (qs.get("name", [""])[0] or "").strip()
                kind = (qs.get("type", ["formula"])[0] or "formula").strip()
                if not name:
                    self.send_response(400)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    self.wfile.write(b"event: error\ndata: name is required\n\n")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                def send_event(event: str, data: str):
                    payload = f"event: {event}\n" + "\n".join(f"data: {line}" for line in data.splitlines() or [""]) + "\n\n"
                    self.wfile.write(payload.encode("utf-8"))
                    self.wfile.flush()
                try:
                    send_event("start", f"Uninstalling {name} ({kind})...")
                    args = ["uninstall"]
                    if kind == "cask":
                        args += ["--cask", name]
                    else:
                        args += [name]
                    for line in brew.run_streaming(args):
                        send_event("log", line)
                    send_event("end", "ok")
                except BrewError as e:
                    error_msg = str(e)
                    if getattr(e, 'needs_sudo', False):
                        error_msg += " | REQUIRES_SUDO"
                    elif getattr(e, 'permission_issue', False):
                        error_msg += " | PERMISSION_ISSUE"
                    send_event("error", error_msg)
                except Exception as e:
                    send_event("error", f"Unexpected error: {e}")
                return
            if path == "/api/upgrade_stream":
                # SSE stream for `brew upgrade` - can handle both GET and POST
                if self.command == "GET":
                    formulae = qs.get("formulae", [])
                    casks = qs.get("casks", [])
                    sudo_password = None
                else:
                    # POST with JSON body containing password
                    body = self._parse_body()
                    formulae = body.get("formulae", [])
                    casks = body.get("casks", [])
                    sudo_password = body.get("sudo_password")
                    if sudo_password:
                        try:
                            brew.validate_sudo(sudo_password)
                        except BrewError as e:
                            self.send_response(200)
                            self.send_header("Content-Type", "text/event-stream")
                            self.send_header("Cache-Control", "no-cache")
                            self.send_header("Connection", "keep-alive")
                            self.end_headers()
                            payload = f"event: error\n" + "\n".join(f"data: {line}" for line in str(e).splitlines() or [""]) + "\n\n"
                            self.wfile.write(payload.encode("utf-8"))
                            self.wfile.flush()
                            return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                def send_event(event: str, data: str):
                    payload = f"event: {event}\n" + "\n".join(f"data: {line}" for line in data.splitlines() or [""]) + "\n\n"
                    self.wfile.write(payload.encode("utf-8"))
                    self.wfile.flush()
                try:
                    if formulae or casks:
                        summary = []
                        if formulae:
                            summary.append(f"formulae: {', '.join(formulae)}")
                        if casks:
                            summary.append(f"casks: {', '.join(casks)}")
                        send_event("start", "Upgrading selected (" + "; ".join(summary) + ")...")
                        if formulae:
                            send_event("start", "Upgrading formulae...")
                            for line in brew.run_streaming(["upgrade", "--formula", *formulae], sudo_password=sudo_password):
                                send_event("log", line)
                            send_event("log", "Formulae upgraded")
                        if casks:
                            send_event("start", "Upgrading casks...")
                            for line in brew.run_streaming(["upgrade", "--cask", *casks], sudo_password=sudo_password):
                                send_event("log", line)
                            send_event("log", "Casks upgraded")
                    else:
                        send_event("start", "Upgrading all outdated packages...")
                        for line in brew.run_streaming(["upgrade"], sudo_password=sudo_password):
                            send_event("log", line)
                    send_event("end", "ok")
                except BrewError as e:
                    error_msg = str(e)
                    if getattr(e, 'needs_sudo', False):
                        error_msg += " | REQUIRES_SUDO"
                    elif getattr(e, 'permission_issue', False):
                        error_msg += " | PERMISSION_ISSUE"
                    send_event("error", error_msg)
                except Exception as e:
                    send_event("error", f"Unexpected error: {e}")
                return
            if path == "/api/health":
                # Quick check for brew existence
                version = brew.run(["--version"]).splitlines()[0]
                needs_update = brew.needs_update()
                self._send_json({"ok": True, "brew": version, "needs_update": needs_update})
                return
            if path == "/api/summary":
                out = brew.outdated()
                dep = brew.deprecated()
                orph = brew.orphaned()
                inst = brew.installed_info()
                self._send_json({"outdated": out, "deprecated": dep, "orphaned": orph, "installed": inst})
                return
            if path == "/api/packages":
                self._send_json({
                    "outdated": brew.outdated(),
                    "installed": brew.installed_info(),
                })
                return
            if path == "/api/installed":
                self._send_json(brew.installed_info())
                return
            if path == "/api/backup":
                self._send_json(brew.backup())
                return
            if path == "/api/outdated":
                self._send_json(brew.outdated())
                return
            if path == "/api/deprecated":
                self._send_json(brew.deprecated())
                return
            if path == "/api/orphaned":
                self._send_json(brew.orphaned())
                return
            if path == "/api/search":
                q = (qs.get("q", [""])[0] or "").strip()
                if not q:
                    self._send_json({"formulae": [], "casks": []})
                    return
                self._send_json(brew.search(q))
                return
            if path == "/api/info":
                name = (qs.get("name", [""])[0] or "").strip()
                kind = (qs.get("type", ["formula"])[0] or "formula").strip()
                if not name:
                    self._send_json({}, 400)
                    return
                self._send_json(brew.info(name, kind))
                return
            self.send_error(404, "Unknown API endpoint")
        except BrewError as e:
            error_response = {
                "ok": False, 
                "error": str(e),
                "needs_sudo": getattr(e, 'needs_sudo', False),
                "permission_issue": getattr(e, 'permission_issue', False)
            }
            self._send_json(error_response, 500)
        except Exception as e:
            self._send_json({"ok": False, "error": f"Unexpected error: {e}"}, 500)

    def _handle_api_post(self):
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._parse_body()
        try:
            if path == "/api/sudo/validate":
                password = body.get("sudo_password")
                if not password:
                    self._send_json({"ok": False, "error": "sudo_password is required"}, 400)
                    return
                try:
                    brew.validate_sudo(password)
                except BrewError as e:
                    self._send_json({"ok": False, "error": str(e)}, 401)
                    return
                self._send_json({"ok": True})
                return
            if path == "/api/update":
                text = brew.update()
                self._send_json({"ok": True, "log": text})
                return
            if path == "/api/upgrade":
                formulae = body.get("formulae") or []
                casks = body.get("casks") or []
                sudo_password = body.get("sudo_password")
                logs = brew.upgrade(formulae=formulae, casks=casks, sudo_password=sudo_password)
                self._send_json({"ok": True, "logs": logs})
                return
            if path == "/api/upgrade_stream":
                # Handle POST to streaming endpoint (for password support)
                return self._handle_api_get()
            if path == "/api/install":
                name = body.get("name")
                kind = body.get("type") or "formula"
                if not name:
                    self._send_json({"ok": False, "error": "name is required"}, 400)
                    return
                log = brew.install(name, kind)
                self._send_json({"ok": True, "log": log})
                return
            if path == "/api/uninstall":
                name = body.get("name")
                kind = body.get("type") or "formula"
                if not name:
                    self._send_json({"ok": False, "error": "name is required"}, 400)
                    return
                log = brew.uninstall(name, kind)
                self._send_json({"ok": True, "log": log})
                return
            if path == "/api/restore":
                formulae = body.get("formulae") or []
                casks = body.get("casks") or []
                sudo_password = body.get("sudo_password")
                logs = brew.restore(formulae=formulae, casks=casks, sudo_password=sudo_password)
                self._send_json({"ok": True, "logs": logs})
                return
            self.send_error(404, "Unknown API endpoint")
        except BrewError as e:
            error_response = {
                "ok": False,
                "error": str(e),
                "needs_sudo": getattr(e, 'needs_sudo', False),
                "permission_issue": getattr(e, 'permission_issue', False)
            }
            self._send_json(error_response, 500)
        except Exception as e:
            self._send_json({"ok": False, "error": f"Unexpected error: {e}"}, 500)


def run(server_class=HTTPServer, handler_class=Handler, port: int = 8765):
    os.chdir(PROJECT_ROOT)
    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler_class)
    print(f"Homebrew Manager running at http://127.0.0.1:{port}")
    print("Press Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    run(port=port)
