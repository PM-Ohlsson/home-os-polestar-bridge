# HOME OS — Polestar cloud bridge (read-only, v0.1)

This service fetches battery status from the unofficial Polestar Python library and exposes **only limited, read-only car data** to HOME OS. It does **not** issue car commands and it does not serve location or VIN. It is a starter to validate your car and hosting; compatibility is not guaranteed.

## Before you deploy

- HOME OS can remain on GitHub Pages, e.g. `https://pm-ohlsson.github.io/Home-OS/`.
- Do **not** enter your Polestar credentials in GitHub files, HTML, ChatGPT, or a public issue.
- This is an **unofficial API**. Whether the specific Polestar 2 works must be tested.
- The API polls on demand with a 10-minute cache to avoid unnecessary requests.
- The cloud service provider will hold your Polestar credentials as secrets. If you would rather not trust a cloud host with these credentials, wait until you have local Home Assistant hardware.

## Render deployment (Python, Free tier for initial testing)

1. Make a **new GitHub repository** (for example `home-os-polestar-bridge`). Upload the contents of this folder, not your HOME OS static HTML. The Python code is safe to keep public **because no credentials are in it**.
2. Go to https://dashboard.render.com/ and choose **New → Web Service**, connect that repository.
3. Runtime: **Python**. Use build command `pip install -r requirements.txt` and start command `uvicorn app:app --host 0.0.0.0 --port $PORT`.
4. Choose the **Free** instance for testing. In **Environment** add the following variables:

   | Name | Value |
   | --- | --- |
   | `POLESTAR_EMAIL` | Polestar ID email, entered only in Render environment |
   | `POLESTAR_PASSWORD` | Polestar password, entered only in Render environment |
   | `HOME_OS_API_KEY` | A NEW random password/token at least 24 characters long (not your Polestar password) |
   | `ALLOWED_ORIGIN` | `https://pm-ohlsson.github.io` (no trailing slash/path) |
   | `POLESTAR_VIN` | Optional. For multiple vehicles, select a specific VIN. Keep it as a secret if used. |

5. Deploy. Your bridge will receive a URL like `https://your-service.onrender.com`. Opening `https://your-service.onrender.com/health` should show `{"status":"ok",...}`. The actual car endpoint is **protected**, so browsing to `/api/vehicle` without a token will show `Unauthorized`.
6. **Do not share** the Render environment variables, access key, or car credentials. Share only the backend base URL (without key) when you want HOME OS connected.

When you're ready, we'll add a small **Connection** form in HOME OS Settings that accepts the Render URL and separate `HOME_OS_API_KEY` on your personal tablet; the key must never be hard-coded into the public GitHub Pages HTML. We can then replace the demo readings with live data, and later switch the data source to Home Assistant without redesigning the UI.

### Optional PowerShell test on your own PC

```powershell
$secret = Read-Host 'HOME OS API key'
Invoke-RestMethod -Uri 'https://YOUR-SERVICE.onrender.com/api/vehicle' -Headers @{Authorization = "Bearer $secret"}
```

Expected output has fields such as `soc_percent`, `range_km`, `charging_status`, `charging_power_kw` and `stale`.

The Render Free web service may sleep after 15 minutes without requests; the first request after that can take about a minute. For this reason it is suitable for a prototype, but not guaranteed always-on uptime.

### Optional local compatibility test

Python 3.12+, with dependencies installed using `pip install -r requirements.txt`. Run `python check_polestar.py`. The script prompts for credentials without storing them in a file and prints only battery data. Do not paste credentials or sensitive output into a public issue.

## Endpoint response example (illustrative only)

```json
{
  "soc_percent": 68,
  "range_km": 250,
  "charging_status": "charging",
  "plugged_in": true,
  "charging_power_kw": 7.4,
  "updated_at": "2026-10-19T18:00:00+00:00",
  "source": "polestar",
  "stale": false
}
```

The example is **not** a claim about your car's current status.

## Limitations

- This service depends on the third-party, reverse-engineered API `unofficial-polestar-api` (0.3.1). Future Polestar app changes may break it.
- The current service intentionally does **not** expose departure or climate timer control. We can add them only after verifying support on your specific car, and behind separate authorization and confirmation.
- The service returns cached data on API errors if a previous sample exists; the `stale` field then becomes `true`.
- A publicly served HTML page cannot safely contain permanent Polestar passwords or backend API keys. An independent secret must be entered on your device when we connect HOME OS.
