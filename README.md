# AntiGravity Bot - Auto Add Account

Automated bot for adding Antigravity accounts to a Mikrotik router (9Router).
Built with **Python + DrissionPage** for anti-detection and high stability.

---

## Requirements

- Python 3.8+
- Google Chrome / Chromium
- DrissionPage (auto-install)
- Internet connection
- 9Router running at `http://localhost:20128/` also disable require login 
---

## Features

- **Anti-detection** - DrissionPage doesn't use WebDriver, making it harder to detect
- **Text-based selector** - Finds elements based on text, not long CSS selectors
- **Auto-installer** - Automatically installs DrissionPage if not already present
- **Error handling** - If one account fails, continues to the next account
- **Headless mode** - Can run in the background without showing the browser
- **Cross-platform** - Runs on Windows, Linux, and Mac

---

## Installation

### Quick Method (Automatic)

**Linux / Mac:**
```bash
chmod +x setup.sh
./setup.sh
```

**Windows:**
```cmd
setup.bat
```

### Manual Method

1. **Make sure Python 3.8+ is installed:**
   ```bash
   python3 --version
   ```

2. **Install DrissionPage:**
   ```bash
   pip install DrissionPage
   ```
   > Or just skip this — the script will auto-install it the first time it runs.

3. **Make sure Google Chrome is installed** on your computer.

---

## Usage

### 1. Prepare the Accounts File

Create an `akun.txt` file in the same folder as `bot.py`:

```
user1@gmail.com|password123
user2@gmail.com|password456
user3@gmail.com|password789
```

> Format: `email|password` (separated by a `|`)
> One line = one account

### 2. Run the Bot

**Normal Mode (with browser visible — RECOMMENDED):**
```bash
python3 bot.py
```

**Custom delay between accounts (e.g., 5 seconds):**
```bash
python3 bot.py --delay 5
```

**Custom accounts file:**
```bash
python3 bot.py --file /path/to/other-accounts.txt
```

**Combined:**
```bash
python3 bot.py --delay 5 --file akun2.txt
```

> **Headless Mode (`--headless`):**
> The headless feature (running in the background without the browser showing) is **currently under repair**.
> There's currently a bug where headless Chrome sometimes fails to connect to the WebSocket,
> especially if there's a leftover Chrome process still running.
> **Use normal mode (without `--headless`) for the most stable results.**
> If you want to try headless anyway, make sure to kill all Chrome processes first:
> ```bash
> pkill -f chromium  # Linux
> taskkill /F /IM chrome.exe  # Windows
> ```

### 3. Bot Flow

The bot will automatically:

1. Open the Chrome browser
2. Navigate to `http://localhost:20128/`
3. Click the **Provider** menu
4. Click **Antigravity**
5. Click the **Add** / **Add Connection** button
6. Click **I Understand** / **Continue** (confirmation modal)
7. Wait for a new tab to open (Google Login)
8. Enter the **email** and click **Next**
9. Enter the **password** and click **Next**
10. Handle Google confirmations (I Understand, Allow, etc.)
11. If successful, remove the account from `akun.txt`
12. Close the browser, delay, then move to the next account

---

## Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--headless` | `False` | Run the browser in the background **(still buggy, see note above)** |
| `--delay` | `3` | Delay between accounts (seconds) |
| `--file` | `akun.txt` | Path to the accounts file |
| `--help` | - | Show help |

---

## Troubleshooting

### 1. "DrissionPage not installed"
The script will auto-install it. If that fails, install it manually:
```bash
pip install DrissionPage
```

### 2. "akun.txt file not found"
Create an `akun.txt` file in the same folder as `bot.py` with the format:
```
email@gmail.com|password
```

### 3. "Cannot find the Provider menu"
- Make sure the 9Router router is running at `http://localhost:20128/`
- Try opening that URL in a regular browser first
- Make sure the page has fully loaded

### 4. "Google Login tab doesn't appear"
- Make sure popups/new tabs aren't blocked
- Try running without `--headless` to see what's happening

### 5. Google asks for a CAPTCHA
- Don't run too many accounts at once
- Increase the delay: `--delay 10`
- Run without headless: the bot is less likely to trigger a CAPTCHA when the UI is visible
- Make sure the accounts don't have 2FA (Two-Factor Authentication) enabled

### 6. Chrome browser not found
- Install Google Chrome
- Or install Chromium:
  - Ubuntu/Debian: `sudo apt install chromium`
  - Mac: `brew install --cask chromium`
  - Windows: Download from [google.com/chrome](https://www.google.com/chrome/)

### 7. Persistent "timeout" errors
- Might be a slow internet connection — try increasing the delay
- The router UI may have changed — check if the menu text is still the same
- Try running it manually to debug:
  ```python
  from DrissionPage import ChromiumPage
  page = ChromiumPage()
  page.get('http://localhost:20128/')
  # Manually inspect the elements present
  ```

---

## File Structure

```
project-folder/
  bot.py          # Main script
  akun.txt        # Account list (email|password) -- DO NOT COMMIT
  README.md       # Documentation (this file)
  .gitignore      # Ignore sensitive files
  setup.sh        # Setup script for Linux/Mac
  setup.bat       # Setup script for Windows
```

---

## Security Notes

- **DO NOT** commit `akun.txt` to git (already ignored in `.gitignore`)
- **DO NOT** share the `akun.txt` file with anyone else
- Use a strong password for each account
- Make sure your internet connection is secure while running the bot

---

## Requirements

- Python 3.8+
- Google Chrome / Chromium
- DrissionPage (auto-install)
- Internet connection
- 9Router running at `http://localhost:20128/`

---