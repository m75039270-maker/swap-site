# TabClean + MONEYBOT

**TabClean** is a browser-only CSV cleaner. It can trim whitespace, remove empty rows, remove duplicate rows, normalize headers, preview the first 100 data rows, and download a cleaned CSV. Files are processed locally in your browser; there is no file-upload endpoint or analytics script.

## Use TabClean

- The public site is expected at `https://m75039270-maker.github.io/swap-site/` **after the Pages workflow succeeds**.
- Until the GitHub Pages setup is enabled and deployment succeeds, open `index.html` directly in a browser or serve it locally with `python -m http.server 8000`.

## MONEYBOT SCOUT schedule

The workflow at [`.github/workflows/scout.yml`](.github/workflows/scout.yml) runs on pushes touching the scanner, via manual dispatch, and every six hours. It searches recent public GitHub issues that may offer bounty rewards, applies a conservative filter, and uploads `candidates.jsonl`, `leads.jsonl`, `rejected.jsonl`, and `scan_status.json` as a 7-day Actions artifact.

Open [Actions](../../actions) → **MONEYBOT SCOUT — paid task discovery** → the newest run → **Artifacts** to download the latest result. A search hit is only a candidate: verify the issue is still open, eligibility and payout terms remain valid, and the task has not already been claimed. No bids, comments, pull requests, or messages are sent automatically.

## Pages deployment status

GitHub Actions first tried to deploy the static page, but GitHub returned **“Resource not accessible by integration”** while attempting to create the Pages site. This means repository Pages needs to be enabled by an owner once:

1. Open [Settings → Pages](../../settings/pages).
2. Under **Build and deployment**, choose **GitHub Actions** as the source.
3. Return to [Actions](../../actions) and re-run **Deploy TabClean to GitHub Pages** (or push a change to `index.html`).

The deployment is considered complete only when a Pages job succeeds and the public URL loads successfully.

## Local MONEYBOT package

The full local-first Python project and setup instructions are available in the separate MONEYBOT ZIP artifact shared in the ChatGPT conversation. The local runner stores private owner accounting in `ventures/pnl.csv`, keeps actual receipts separate from forecasts, and requires manual approval before any submission. No paid API keys or hosting purchases are required by the starter configuration.
