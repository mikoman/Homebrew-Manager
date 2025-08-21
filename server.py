#!/usr/bin/env python3
import json
import logging
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
from logging.handlers import RotatingFileHandler
from http.server import SimpleHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")

# Logging setup
LOG_PATH = os.path.join(PROJECT_ROOT, "homebrew_manager.log")
logger = logging.getLogger("homebrew_manager")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3)
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_handler)

# Cache directory for offline data
CACHE_DIR = os.path.join(PROJECT_ROOT, ".cache")
os.makedirs(CACHE_DIR, exist_ok=True)


def _read_cache(name: str) -> Optional[dict]:
    path = os.path.join(CACHE_DIR, f"{name}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(name: str, data: dict) -> None:
    path = os.path.join(CACHE_DIR, f"{name}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        logger.exception("Failed to write cache %s", name)


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


def dir_size_kb(path: str) -> int:
    """Calculate directory size in kilobytes."""
    try:
        result = subprocess.run(["du", "-sk", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0 and result.stdout:
            return int(result.stdout.split()[0])
    except Exception:
        pass
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                continue
    return total // 1024


def human_size(kb: int) -> str:
    """Convert kilobytes to human readable string."""
    units = ["KB", "MB", "GB", "TB", "PB"]
    size = float(kb)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "KB":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024


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
    def __init__(self, timeout_seconds: int = 120, cache_ttl: int = 30):
        self.brew_path = find_brew_path()
        self.timeout_seconds = timeout_seconds
        self.lock = threading.Lock()
        self.cache_ttl = cache_ttl
        # Simple in-memory caches to avoid repeated brew invocations
        self._installed_cache: Optional[dict] = None
        self._installed_cache_time: float = 0.0
        self._search_cache: Dict[str, tuple] = {}

    def _cache_valid(self, ts: float) -> bool:
        return (time.time() - ts) < self.cache_ttl

    def invalidate_caches(self) -> None:
        self._installed_cache = None
        self._search_cache.clear()

    def run(self, args, capture_json: bool = False, sudo_password: str = None) -> Union[dict, str]:
        cmd = [self.brew_path] + args
        env = os.environ.copy()
        env.setdefault("LC_ALL", "C.UTF-8")
        env.setdefault("LANG", "C.UTF-8")
        logger.debug("brew %s", " ".join(args))
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
            logger.error("Homebrew not found: %s", e)
            raise BrewError("Homebrew not found. Please install Homebrew from https://brew.sh") from e
        except subprocess.TimeoutExpired as e:
            logger.error("Command timed out: %s", " ".join(cmd))
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
            
            logger.error("Brew command failed: %s", enhanced_message)
            raise BrewError(enhanced_message, needs_sudo=needs_sudo, permission_issue=permission_issue)

        output = result.stdout
        if capture_json:
            try:
                return json.loads(output)
            except json.JSONDecodeError:
                logger.error("Failed to parse JSON output from brew: %s", output[:200])
                raise BrewError("Failed to parse JSON output from brew")
        logger.debug("brew command succeeded: %s", " ".join(args))
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
        cache_name = "outdated"
        try:
            data = self.run(["outdated", "--greedy", "--json=v2"], capture_json=True)
        except BrewError as e:
            cached = _read_cache(cache_name)
            if cached is not None:
                logger.warning("Using cached outdated data: %s", e)
                return cached
            raise

        # Enhance with descriptions by getting info for each outdated package
        formulae = data.get("formulae", [])
        casks = data.get("casks", [])

        # Get descriptions and disk usage for outdated formulae
        usage = self.disk_usage()
        size_map = {u["name"]: u for u in usage.get("formulae", [])}
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
                logger.debug("Failed to fetch description for formula %s: %s", formula['name'], e)
                formula["desc"] = ""
            u = size_map.get(formula.get("name"))
            if u:
                formula["size_kb"] = u.get("kilobytes")
                formula["size"] = u.get("human")

        # Get descriptions and disk usage for outdated casks
        size_map_c = {u["name"]: u for u in usage.get("casks", [])}
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
                logger.debug("Failed to fetch description for cask %s: %s", cask['name'], e)
                cask["desc"] = ""
            u = size_map_c.get(cask.get("name"))
            if u:
                cask["size_kb"] = u.get("kilobytes")
                cask["size"] = u.get("human")

        result = {"formulae": formulae, "casks": casks}
        _write_cache(cache_name, result)
        return result

    def installed_info(self) -> dict:
        cache_name = "installed"
        if self._installed_cache and self._cache_valid(self._installed_cache_time):
            return self._installed_cache
        try:
            formulae = self.run(["info", "--json=v2", "--installed", "--formula"], capture_json=True)
            casks = self.run(["info", "--json=v2", "--installed", "--cask"], capture_json=True)
        except BrewError as e:
            cached = _read_cache(cache_name)
            if cached is not None:
                logger.warning("Using cached installed info: %s", e)
                self._installed_cache = cached
                self._installed_cache_time = time.time()
                return cached
            raise

        formulae_list = formulae.get("formulae", [])
        casks_list = casks.get("casks", [])
        usage = self.disk_usage()
        size_map = {u["name"]: u for u in usage.get("formulae", [])}
        size_map.update({u["name"]: u for u in usage.get("casks", [])})
        for item in formulae_list:
            item["category"] = categorize_item(item)
            u = size_map.get(item.get("name"))
            if u:
                item["size_kb"] = u.get("kilobytes")
                item["size"] = u.get("human")
        for item in casks_list:
            item["category"] = categorize_item(item)
            key = item.get("token") or item.get("name")
            if isinstance(key, list):
                key = key[0] if key else None
            u = size_map.get(key)
            if u:
                item["size_kb"] = u.get("kilobytes")
                item["size"] = u.get("human")
        result = {"formulae": formulae_list, "casks": casks_list}
        self._installed_cache = result
        self._installed_cache_time = time.time()
        _write_cache(cache_name, result)
        return result

    def disk_usage(self) -> dict:
        """Return disk usage for installed formulae and casks."""
        usage = {"formulae": [], "casks": []}
        try:
            names = [n.strip() for n in self.run(["list", "--formula"]).splitlines() if n.strip()]
            for name in names:
                path = self.run(["--cellar", name]).strip()
                if not path:
                    continue
                size = dir_size_kb(path)
                usage["formulae"].append({
                    "name": name,
                    "kilobytes": size,
                    "human": human_size(size),
                })
        except BrewError:
            pass
        try:
            caskroom = self.run(["--caskroom"]).strip()
            names = [n.strip() for n in self.run(["list", "--cask"]).splitlines() if n.strip()]
            for name in names:
                path = os.path.join(caskroom, name)
                if not os.path.exists(path):
                    continue
                size = dir_size_kb(path)
                usage["casks"].append({
                    "name": name,
                    "kilobytes": size,
                    "human": human_size(size),
                })
        except BrewError:
            pass
        usage["formulae"].sort(key=lambda x: x["kilobytes"], reverse=True)
        usage["casks"].sort(key=lambda x: x["kilobytes"], reverse=True)
        return usage

    def leaves(self) -> List[str]:
        cache_name = "leaves"
        try:
            output = self.run(["leaves"])  # lists leaf formulae
            result = [line.strip() for line in output.splitlines() if line.strip()]
            _write_cache(cache_name, result)
            return result
        except BrewError as e:
            cached = _read_cache(cache_name)
            if cached is not None:
                logger.warning("Using cached leaves: %s", e)
                return cached
        return []

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
                        "size_kb": item.get("size_kb"),
                        "size": item.get("size"),
                    })
            return deprecated_items
        return {
            "formulae": pick_deprecated(info.get("formulae", []), "formula"),
            "casks": pick_deprecated(info.get("casks", []), "cask"),
        }

    def orphaned(self) -> dict:
        cache_name = "orphaned"
        try:
            # Orphaned = leaves that were installed as dependency, not on request
            leaves = set(self.leaves())
            installed = self.installed_info().get("formulae", [])
        except BrewError as e:
            cached = _read_cache(cache_name)
            if cached is not None:
                logger.warning("Using cached orphaned data: %s", e)
                return cached
            raise

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
        result = {"formulae": orphaned_list, "casks": []}
        _write_cache(cache_name, result)
        return result

    def dependency_tree(self, name: str, kind: str = "formula") -> dict:
        """Return dependency tree for a given package."""

        visited = set()

        def build(node_name: str, node_kind: str = "formula", optional: bool = False) -> dict:
            key = (node_kind, node_name)
            if key in visited:
                return {"name": node_name, "type": node_kind, "optional": optional, "deps": []}
            visited.add(key)

            if node_kind == "cask":
                info = self.run(["info", "--json=v2", "--cask", node_name], capture_json=True)
                items = info.get("casks", [])
                details = items[0] if items else {}
                depends = details.get("depends_on", {}) or {}
                formulae = depends.get("formula", []) if isinstance(depends, dict) else []
                casks = depends.get("cask", []) if isinstance(depends, dict) else []
                children = [build(d, "formula") for d in formulae]
                children.extend(build(d, "cask") for d in casks)
                return {"name": node_name, "type": "cask", "optional": optional, "deps": children}

            info = self.run(["info", "--json=v2", "--formula", node_name], capture_json=True)
            items = info.get("formulae", [])
            details = items[0] if items else {}
            req = []
            req.extend(details.get("dependencies", []) or [])
            req.extend(details.get("build_dependencies", []) or [])
            req.extend(details.get("test_dependencies", []) or [])
            req.extend(details.get("recommended_dependencies", []) or [])
            opt = details.get("optional_dependencies", []) or []
            children = [build(d, "formula") for d in req]
            children.extend(build(d, "formula", True) for d in opt)
            return {"name": node_name, "type": "formula", "optional": optional, "deps": children}

        return build(name, kind)

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
        result = self.run(["update"])  # textual output
        self.invalidate_caches()
        return result

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
        self.invalidate_caches()
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
        self.invalidate_caches()
        return logs

    def search(self, query: str) -> dict:
        """Search for formulae and casks using flexible token matching.

        Results are cached briefly to avoid repeated ``brew`` invocations
        while a user refines their query.

        Homebrew's ``brew search`` requires fairly exact strings and exits with
        a non-zero status when nothing is found.  To provide a better UX we:

        * Safely execute searches, treating "not found" as an empty result
        * Split the query into tokens and ensure all tokens appear in the
          results, enabling searches like "tencent lemon"
        * Fall back to a hyphen-joined version of the query
        """

        cache_key = query.strip().lower()
        cached = self._search_cache.get(cache_key)
        if cached and self._cache_valid(cached[0]):
            return cached[1]

        def parse_list(text: str) -> list:
            items = []
            for line in text.splitlines():
                name = line.strip()
                if name and not name.startswith("==>"):
                    items.append(name)
            return items

        def safe_search(kind: str, term: str) -> list:
            try:
                return parse_list(self.run(["search", f"--{kind}", term]))
            except BrewError:
                # brew search returns a non-zero exit code when no matches are
                # found; treat this as an empty result instead of an error
                return []

        tokens = [t for t in query.split() if t]

        # Initial search with the raw query
        formulae = safe_search("formula", query)
        casks = safe_search("cask", query)

        # If the query contains multiple tokens, ensure results contain all
        # tokens (order independent)
        if len(tokens) > 1:
            f_sets = [set(safe_search("formula", t)) for t in tokens]
            c_sets = [set(safe_search("cask", t)) for t in tokens]
            if f_sets:
                formulae = sorted(set(formulae) | set.intersection(*f_sets))
            if c_sets:
                casks = sorted(set(casks) | set.intersection(*c_sets))

        # If still nothing and tokens exist, try hyphen-joined query
        if not formulae and not casks and len(tokens) > 1:
            hyphen_query = "-".join(tokens)
            formulae = safe_search("formula", hyphen_query)
            casks = safe_search("cask", hyphen_query)
        
        # Enhance with descriptions (limit to first 20 results for performance)
        def bulk_info(names: List[str], kind: str) -> Dict[str, str]:
            if not names:
                return {}
            try:
                data = self.run(["info", "--json=v2", f"--{kind}", *names], capture_json=True)
                key = "formulae" if kind == "formula" else "casks"
                desc_map = {}
                for item in data.get(key, []):
                    name_key = item.get("name") if kind == "formula" else item.get("token") or item.get("name")
                    desc_map[name_key] = item.get("desc", "")
                return desc_map
            except BrewError:
                return {n: "" for n in names}

        f_names = formulae[:20]
        c_names = casks[:20]
        f_desc = bulk_info(f_names, "formula")
        c_desc = bulk_info(c_names, "cask")
        enhanced_formulae = [{"name": n, "desc": f_desc.get(n, "")} for n in f_names]
        enhanced_casks = [{"name": n, "desc": c_desc.get(n, "")} for n in c_names]

        result = {"formulae": enhanced_formulae, "casks": enhanced_casks}
        self._search_cache[cache_key] = (time.time(), result)
        return result

    def install(self, name: str, kind: str) -> str:
        if kind == "cask":
            result = self.run(["install", "--cask", name])
        else:
            result = self.run(["install", name])
        self.invalidate_caches()
        return result

    def uninstall(self, name: str, kind: str) -> str:
        if kind == "cask":
            result = self.run(["uninstall", "--cask", name])
        else:
            result = self.run(["uninstall", name])
        self.invalidate_caches()
        return result

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
        logger.info("GET %s", self.path)
        if self.path.startswith("/api/"):
            self._handle_api_get()
        else:
            super().do_GET()

    def do_POST(self):
        logger.info("POST %s", self.path)
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
            if path == "/api/dependencies":
                name = (qs.get("name", [""])[0] or "").strip()
                kind = (qs.get("type", ["formula"])[0] or "formula").strip()
                if not name:
                    self._send_json({}, 400)
                    return
                self._send_json(brew.dependency_tree(name, kind))
                return
            self.send_error(404, "Unknown API endpoint")
        except BrewError as e:
            logger.error("API GET %s failed: %s", path, e)
            error_response = {
                "ok": False,
                "error": str(e),
                "needs_sudo": getattr(e, 'needs_sudo', False),
                "permission_issue": getattr(e, 'permission_issue', False)
            }
            self._send_json(error_response, 500)
        except Exception as e:
            logger.exception("Unexpected error handling GET %s", path)
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
            logger.error("API POST %s failed: %s", path, e)
            error_response = {
                "ok": False,
                "error": str(e),
                "needs_sudo": getattr(e, 'needs_sudo', False),
                "permission_issue": getattr(e, 'permission_issue', False)
            }
            self._send_json(error_response, 500)
        except Exception as e:
            logger.exception("Unexpected error handling POST %s", path)
            self._send_json({"ok": False, "error": f"Unexpected error: {e}"}, 500)


def run(server_class=HTTPServer, handler_class=Handler, port: int = 8765):
    os.chdir(PROJECT_ROOT)
    logger.info("Starting server on port %s", port)
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
        logger.info("Server on port %s stopped", port)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    run(port=port)
