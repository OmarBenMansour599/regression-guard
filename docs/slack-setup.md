# Slack setup (about 10 minutes, no coding)

RegressionGuard can post a message to a Slack channel when a prompt change fails the gate, when a run fails for infrastructure reasons, or when drift starts. It uses an **incoming webhook**: a secret web address that lets a program post messages into **one** channel, and nothing else. It can't read messages, see members, or post elsewhere.

Slack changes its screens from time to time, so a button label may differ slightly from the ones below. The steps stay the same.

## 1. Get a Slack workspace

If you don't have one, create a free workspace at <https://slack.com/get-started> ("Create a new workspace"). Use your own email address. Then create a channel for the alerts, for example `#regressionguard`.

## 2. Create a Slack app

1. Open <https://api.slack.com/apps> and sign in with the same account.
2. Click **Create New App** → **From scratch**.
3. App name: `RegressionGuard`. Workspace: pick yours. Click **Create App**.

## 3. Turn on incoming webhooks

1. In the left menu of your app, open **Incoming Webhooks**.
2. Switch **Activate Incoming Webhooks** to **On**.
3. At the bottom, click **Add New Webhook** (older screens say "Add New Webhook to Workspace").
4. Choose the channel (for example `#regressionguard`) and click **Allow**.
5. A **Webhook URL** appears. It looks like `https://hooks.slack.com/services/T…/B…/…`. Click **Copy**.

## 4. Store the URL as a secret

**The webhook URL is a password.** Anyone who has it can post in your channel. So:
- Never commit it, paste it into a chat, a screenshot, an issue, or a prompt.
- Put it only in your `.env` file, which git ignores.

Open `regression-guard/.env` in your editor and set:

```
REGGUARD_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...your URL...
```

If the URL ever leaks: in the app's **Incoming Webhooks** page, remove that webhook and add a new one. The old URL stops working immediately.

## 5. Test it

From `backend/`:

```powershell
uv run python -m regguard notify test
```

You should see `Slack notified`, and a "RegressionGuard is connected" message in the channel. If not, the error says what Slack answered (for example HTTP 404 means the URL is wrong or the webhook was removed). The URL itself is never printed.

## 6. Use it

Notifications are **opt-in**: add `--notify` to a command.

```powershell
# compare a stored run with the baseline; post to Slack if the verdict is FAIL
uv run python -m regguard compare <run_id> --notify -c ../examples/support-email-classifier/regguard.yaml

# full pipeline: run, compare, write the report, notify
uv run python -m regguard run -p v2 --limit 12 --baseline main --report --notify -c ../examples/support-email-classifier/regguard.yaml

# drift check: posts once when a drift episode starts, not every day it continues
uv run python -m regguard drift --notify -c ../examples/support-email-classifier/regguard.yaml
```

Which events are sent is set in `regguard.yaml`:

```yaml
notify:
  events: [fail, error, drift]   # add "warn" to also be told about warnings
```

## What a message contains (and what it doesn't)

**It contains:** the verdict, the app, prompt and model, the main reasons, the ids of regressed cases, the run id and the report path.

**It never contains** email text or model outputs. Channels are widely read, and real inputs contain personal data. Open the HTML report (`--report`) for the details.

**A Slack problem never changes the result.** If Slack is down or the URL is wrong, you get a yellow warning, and the verdict and exit code stay the same. In CI (Phase 9), the webhook URL becomes a GitHub Actions secret.
