#!/usr/bin/env python3
"""Collect PRs MERGED in the last 90 days from posthog/posthog via GitHub GraphQL,
including each PR's review graph. Windowed by mergedAt to respect the 1000/query
search cap. Checkpoints to raw_prs.json after every window.

Token: $GITHUB_TOKEN, ./ .ph_token, ~/.ph_token, or argv[1].
"""
import json, os, sys, time, urllib.request, urllib.error
from datetime import date, timedelta, datetime

REPO = "posthog/posthog"
DAYS = 90
WINDOW_DAYS = 7          # 7d * ~94 merged/day ~= 658 < 1000 search cap
PAGE = 50
GQL_URL = "https://api.github.com/graphql"


def get_token():
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"].strip()
    for p in [".ph_token", os.path.expanduser("~/.ph_token")]:
        if os.path.exists(p):
            return open(p).read().strip()
    if len(sys.argv) > 1:
        return sys.argv[1].strip()
    sys.exit("No token.")


TOKEN = get_token()

QUERY = """
query($q: String!, $cursor: String) {
  rateLimit { remaining cost }
  search(query: $q, type: ISSUE, first: %d, after: $cursor) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        number
        title
        author { login }
        createdAt
        mergedAt
        additions
        deletions
        changedFiles
        comments { totalCount }
        reviews(first: 50) {
          totalCount
          nodes { author { login } state }
        }
      }
    }
  }
}
""" % PAGE


def gql(variables):
    body = json.dumps({"query": QUERY, "variables": variables}).encode()
    req = urllib.request.Request(
        GQL_URL, data=body,
        headers={"Authorization": f"bearer {TOKEN}",
                 "Content-Type": "application/json",
                 "User-Agent": "posthog-impact"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            if "errors" in data:
                msg = json.dumps(data["errors"])[:300]
                if any(k in msg.upper() for k in ("RATE_LIMIT", "TIMEOUT", "ABUSE")):
                    time.sleep(8 * (attempt + 1)); continue
                raise RuntimeError(msg)
            return data["data"]
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 403, 429):
                time.sleep(8 * (attempt + 1)); continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(4 * (attempt + 1))
    raise RuntimeError("GraphQL failed after retries")


def windows():
    end = date.today()
    start = end - timedelta(days=DAYS)
    cur, out = start, []
    while cur <= end:
        nxt = min(cur + timedelta(days=WINDOW_DAYS - 1), end)
        out.append((cur.isoformat(), nxt.isoformat()))
        cur = nxt + timedelta(days=1)
    return out


def save(prs):
    tmp = "raw_prs.json.tmp"
    with open(tmp, "w") as f:
        json.dump({"collected_at": datetime.utcnow().isoformat() + "Z",
                   "repo": REPO, "days": DAYS, "basis": "merged",
                   "prs": list(prs.values())}, f)
    os.replace(tmp, "raw_prs.json")


def collect():
    prs = {}
    wins = windows()
    for i, (a, b) in enumerate(wins, 1):
        q = f"repo:{REPO} is:pr is:merged merged:{a}..{b}"
        cursor, page, wcount = None, 0, None
        while True:
            d = gql({"q": q, "cursor": cursor})
            s = d["search"]
            wcount = s["issueCount"]
            for n in s["nodes"]:
                if n:
                    prs[n["number"]] = n
            page += 1
            if not s["pageInfo"]["hasNextPage"]:
                break
            cursor = s["pageInfo"]["endCursor"]
            time.sleep(0.4)
        if wcount and wcount > 1000:
            print(f"  !! WARN window {a}..{b} has {wcount} > 1000 cap; shrink WINDOW_DAYS",
                  flush=True)
        save(prs)
        print(f"[{i}/{len(wins)}] {a}..{b}: window={wcount} totalPRs={len(prs)} "
              f"rl={d['rateLimit']['remaining']}", flush=True)
    return prs


if __name__ == "__main__":
    print(f"Collecting merged PRs, last {DAYS}d of {REPO}...", flush=True)
    t0 = time.time()
    prs = collect()
    save(prs)
    print(f"\nDONE {len(prs)} PRs in {time.time()-t0:.0f}s -> raw_prs.json", flush=True)
