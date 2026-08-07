# MarketPulse free cloud EOD (GitHub Actions + Telegram)

This is the **$0-first** path: your PC can be off; GitHub runs download → database update → Telegram at **8:00 PM IST**.

The interactive web UI still runs locally (or later on a host). This workflow does **not** host the website yet.

## What runs automatically

| Time | What |
|------|------|
| **20:00 IST** daily (`cron: 30 14 * * *` UTC) | EOD job |
| Manual | Actions → **MarketPulse EOD** → **Run workflow** |

Steps:

1. Checkout this repo  
2. Restore previous DuckDB from Actions cache (if any)  
3. `python Scripts/daily_pipeline.py`  
   - download latest NSE session  
   - append (or full build if no DB)  
   - Telegram BUY TV lists (10 sessions)  
4. Upload logs + DuckDB artifact (14 days)  
5. Commit new `Input/` files back to `main`  

## One-time setup (required)

### 1. Secrets

GitHub → your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Name | Value |
|------|--------|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_CHAT_ID` | Your private chat id (from `telegram_deals.py --setup`) |

Do **not** commit `.env` with the token.

### 2. Enable Actions

If Actions are disabled: **Settings** → **Actions** → **Allow**.

Scheduled workflows only run on the **default branch** (`main`).

### 3. First run (manual)

1. **Actions** → **MarketPulse EOD** → **Run workflow**  
2. Wait (first run can take a long time if it full-builds the DB from Input)  
3. Check Telegram for BUY lists  
4. Check **Artifacts** for `marketpulse-duckdb` and logs  

### 4. Allow the bot to push Input

Default `GITHUB_TOKEN` can push to `main` if branch protection is off.  
If you protect `main`, allow the Actions bot to push or use a PAT secret.

## Local PC after this

| Still optional on PC | Cloud |
|----------------------|--------|
| `Launch_MarketPulse.bat` (open UI) | 8 PM pipeline + Telegram |
| Developing code | Code lives in Git |

To use the cloud-built DB on your PC: download the **marketpulse-duckdb** artifact from the latest successful run and place it at `Database/marketpulse.duckdb`.

## If NSE download fails on GitHub

GitHub runners are often blocked by NSE. Then:

1. You still get a **failure Telegram** (if secrets are set)  
2. Run pipeline on a small VPS later, **or** keep one local/manual run  
3. UI host (Fly etc.) is a separate later step  

## Cost

| Item | Typical |
|------|---------|
| Actions minutes | Free tier on personal accounts for light nightly use |
| Telegram | Free |
| Always-on web UI | **Not included** in this setup (add later if you want) |

## Security

- Never put `TELEGRAM_BOT_TOKEN` in the repo  
- Rotate the token if it was ever pasted in chat  
- Prefer a private repo if Input history is sensitive  

## Related

- Pipeline: `Scripts/daily_pipeline.py`  
- Telegram: `Scripts/telegram_deals.py`  
- Local schedule (optional): `Install_MarketPulse_Schedule.bat`  
