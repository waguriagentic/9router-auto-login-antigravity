#!/usr/bin/env python3
"""
Antigravity Auto-Add Account (Hybrid Mode — CloakBrowser CDP)

Browser = CloakBrowser Docker via raw CDP for Google OAuth only.
Token exchange, loadCodeAssist, onboardUser, DB inject = pure HTTP.

Usage:
  python3 bot.py                    # visible browser
  python3 bot.py --delay 5          # delay between accounts
  python3 bot.py --file akun.txt    # custom accounts file
"""

import os, sys, json, uuid, random, shutil, time, argparse, sqlite3
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode
from datetime import datetime, timezone

SCRIPT_DIR = Path(__file__).parent
AKUN_FILE = SCRIPT_DIR / "akun.txt"
DB_PATH = Path.home() / ".9router" / "db" / "data.sqlite"
PROFILE_ID = "9febcfa9-40d4-4c8c-a515-4d9b22238d6e"
CDP_BASE = f"http://127.0.0.1:8080/api/profiles/{PROFILE_ID}"

# ── Load .env ───────────────────────────────────────────────
_env_path = SCRIPT_DIR / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

CLIENT_ID = os.environ.get("AG_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("AG_CLIENT_SECRET", "")
if not CLIENT_ID or not CLIENT_SECRET:
    print("[!] AG_CLIENT_ID / AG_CLIENT_SECRET not set. Copy .env.example to .env")
    sys.exit(1)

# ── Antigravity OAuth constants ─────────────────────────────
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo"
LOAD_CODE_ASSIST_URL = "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist"
ONBOARD_USER_URL = "https://cloudcode-pa.googleapis.com/v1internal:onboardUser"
SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs",
]
CLIENT_METADATA = {"ideType": 9, "platform": 3, "pluginType": 2}
LOAD_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "google-api-nodejs-client/9.15.1",
    "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
    "Client-Metadata": json.dumps(CLIENT_METADATA),
    "x-request-source": "local",
}


# ── CDP helper ──────────────────────────────────────────────
class CDPPage:
    """Minimal CDP client over websocket."""

    def __init__(self, ws_url):
        import websocket
        self.ws = websocket.create_connection(ws_url, timeout=30)
        self._id = 0

    def send(self, method, params=None):
        self._id += 1
        msg = {"id": self._id, "method": method}
        if params:
            msg["params"] = params
        self.ws.send(json.dumps(msg))
        # Read until we get our response
        while True:
            r = json.loads(self.ws.recv())
            if r.get("id") == self._id:
                return r

    def navigate(self, url):
        return self.send("Page.navigate", {"url": url})

    def eval(self, expression):
        r = self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        return r.get("result", {}).get("result", {}).get("value")

    def type_text(self, text):
        """Type text using CDP Input.dispatchKeyEvent (bypasses JS value= issue)."""
        for ch in text:
            self.send("Input.dispatchKeyEvent", {"type": "keyDown", "text": ch, "key": ch})
            self.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": ch})
            time.sleep(0.02)

    def click_at(self, x, y):
        """Click at coordinates using CDP Input.dispatchMouseEvent (bypasses JS .click() issues)."""
        self.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
        self.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})

    def close(self):
        self.ws.close()


def get_page_ws():
    """Get a page websocket URL from CloakBrowser Docker."""
    import urllib.request
    # Get targets
    req = urllib.request.Request(f"{CDP_BASE}/cdp/json")
    with urllib.request.urlopen(req, timeout=10) as resp:
        targets = json.loads(resp.read())
    # Find about:blank page or use first page
    for t in targets:
        if t.get("type") == "page" and t.get("url") == "about:blank":
            return t["webSocketDebuggerUrl"]
    # Create new page
    for t in targets:
        if t.get("type") == "page":
            return t["webSocketDebuggerUrl"]
    raise Exception("No page target found")


