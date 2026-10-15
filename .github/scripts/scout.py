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
REWARD_PATTERNS = [
    re.compile(r"\$\s*([0-9][0-9,]*(?:\.\d{1,2})?)", re.I),
    re.compile(r"\bUSD\s*([0-9][0-9,]*(?:\.\d{1,2})?)\b", re.I),
    re.compile(r"\b([0-9][0-9,]*(?:\.\d{1,2})?)\s*USD\b", re.I),
]
SIMPLE = re.compile(r"\b(docs?|documentation|readme|changelog|markdown|csv|json|regex|unit test|test coverage|typo|copy edit|small script|simple cli|small bug|formatting)\b", re.I)
COMPLEX = re.compile(r"\b(remote code execution|exploit|security audit|smart contract|blockchain protocol|kernel|compiler|machine learning model|mobile app|rewrite|from scratch|production migration)\b", re.I)
PAYOUT = re.compile(r"\b(payment is released|payment will be|payout|payable|paid on merge|paid upon merge|upon merge|after merge|after acceptance|after approval|paid when|reward will be paid)\b", re.I)
ACCEPTANCE = re.compile(r"\b(acceptance criteria|requirements?|expected behavior|must|required|should|deliverable|steps to reproduce|implement|create|add|fix|update|include)\b", re.I)
ADVANCE = re.compile(r"\b(upfront fee|pay to apply|application fee|deposit\s+required|buy credits to apply|purchase credits to claim)\b", re.I)
NEGATED_FEE = re.compile(r"\b(?:no|without|never|not requiring|does not require|doesn't require)\s+(?:any\s+)?(?:upfront fee|application fee|deposit|paid credits)(?:\s+or\s+(?:any\s+)?(?:upfront fee|application fee|deposit|paid credits))*", re.I)


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
            "User-Agent": "MONEYBOT-Scout/1.0",
            **({"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"]} if os.getenv("GITHUB_TOKEN") else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("items", [])


def reward_amount(text: str):
    for pattern in REWARD_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                pass
    return None


def normalize(issue: dict) -> dict:
    title = issue.get("title") or ""
    body = issue.get("body") or ""
    full = title + "\n" + body
    low = full.lower()
    rewards = reward_amount(full)
    labels = [item.get("name", "") for item in issue.get("labels", []) if isinstance(item, dict)]
    reasons = []
    created = issue.get("created_at") or ""
    try:
        parsed = datetime.fromisoformat(created.replace("Z", "+00:00"))
        age = max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 86400)
    except (ValueError, AttributeError):
        age = 999.0
    hours = 2.0 if SIMPLE.search(full) and not COMPLEX.search(full) else (5.0 if COMPLEX.search(full) else 4.0)
    if rewards is None:
        reasons.append("no explicit USD/dollar reward amount")
    elif rewards < MIN_USD:
        reasons.append(f"reward below USD {MIN_USD:.0f}")
    if not any(term in low for term in ("bounty", "reward", "prize", "paid")):
        reasons.append("no explicit reward/bounty wording")
    if not PAYOUT.search(body):
        reasons.append("payout-after-acceptance terms not explicit")
    if len(body.strip()) < 80 or not ACCEPTANCE.search(body):
        reasons.append("clear acceptance criteria not found")
    if ADVANCE.search(NEGATED_FEE.sub("", full)):
        reasons.append("advance fee/deposit/paid credits mentioned")
    if int(issue.get("comments", 0) or 0) > 3:
        reasons.append("more than 3 comments; competition proxy exceeded")
    if age > 14:
        reasons.append(f"issue older than 14 days ({age:.1f})")
    if hours > MAX_HOURS:
        reasons.append(f"estimated work exceeds {MAX_HOURS:.0f} hours")
    if not SIMPLE.search(full) or COMPLEX.search(full):
        reasons.append("not a clearly low-complexity task")
    if issue.get("assignee") or issue.get("assignees"):
        reasons.append("already assigned")
    if any(term in low for term in ("not a bounty", "not eligible", "security challenge", "test our defenses", "proposed bounty")):
        reasons.append("proposal, eligibility, or security challenge is unclear")
    url = issue.get("html_url", "")
    repo_url = issue.get("repository_url", "")
    return {
        "lead_id": re.sub(r"[^a-zA-Z0-9_-]+", "-", url.lower()).strip("-")[-72:] or "unknown",
        "url": url,
        "title": title,
        "budget": rewards,
        "budget_currency": "USD_assumed_from_$" if rewards is not None and "$" in full else ("USD" if rewards is not None else None),
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
        "owner_action": "Review leads.jsonl and verify bounty/payout terms manually; nothing is submitted automatically." if leads else "No qualified leads. Inspect rejected.jsonl and allow the next scheduled scan to retry.",
    }
    (OUT / "scan_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
