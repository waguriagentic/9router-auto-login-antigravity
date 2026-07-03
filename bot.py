#!/usr/bin/env python3
"""
Antigravity Auto-Add Account (Hybrid Mode)

Browser = Google OAuth only (login + consent).
Token exchange, loadCodeAssist, onboardUser, DB inject = pure HTTP.

Usage:
  python3 bot.py                    # normal (visible browser)
  python3 bot.py --headless         # headless browser
  python3 bot.py --delay 5          # delay between accounts (seconds)
  python3 bot.py --file akun.txt    # custom accounts file
  python3 bot.py --db ~/.9router/db/data.sqlite  # custom 9router DB path
"""

import os, sys, subprocess, tempfile, shutil, random, time, argparse, json, sqlite3, uuid
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(SCRIPT_DIR, ".venv")
AKUN_FILE = os.path.join(SCRIPT_DIR, "akun.txt")
DB_PATH = os.path.expanduser("~/.9router/db/data.sqlite")
DELAY_ANTAR_AKUN = 3

# ── Auto-installer ──────────────────────────────────────────
def _ensure_drissionpage():
    try:
        import DrissionPage  # noqa: F401
        return
    except ImportError:
        pass

    print("[*] DrissionPage not installed, installing...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "DrissionPage"],
                              stdout=sys.stdout, stderr=sys.stderr)
        return
    except subprocess.CalledProcessError:
        pass

    print("[*] pip failed, creating venv...")
    subprocess.check_call([sys.executable, "-m", "venv", VENV_DIR],
                          stdout=sys.stdout, stderr=sys.stderr)
    venv_py = os.path.join(VENV_DIR, "Scripts" if sys.platform == "win32" else "bin", "python3")
    subprocess.check_call([venv_py, "-m", "pip", "install", "--upgrade", "pip"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.check_call([venv_py, "-m", "pip", "install", "DrissionPage"],
                          stdout=sys.stdout, stderr=sys.stderr)
    os.execv(venv_py, [venv_py] + sys.argv)

_ensure_drissionpage()

from DrissionPage import ChromiumPage, ChromiumOptions
from DrissionPage._units.actions import Keys

# ── Antigravity OAuth constants (from 9router source) ──────
CLIENT_ID = os.environ.get("AG_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("AG_CLIENT_SECRET", "")
if not CLIENT_ID or not CLIENT_SECRET:
    print("[!] AG_CLIENT_ID / AG_CLIENT_SECRET not set. Copy .env.example to .env and fill in values.")
    sys.exit(1)

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
# Linux x86_64
PLATFORM_ENUM = 3  # LINUX_AMD64
CLIENT_METADATA = json.dumps({"ideType": 9, "platform": PLATFORM_ENUM, "pluginType": 2})
USER_AGENT = "antigravity/1.107.0 linux/x86_64"
LOAD_HEADERS = {
    "Authorization": "",  # filled at runtime
    "Content-Type": "application/json",
    "User-Agent": "google-api-nodejs-client/9.15.1",
    "X-Goog-Api-Client": "google-cloud-sdk vscode_cloudshelleditor/0.1",
    "Client-Metadata": CLIENT_METADATA,
    "x-request-source": "local",
}


# ── HTTP helpers ────────────────────────────────────────────
def exchange_code(code, redirect_uri):
    """Exchange authorization code for access_token + refresh_token."""
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
    """Get email from Google userinfo API."""
    import urllib.request
    req = urllib.request.Request(f"{USERINFO_URL}?alt=json", headers={
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def load_code_assist(access_token):
    """Fetch projectId + tierId from loadCodeAssist."""
    import urllib.request
    headers = {**LOAD_HEADERS, "Authorization": f"Bearer {access_token}"}
    data = json.dumps({"metadata": json.loads(CLIENT_METADATA)}).encode()
    req = urllib.request.Request(LOAD_CODE_ASSIST_URL, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    project_id = ""
    raw_proj = result.get("cloudaicompanionProject")
    if isinstance(raw_proj, dict):
        project_id = raw_proj.get("id", "")
    elif isinstance(raw_proj, str):
        project_id = raw_proj

    tier_id = "legacy-tier"
    for tier in result.get("allowedTiers", []):
        if tier.get("isDefault") and tier.get("id"):
            tier_id = tier["id"].strip()
            break

    return project_id, tier_id


def onboard_user(access_token, tier_id, max_retries=10):
    """Onboard user (activate service). Polls until done."""
    import urllib.request
    headers = {**LOAD_HEADERS, "Authorization": f"Bearer {access_token}"}
    metadata = json.loads(CLIENT_METADATA)
    data = json.dumps({"tierId": tier_id, "metadata": metadata}).encode()

    for attempt in range(max_retries):
        req = urllib.request.Request(ONBOARD_USER_URL, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
            if result.get("done"):
                # Extract final projectId
                resp_proj = result.get("response", {}).get("cloudaicompanionProject", "")
                if isinstance(resp_proj, str):
                    return resp_proj.strip()
                elif isinstance(resp_proj, dict):
                    return resp_proj.get("id", "")
                return ""
        except Exception as e:
            print(f"    [WARN] onboard attempt {attempt+1}: {e}")
        time.sleep(5)
    return ""


def inject_to_9router(email, access_token, refresh_token, project_id, db_path):
    """Insert antigravity connection directly into 9router SQLite."""
    conn_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{random.randint(100,999)}Z"
    data = json.dumps({
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "projectId": project_id,
        "testStatus": "active",
        "lastRefreshAt": now,
    })
    conn = sqlite3.connect(db_path)
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


# ── Browser helpers ─────────────────────────────────────────
def find_and_click(page_or_tab, locators, timeout=5, desc="element"):
    for locator in locators:
        try:
            ele = page_or_tab.ele(locator, timeout=timeout)
            if ele:
                ele.click()
                return True
        except Exception:
            continue
    return False


def force_input(page_or_tab, locator, text, timeout=15, desc="field"):
    ele = page_or_tab.ele(locator, timeout=timeout)
    if ele is None:
        raise Exception(f"Element {desc} not found: {locator}")

    # Strategy 1: standard .input()
    try:
        ele.input(text, clear=True)
        time.sleep(0.5)
        val = ele.attr("value") or ele.property("value") or ""
        if text in val:
            return ele
    except Exception:
        pass

    # Strategy 2: .input(by_js=True)
    try:
        ele.input(text, clear=True, by_js=True)
        time.sleep(0.5)
        val = ele.attr("value") or ele.property("value") or ""
        if text in val:
            return ele
    except Exception:
        pass

    # Strategy 3: CDP keyboard
    try:
        ele.click()
        time.sleep(0.3)
        page_or_tab.actions.key_down(Keys.CTRL).type("a").key_up(Keys.CTRL)
        time.sleep(0.2)
        page_or_tab.actions.type(Keys.BACKSPACE)
        time.sleep(0.3)
        page_or_tab.actions.input(text)
        time.sleep(0.5)
        val = ele.attr("value") or ele.property("value") or ""
        if text in val:
            return ele
    except Exception:
        pass

    # Strategy 4: JS direct
    try:
        ele.click()
        time.sleep(0.3)
        ele.run_js("""
            this.focus();
            this.value = arguments[0];
            this.dispatchEvent(new Event('input', {bubbles: true}));
            this.dispatchEvent(new Event('change', {bubbles: true}));
        """, text)
        time.sleep(0.5)
        return ele
    except Exception:
        pass

    raise Exception(f"Failed to input text to {desc} with all strategies")


def read_accounts(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    accounts = []
    for line in lines:
        if "|" not in line:
            continue
        parts = line.split("|", 1)
        email, password = parts[0].strip(), parts[1].strip()
        if email and password:
            accounts.append({"email": email, "password": password, "raw": line})
    return accounts


def remove_account(path, raw_line):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    remaining = [line for line in lines if line.strip() != raw_line]
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(remaining)


# ── Main flow ───────────────────────────────────────────────
def process_account(account, index, total, headless=False, db_path=DB_PATH):
    email = account["email"]
    password = account["password"]
    redirect_uri = "http://localhost:8080/callback"

    print(f"\n{'='*55}")
    print(f" Account {index+1}/{total}: {email}")
    print(f"{'='*55}")

    # Build auth URL
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
    from urllib.parse import urlencode
    auth_url = f"{AUTHORIZE_URL}?{urlencode(params)}"

    # ── Step 1: Browser — Google OAuth only ──
    print(" [1/6] Starting browser for Google OAuth...")
    tmp_user_data = tempfile.mkdtemp(prefix="antigravity_")
    co = ChromiumOptions()
    co.set_argument("--start-maximized")
    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_argument("--no-first-run")
    co.set_argument("--no-default-browser-check")
    co.set_user_data_path(tmp_user_data)
    co.set_local_port(random.randint(19200, 29200))
    if headless:
        co.headless(True)

    page = ChromiumPage(co)
    auth_code = None

    try:
        # Navigate directly to Google OAuth (skip 9router UI entirely)
        print(f" [2/6] Navigating to Google OAuth...")
        page.get(auth_url)
        time.sleep(3)

        # Input email
        print(f" [3/6] Logging in: {email}")
        force_input(page, "#identifierId", email, timeout=15, desc="email")
        time.sleep(1)

        if not find_and_click(page, ["#identifierNext", "tag:button@@text():Next"], timeout=5, desc="Next(email)"):
            raise Exception("Next button (email) not found")
        time.sleep(3)

        # Input password
        pw_done = False
        for loc in ["@type=password", "tag:input@@type=password", "@name=Passwd"]:
            try:
                force_input(page, loc, password, timeout=10, desc="password")
                pw_done = True
                break
            except Exception:
                continue
        if not pw_done:
            raise Exception("Password field not found")
        time.sleep(1)

        if not find_and_click(page, ["#passwordNext", "tag:button@@text():Next"], timeout=5, desc="Next(pw)"):
            raise Exception("Next button (password) not found")
        time.sleep(3)

        # Handle Google consent screens
        print(" [4/6] Handling Google consent...")
        find_and_click(page, [
            "#gaplustosNext",
            "tag:button@@text():I Understand",
            "tag:button@@text():I agree",
        ], timeout=15, desc="I Understand")
        time.sleep(2)

        if not find_and_click(page, [
            "#submit_approve_access",
            "tag:button@@text():Allow",
            "tag:button@@text():Continue",
        ], timeout=15, desc="Allow"):
            raise Exception("Allow button not found — Google login FAILED")
        time.sleep(3)

        # Intercept redirect URL to extract auth code
        print(" [5/6] Extracting auth code from redirect...")
        # Wait for redirect to localhost:8080/callback
        for _ in range(30):
            current_url = page.url
            if "localhost" in current_url and "code=" in current_url:
                parsed = urlparse(current_url)
                qs = parse_qs(parsed.query)
                code_list = qs.get("code", [])
                if code_list:
                    auth_code = code_list[0]
                    break
            # Check if there's an error
            if "error=" in current_url:
                parsed = urlparse(current_url)
                qs = parse_qs(parsed.query)
                error = qs.get("error", ["unknown"])[0]
                desc = qs.get("error_description", [""])[0]
                raise Exception(f"Google OAuth error: {error} — {desc}")
            time.sleep(1)

        if not auth_code:
            # Fallback: try to get code from page content or URL fragments
            current_url = page.url
            print(f"    [DEBUG] Final URL: {current_url[:120]}")
            raise Exception("Could not extract auth code from redirect URL")

        print(f"    Auth code: {auth_code[:20]}...")

    finally:
        try:
            page.quit()
        except Exception:
            pass
        try:
            shutil.rmtree(tmp_user_data, ignore_errors=True)
        except Exception:
            pass

    # ── Step 2-5: Pure HTTP ──
    try:
        # Exchange code for tokens
        print(" [6/6] Exchanging code for tokens...")
        tokens = exchange_code(auth_code, redirect_uri)
        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")
        if not access_token:
            raise Exception(f"No access_token in response: {tokens}")
        print(f"    access_token: {access_token[:30]}...")
        print(f"    refresh_token: {refresh_token[:20]}..." if refresh_token else "    [WARN] No refresh_token")

        # Get user info
        print("    Fetching user info...")
        user_info = get_user_info(access_token)
        actual_email = user_info.get("email", email)
        print(f"    Email: {actual_email}")

        # Load Code Assist → projectId
        print("    Loading Code Assist...")
        project_id, tier_id = load_code_assist(access_token)
        if not project_id:
            print("    [WARN] No projectId found, using empty string")
        else:
            print(f"    Project ID: {project_id}")

        # Onboard user
        if project_id:
            print("    Onboarding user...")
            final_project_id = onboard_user(access_token, tier_id)
            if final_project_id:
                project_id = final_project_id
                print(f"    Final Project ID: {project_id}")

        # Inject into 9router DB
        print("    Injecting into 9router DB...")
        conn_id = inject_to_9router(actual_email, access_token, refresh_token, project_id, db_path)
        print(f"    Connection ID: {conn_id}")

        # Remove from accounts file
        remove_account(AKUN_FILE, account["raw"])
        print(f"\n [SUCCESS] {actual_email} → injected into 9router (id: {conn_id[:8]}...)")
        return True

    except Exception as e:
        print(f"\n [FAILED] {email}: {e}")
        return False


# ── Main ────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Antigravity Auto-Add (Hybrid Mode)")
    parser.add_argument("--headless", action="store_true", help="Run browser headless")
    parser.add_argument("--delay", type=int, default=DELAY_ANTAR_AKUN, help="Delay between accounts (seconds)")
    parser.add_argument("--file", type=str, default=None, help="Path to accounts file")
    parser.add_argument("--db", type=str, default=DB_PATH, help="Path to 9router SQLite DB")
    args = parser.parse_args()

    global AKUN_FILE
    if args.file:
        AKUN_FILE = args.file

    # Cleanup zombie Chrome processes
    try:
        if sys.platform != "win32":
            os.system("pkill -f 'chromium.*antigravity_' 2>/dev/null")
            os.system("pkill -f 'chrome.*antigravity_' 2>/dev/null")
        import glob
        for old in glob.glob(os.path.join(tempfile.gettempdir(), "antigravity_*")):
            shutil.rmtree(old, ignore_errors=True)
    except Exception:
        pass

    accounts = read_accounts(AKUN_FILE)
    if not accounts:
        print("[!] No accounts found. Create akun.txt with format: email|password")
        sys.exit(1)

    print(f"""
    AntiGravity Auto-Add (Hybrid Mode)
    ===================================
    Accounts : {len(accounts)}
    Headless : {'YES' if args.headless else 'NO'}
    Delay    : {args.delay}s
    DB       : {args.db}
    """)

    success = fail = 0
    for i, account in enumerate(accounts):
        ok = process_account(account, i, len(accounts), headless=args.headless, db_path=args.db)
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