def ensure_cloakbrowser_running():
    """Ensure CloakBrowser profile is running."""
    import urllib.request
    try:
        req = urllib.request.Request(f"{CDP_BASE}/status")
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = json.loads(resp.read())
        if status.get("status") == "running":
            return True
    except Exception:
        pass
    # Try to launch
    import urllib.request
    try:
        req = urllib.request.Request(f"{CDP_BASE}/launch", method="POST",
                                     data=b"{}",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return True
    except Exception as e:
        raise Exception(f"Failed to launch CloakBrowser: {e}")


# ── HTTP helpers ────────────────────────────────────────────
def exchange_code(code, redirect_uri):
    import urllib.request, urllib.parse
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "redirect_uri": redirect_uri,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def get_user_info(access_token):
    import urllib.request
    req = urllib.request.Request(f"{USERINFO_URL}?alt=json", headers={
        "Authorization": f"Bearer {access_token}",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def load_code_assist(access_token):
    import urllib.request
    headers = {**LOAD_HEADERS, "Authorization": f"Bearer {access_token}"}
    data = json.dumps({"metadata": CLIENT_METADATA}).encode()
    req = urllib.request.Request(LOAD_CODE_ASSIST_URL, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    project_id = ""
    raw = result.get("cloudaicompanionProject")
    if isinstance(raw, dict):
        project_id = raw.get("id", "")
    elif isinstance(raw, str):
        project_id = raw
    tier_id = "legacy-tier"
    for tier in result.get("allowedTiers", []):
        if tier.get("isDefault") and tier.get("id"):
            tier_id = tier["id"].strip()
            break
    return project_id, tier_id


def onboard_user(access_token, project_id, tier_id, max_retries=10):
    """Onboard user with projectId in request body (required by Google API)."""
    import urllib.request
    headers = {**LOAD_HEADERS, "Authorization": f"Bearer {access_token}"}
    # ✅ projectId MUST be included in the request body
    data = json.dumps({
        "tierId": tier_id, 
        "metadata": CLIENT_METADATA,
        "projectId": project_id  # This is required!
    }).encode()
    
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(ONBOARD_USER_URL, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            if result.get("done"):
                resp_proj = result.get("response", {}).get("cloudaicompanionProject", "")
                if isinstance(resp_proj, str):
                    return resp_proj.strip()
                elif isinstance(resp_proj, dict):
                    return resp_proj.get("id", "")
                # If no project in response, return the original projectId
                return project_id
        except Exception as e:
            print(f"    [WARN] onboard attempt {attempt+1}: {e}")
        time.sleep(5)
    return ""


def inject_to_9router(email, access_token, refresh_token, project_id, db_path):
    conn_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(100,999)}Z"
    data = json.dumps({
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "projectId": project_id,
        "testStatus": "active",
        "lastRefreshAt": now,
    })
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO providerConnections(id, provider, authType, name, email, priority, isActive, data, createdAt, updatedAt) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (conn_id, "antigravity", "oauth", email, email, 20, 1, data, now, now)
        )
        conn.commit()
        return conn_id
    finally:
        conn.close()


# ── Account helpers ─────────────────────────────────────────
def read_accounts(path):
    if not path.exists():
        return []
    accounts = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if "|" not in line:
            continue
        parts = line.split("|", 1)
        if parts[0].strip() and parts[1].strip():
            accounts.append({"email": parts[0].strip(), "password": parts[1].strip(), "raw": line})
    return accounts


def remove_account(path, raw_line):
    if not path.exists():
        return
    lines = [l for l in path.read_text().splitlines() if l.strip() != raw_line]
    path.write_text("\n".join(lines) + "\n")


# ── Browser flow (CloakBrowser CDP) ────────────────────────
def google_oauth_flow(email, password):
    """Run Google OAuth via CloakBrowser CDP, return auth_code."""
    redirect_uri = "http://localhost:8080/callback"
    state = uuid.uuid4().hex
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(SCOPES),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = f"{AUTHORIZE_URL}?{urlencode(params)}"

    print(f"    Connecting to CloakBrowser CDP...")
    page_ws = get_page_ws()
    page = CDPPage(page_ws)

    try:
        # Enable Page events
        page.send("Page.enable")

        # Clear Google cookies to avoid account chooser
        page.send("Network.enable")
        page.send("Network.clearBrowserCookies")

        # Navigate to Google OAuth
        print(f"    Navigating to Google OAuth...")
        page.navigate(auth_url)
        time.sleep(5)

        # Check current URL
        url = page.eval("document.location.href")
        print(f"    URL: {(url or '')[:120]}")

        # Email field should be visible (cookies cleared → no account chooser)
        has_email_field = page.eval("!!document.querySelector('#identifierId')")

        if has_email_field:
            # Input email via CDP keyboard (JS value= doesn't trigger Google's handlers)
            print(f"    Inputting email: {email}")
            page.eval("document.querySelector('#identifierId')?.focus()")
            time.sleep(0.3)
            page.type_text(email)
            time.sleep(0.5)

            # Click Next
            page.eval("document.querySelector('#identifierNext button, #identifierNext')?.click()")
            time.sleep(5)

        # Check for password field
        has_password = page.eval("!!document.querySelector('input[type=password], input[name=Passwd]')")
        if not has_password:
            # Maybe error or different page
            url = page.eval("document.location.href")
            title = page.eval("document.title")
            print(f"    [DEBUG] URL: {(url or '')[:150]}")
            print(f"    [DEBUG] Title: {title}")

            # Check for error
            error_text = page.eval("""
                Array.from(document.querySelectorAll('[class*=error], [class*=LgSUxe], [jsname=B34EJ]'))
                    .map(e => e.textContent.trim())
                    .filter(t => t.length > 0)
                    .join(' | ')
            """)
            if error_text:
                print(f"    [DEBUG] Error: {error_text[:150]}")
            raise Exception("Password field not found after email step")

        # Input password via CDP keyboard
        print(f"    Inputting password...")
        page.eval("document.querySelector('input[type=password], input[name=Passwd]')?.focus()")
        time.sleep(0.3)
        page.type_text(password)
        time.sleep(0.5)

        # Click Next (password)
        page.eval("document.querySelector('#passwordNext button, #passwordNext')?.click()")
        time.sleep(6)

        # Handle consent screens
        print(f"    Handling Google consent...")
        # Try I Understand / consent
        page.eval("""
            (() => {
                const btns = document.querySelectorAll('button');
                for (const b of btns) {
                    const txt = b.textContent.trim().toLowerCase();
                    if (txt.includes('i understand') || txt.includes('i agree') || 
                        txt.includes('saya memahami') || txt.includes('gaplustos')) {
                        b.click();
                        return 'clicked_consent';
                    }
                }
                return 'no_consent';
            })()
        """)
        time.sleep(3)

        # Click Allow/Login (critical — GSuite shows "Login", regular shows "Allow")
        # Must use CDP mouse click because Google consent page ignores JS .click()
        print(f"    Clicking Allow/Login...")
        time.sleep(2)  # Wait for consent page to fully render
        allow_pos = page.eval("""
            (() => {
                const btns = document.querySelectorAll('button, input[type=submit]');
                for (const b of btns) {
                    const txt = (b.textContent || b.value || '').trim().toLowerCase();
                    if (txt === 'login' || txt === 'allow' || txt === 'izinkan' || 
                        txt === 'masuk' || txt.includes('submit_approve')) {
                        const rect = b.getBoundingClientRect();
                        return JSON.stringify({x: rect.x + rect.width/2, y: rect.y + rect.height/2});
                    }
                }
                const el = document.querySelector('#submit_approve_access');
                if (el) {
                    const rect = el.getBoundingClientRect();
                    return JSON.stringify({x: rect.x + rect.width/2, y: rect.y + rect.height/2});
                }
                return null;
            })()
        """)

        if allow_pos:
            coords = json.loads(allow_pos)
            page.click_at(coords["x"], coords["y"])
            allow_result = f"cdp_click_at({coords['x']:.0f},{coords['y']:.0f})"
        else:
            allow_result = "no_allow"
        print(f"    Allow result: {allow_result}")

        if allow_result == "no_allow":
            # Debug
            url = page.eval("document.location.href")
            title = page.eval("document.title")
            print(f"    [DEBUG] URL: {(url or '')[:150]}")
            print(f"    [DEBUG] Title: {title}")
            btns = page.eval("""
                Array.from(document.querySelectorAll('button')).map(b => 
                    b.textContent.trim().substring(0, 60) + ' | id=' + b.id
                ).join('\\n')
            """)
            print(f"    [DEBUG] Buttons:\n    {(btns or 'none')[:300]}")
            raise Exception("Allow button not found — Google login FAILED")

        time.sleep(5)

        # Extract auth code from redirect URL
        print(f"    Extracting auth code...")
        for _ in range(30):
            url = page.eval("document.location.href") or ""
            if "code=" in url:
                qs = parse_qs(urlparse(url).query)
                code_list = qs.get("code", [])
                if code_list:
                    return code_list[0], redirect_uri
            if "error=" in url:
                qs = parse_qs(urlparse(url).query)
                error = qs.get("error", ["unknown"])[0]
                desc = qs.get("error_description", [""])[0]
                raise Exception(f"Google OAuth error: {error} — {desc}")
            time.sleep(1)

        raise Exception(f"Could not extract auth code. Final URL: {url[:200]}")

    finally:
        page.close()


# ── Process one account ─────────────────────────────────────
def process_account(account, index, total, db_path=DB_PATH):
    email = account["email"]
    password = account["password"]

    print(f"\n{'='*55}")
    print(f" Account {index+1}/{total}: {email}")
    print(f"{'='*55}")

    try:
        # Step 1: Browser — Google OAuth
        print(" [1/6] Google OAuth via CloakBrowser CDP...")
        auth_code, redirect_uri = google_oauth_flow(email, password)
        print(f"    Auth code: {auth_code[:20]}...")

        # Step 2: Exchange code → tokens
        print(" [2/6] Exchanging code for tokens...")
        tokens = exchange_code(auth_code, redirect_uri)
        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")
        if not access_token:
            raise Exception(f"No access_token: {tokens}")
        print(f"    access_token: {access_token[:30]}...")
        if refresh_token:
            print(f"    refresh_token: {refresh_token[:20]}...")

        # Step 3: User info
        print(" [3/6] Getting user info...")
        user_info = get_user_info(access_token)
        actual_email = user_info.get("email", email)
        print(f"    Email: {actual_email}")

        # Step 4: loadCodeAssist
        print(" [4/6] Loading Code Assist...")
        project_id, tier_id = load_code_assist(access_token)
        print(f"    Project ID: {project_id or '(empty)'}")

        # Step 5: onboardUser
        if project_id:
            print(" [5/6] Onboarding user...")
            final_pid = onboard_user(access_token, project_id, tier_id)
            if final_pid:
                project_id = final_pid
            print(f"    Final Project ID: {project_id}")
        else:
            print(" [5/6] Skipping onboard (no projectId)")

        # Step 6: Inject into 9router DB
        print(" [6/6] Injecting into 9router DB...")
        conn_id = inject_to_9router(actual_email, access_token, refresh_token, project_id, db_path)
        print(f"    Connection ID: {conn_id[:8]}...")

        remove_account(AKUN_FILE, account["raw"])
        print(f"\n [SUCCESS] {actual_email} → 9router (id: {conn_id[:8]}...)")
        return True

    except Exception as e:
        print(f"\n [FAILED] {email}: {e}")
        return False


# ── Main ────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Antigravity Auto-Add (Hybrid — CloakBrowser CDP)")
    parser.add_argument("--delay", type=int, default=3, help="Delay between accounts (seconds)")
    parser.add_argument("--file", type=str, default=None, help="Accounts file path")
    parser.add_argument("--db", type=str, default=None, help="9router SQLite DB path")
    args = parser.parse_args()

    global AKUN_FILE, DB_PATH
    if args.file:
        AKUN_FILE = Path(args.file)
    if args.db:
        DB_PATH = Path(args.db)

    # Ensure CloakBrowser is running
    print("[*] Checking CloakBrowser...")
    ensure_cloakbrowser_running()
    print("[*] CloakBrowser running OK")

    accounts = read_accounts(AKUN_FILE)
    if not accounts:
        print("[!] No accounts. Create akun.txt: email|password")
        sys.exit(1)

    print(f"""
    AntiGravity Auto-Add (Hybrid — CloakBrowser CDP)
    ==================================================
    Accounts : {len(accounts)}
    Delay    : {args.delay}s
    DB       : {DB_PATH}
    """)

    success = fail = 0
    for i, account in enumerate(accounts):
        ok = process_account(account, i, len(accounts), db_path=DB_PATH)
        if ok:
            success += 1
        else:
            fail += 1
        if i < len(accounts) - 1:
            time.sleep(args.delay)

    print(f"\n{'='*55}")
    print(f" DONE — {success} success, {fail} failed, {len(accounts)} total")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
