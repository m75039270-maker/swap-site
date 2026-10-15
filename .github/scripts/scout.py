from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path("moneybot-scout-output")
OUT.mkdir(exist_ok=True)
MIN_USD = 20.0
MAX_HOURS = 3.0
MONEY = re.compile(r"\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)", re.I)
BODY_REWARD = re.compile(r"\b(?:bounty|prize|reward|budget|compensation)\b[^\n$]{0,35}\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)", re.I)
SIMPLE = re.compile(r"\b(docs?|documentation|readme|changelog|markdown|csv|json|regex|unit test|test coverage|typo|copy edit|small script|simple cli|small bug|formatting)\b", re.I)
COMPLEX = re.compile(r"\b(remote code execution|exploit|security audit|smart contract|blockchain protocol|kernel|compiler|machine learning model|mobile app|rewrite|from scratch|production migration|visuali[sz](?:er|ation)|network graph|interactive graph|all-pairs shortest path|floyd-warshall|real[- ]time|turnkey generator|multi[- ]component deliverable|full[- ]stack|dashboard|production pipeline|API integration)\b", re.I)
PAYOUT = re.compile(
    r"\b(?:payment|bounty|reward|prize|funds)\b.{0,60}\b(?:paid|released|sent|transferred|pays out)\b.{0,60}\b(?:upon|after|once|following|when)\b.{0,35}\b(?:merge|acceptance|approval|review|PR accepted)\b"
    r"|\b(?:paid|released|sent|transferred)\s+(?:upon|after|once|following)\s+(?:merge|acceptance|approval|review)\b",
    re.I | re.S,
)
ACCEPTANCE = re.compile(r"\b(acceptance criteria|requirements?|expected behavior|must|required|should|deliverable|steps to reproduce|implement|create|add|fix|update|include)\b", re.I)
ADVANCE = re.compile(r"\b(upfront fee|pay to apply|application fee|deposit\s+required|buy credits to apply|purchase credits to claim)\b", re.I)
NEGATED_FEE = re.compile(r"\b(?:no|without|never|not requiring|does not require|doesn't require)\s+(?:any\s+)?(?:upfront fee|application fee|deposit|paid credits)(?:\s+or\s+(?:any\s+)?(?:upfront fee|application fee|deposit|paid credits))*", re.I)
EXPLICIT_ETA = re.compile(r"\b(?:ETA|estimated effort|time estimate|estimate)\s*[:=-]\s*(\d+(?:\.\d+)?)\s*(hours?|hrs?|h)\b", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def append_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def query_issues(query: str) -> list[dict]:
    params = urllib.parse.urlencode({"q": query, "sort": "created", "order": "desc", "per_page": 100})
    request = urllib.request.Request(
        "https://api.github.com/search/issues?" + params,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "MONEYBOT-Scout/1.1",
            **({"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"]} if os.getenv("GITHUB_TOKEN") else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("items", [])


def reward_amount(title: str, body: str) -> float | None:
    # Prefer a number in the title; don't mistake dollar values in source code
    # examples, wallet descriptions, or unrelated prose for an advertised reward.
    if any(term in title.lower() for term in ("bounty", "reward", "prize", "paid")):
        match = MONEY.search(title)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                pass
    clean_body = re.sub(r"\x60\x60\x60.*?\x60\x60\x60", " ", body, flags=re.S)
    clean_body = re.sub(r"\x60[^\x60]*\x60", " ", clean_body)
    match = BODY_REWARD.search(clean_body)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


def explicit_hours(text: str) -> float | None:
    match = EXPLICIT_ETA.search(text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def normalize(issue: dict) -> dict:
    title = issue.get("title") or ""
    body = issue.get("body") or ""
    full = title + "\n" + body
    low = full.lower()
    reward = reward_amount(title, body)
    labels = [item.get("name", "") for item in issue.get("labels", []) if isinstance(item, dict)]
    reasons = []
    created = issue.get("created_at") or ""
    try:
        parsed = datetime.fromisoformat(created.replace("Z", "+00:00"))
        age = max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 86400)
    except (ValueError, AttributeError):
        age = 999.0
    stated_hours = explicit_hours(full)
    if stated_hours is not None:
        hours = stated_hours
    elif COMPLEX.search(full):
        hours = 5.0
    elif SIMPLE.search(full):
        hours = 2.0
    else:
        hours = 4.0
    if reward is None:
        reasons.append("no explicit USD/dollar reward amount tied to bounty title or reward field")
    elif reward < MIN_USD:
        reasons.append(f"reward below USD {MIN_USD:.0f}")
    if not any(term in low for term in ("bounty", "reward", "prize", "paid")):
        reasons.append("no explicit reward/bounty wording")
    if not PAYOUT.search(body):
        reasons.append("no specific payout-after-acceptance/merge terms found")
    if len(body.strip()) < 80 or not ACCEPTANCE.search(body):
        reasons.append("clear acceptance criteria not found")
    fee_check = NEGATED_FEE.sub("", full)
    if ADVANCE.search(fee_check):
        reasons.append("advance fee/deposit/paid credits mentioned")
    if int(issue.get("comments", 0) or 0) > 3:
        reasons.append("more than 3 comments; competition proxy exceeded")
    if age > 14:
        reasons.append(f"issue older than 14 days ({age:.1f})")
    if hours > MAX_HOURS:
        reasons.append(f"estimated work exceeds {MAX_HOURS:.0f} hours ({hours:.1f} stated/estimated)")
    if not SIMPLE.search(full) or COMPLEX.search(full):
        reasons.append("not a clearly low-complexity task")
    if issue.get("assignee") or issue.get("assignees"):
        reasons.append("already assigned")
    if any(term in low for term in ("not a bounty", "not eligible", "security challenge", "test our defenses", "proposed bounty")):
        reasons.append("proposal, eligibility, or security challenge is unclear")
    url = issue.get("html_url", "")
    repo_url = issue.get("repository_url", "")
    currency = "USD_assumed_from_$" if reward is not None else None
    return {
        "lead_id": re.sub(r"[^a-zA-Z0-9_-]+", "-", url.lower()).strip("-")[-72:] or "unknown",
        "url": url,
        "title": title,
        "budget": reward,
        "budget_currency": currency,
        "deadline": None,
        "skills": labels,
        "can_autosolve": not reasons,
        "est_hours": hours,
        "source": "GitHub Issues Search API",
        "source_created_at": created,
        "source_updated_at": issue.get("updated_at"),
        "comments": int(issue.get("comments", 0) or 0),
        "repository_url": repo_url,
        "checked_at": now_iso(),
        "status": "qualified_pending_owner_review" if not reasons else "rejected_by_filters",
        "rejection_reasons": reasons,
        "description_excerpt": body[:700],
        "needs_owner": True,
    }


def main() -> int:
    since = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
    queries = [
        f'is:issue is:open label:bounty created:>{since} "$"',
        f'is:issue is:open in:title bounty created:>{since} "$"',
        f'is:issue is:open in:title bounty created:>{since} USDC',
    ]
    items = {}
    errors = []
    for query in queries:
        try:
            for issue in query_issues(query):
                if issue.get("pull_request") or not issue.get("html_url"):
                    continue
                items[issue["html_url"]] = issue
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            errors.append({"query": query, "error": type(error).__name__ + ": " + str(error)})
    candidates = [normalize(item) for item in items.values()]
    leads = [item for item in candidates if item["can_autosolve"]]
    leads.sort(key=lambda item: (item["budget"] or 0, -item["comments"]), reverse=True)
    rejected = [item for item in candidates if not item["can_autosolve"]]
    append_jsonl(OUT / "candidates.jsonl", candidates)
    append_jsonl(OUT / "leads.jsonl", leads)
    append_jsonl(OUT / "rejected.jsonl", rejected)
    status = {
        "checked_at": now_iso(),
        "source": "GitHub Issues Search API",
        "scanned": len(candidates),
        "qualified": len(leads),
        "rejected": len(rejected),
        "errors": errors,
        "status": "ok" if not errors else ("partial" if candidates else "network_error"),
        "owner_action": "Review leads.jsonl and verify the issue is still open, payout/eligibility are explicit, and no one has already claimed it. Nothing is submitted automatically." if leads else "No qualified leads. Inspect rejected.jsonl; next scheduled scan retries automatically.",
    }
    (OUT / "scan_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
