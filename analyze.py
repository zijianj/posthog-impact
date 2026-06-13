#!/usr/bin/env python3
"""Turn raw merged-PR + review data into a transparent 3-pillar impact ranking.

Impact != volume. Three pillars, each from concrete GitHub signals, raw numbers
always shown alongside the normalized score:

  SHIPPING  (35%)  Do they reliably land meaningful work?
                   - merged PRs           (landed work)
                   - active weeks         (consistency, not a one-off spike)
  LEVERAGE  (35%)  Do they multiply the team?
                   - PRs reviewed for others (unblocking)
                   - distinct authors helped (breadth of enabling)
  INFLUENCE (30%)  Does the team depend on them?
                   - distinct collaborators  (review-network reach)
                   - engagement their PRs attract (reviews+discussion received)

Each sub-metric is normalized 0-100 relative to the strongest engineer in that
dimension, combined into pillar scores, then weighted into a final 0-100 score.
LOC is NEVER scored (shown only as context).
"""
import json, sys, re
from collections import defaultdict
from datetime import datetime

W_SHIP, W_LEV, W_INF = 0.35, 0.35, 0.30

# --- bot / non-human-engineer detection --------------------------------------
# Explicit accounts that are bots, AI agents, scanners, or org/service handles
# (verified in the data: e.g. greptile-apps gave 2,689 reviews, stamphog 0 merges).
BOT_LOGINS = {
    "dependabot", "dependabot-preview", "github-actions", "renovate",
    "sentry-io", "posthog-bot", "posthog-contributions-bot", "codecov",
    "codecov-commenter", "snyk-bot", "sonarcloud", "greenkeeper",
    "imgbot", "allcontributors", "pre-commit-ci", "coderabbitai",
    "graphite-app", "github-advanced-security", "vercel", "netlify",
    # AI code-review / code-gen agents (not human engineers):
    "greptile-apps", "copilot-pull-request-reviewer", "copilot-swe-agent",
    "chatgpt-codex-connector", "devin-ai-integration", "cursor", "veria-ai",
    # PostHog automation / scanners / org handle:
    "stamphog", "hex-security-app", "mendral-app", "posthog",
}
# substrings that mark AI/bot accounts regardless of suffix
BOT_SUBSTR = ("copilot", "greptile", "codex-connector", "coderabbit",
              "dependabot", "renovate", "snyk", "sonarcloud")

def is_bot(login):
    if not login:
        return True
    l = login.lower()
    if l in BOT_LOGINS:
        return True
    # GitHub App naming conventions: foo[bot], foo-bot, foo-app, foo-apps
    if l.endswith("[bot]") or l.endswith("-bot") or l.endswith("_bot") \
       or l.endswith("-app") or l.endswith("-apps"):
        return True
    if any(s in l for s in BOT_SUBSTR):
        return True
    if "bot" in l and re.search(r"(^|[-_])bot([-_]|$)", l):
        return True
    return False


def iso_week(ts):
    d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def main():
    raw = json.load(open("raw_prs.json"))
    prs = raw["prs"]

    authored = defaultdict(list)          # login -> [pr,...] (merged, authored)
    active_weeks = defaultdict(set)       # login -> {iso week}
    adds = defaultdict(int); dels = defaultdict(int); files = defaultdict(int)

    reviews_given = defaultdict(set)      # reviewer -> {pr numbers reviewed (others')}
    authors_helped = defaultdict(set)     # reviewer -> {authors helped}
    review_states = defaultdict(lambda: defaultdict(int))  # reviewer -> {state:count}

    reviewers_of = defaultdict(set)       # author -> {distinct reviewers of their PRs}
    reviews_recv = defaultdict(int)       # author -> total review events received
    discuss_recv = defaultdict(int)       # author -> total PR comments received

    collaborators = defaultdict(set)      # login -> {people via review edges either dir}

    for pr in prs:
        a = (pr.get("author") or {}).get("login")
        if is_bot(a):
            continue
        authored[a].append(pr)
        if pr.get("mergedAt"):
            active_weeks[a].add(iso_week(pr["mergedAt"]))
        adds[a] += pr.get("additions", 0)
        dels[a] += pr.get("deletions", 0)
        files[a] += pr.get("changedFiles", 0)
        discuss_recv[a] += pr.get("comments", {}).get("totalCount", 0)

        seen_reviewers = set()
        for rv in (pr.get("reviews") or {}).get("nodes", []):
            r = (rv.get("author") or {}).get("login")
            if is_bot(r) or r == a:
                continue
            reviews_recv[a] += 1
            reviewers_of[a].add(r)
            collaborators[a].add(r); collaborators[r].add(a)
            reviews_given[r].add(pr["number"])
            authors_helped[r].add(a)
            review_states[r][rv.get("state", "")] += 1
            seen_reviewers.add(r)

    # universe of humans who authored and/or reviewed
    people = set(authored) | set(reviews_given)
    people = {p for p in people if not is_bot(p)}

    def m(login):
        return {
            "merged_prs": len(authored.get(login, [])),
            "active_weeks": len(active_weeks.get(login, set())),
            "reviews_given": len(reviews_given.get(login, set())),
            "authors_helped": len(authors_helped.get(login, set())),
            "collaborators": len(collaborators.get(login, set())),
            "reviews_received": reviews_recv.get(login, 0),
            "reviewers_distinct": len(reviewers_of.get(login, set())),
            "discussion_received": discuss_recv.get(login, 0),
            "additions": adds.get(login, 0),
            "deletions": dels.get(login, 0),
            "changed_files": files.get(login, 0),
        }

    metrics = {p: m(p) for p in people}

    def maxnorm(key, pool):
        mx = max((metrics[p][key] for p in pool), default=0) or 1
        return {p: 100.0 * metrics[p][key] / mx for p in pool}

    n_merged = maxnorm("merged_prs", people)
    n_weeks = maxnorm("active_weeks", people)
    n_rgiven = maxnorm("reviews_given", people)
    n_helped = maxnorm("authors_helped", people)
    n_collab = maxnorm("collaborators", people)
    n_recv = maxnorm("reviews_received", people)

    scored = {}
    for p in people:
        ship = 0.65 * n_merged[p] + 0.35 * n_weeks[p]
        lev = 0.60 * n_rgiven[p] + 0.40 * n_helped[p]
        inf = 0.55 * n_collab[p] + 0.45 * n_recv[p]
        final = W_SHIP * ship + W_LEV * lev + W_INF * inf
        scored[p] = {"shipping": round(ship, 1), "leverage": round(lev, 1),
                     "influence": round(inf, 1), "impact": round(final, 1)}

    ranked = sorted(people, key=lambda p: scored[p]["impact"], reverse=True)

    # diagnostics
    if "--diag" in sys.argv:
        # audit: which accounts got flagged as bots/non-human
        all_logins = set()
        for pr in prs:
            all_logins.add((pr.get("author") or {}).get("login"))
            for rv in (pr.get("reviews") or {}).get("nodes", []):
                all_logins.add((rv.get("author") or {}).get("login"))
        flagged = sorted(l for l in all_logins if l and is_bot(l))
        print(f"EXCLUDED as bot/non-human ({len(flagged)}):", ", ".join(flagged))
        # audit: reviewer-only accounts (0 merges, many reviews) = likely AI agents
        suspects = sorted(((p, len(reviews_given[p])) for p in people
                           if metrics[p]["merged_prs"] == 0 and len(reviews_given[p]) >= 15),
                          key=lambda x: -x[1])
        if suspects:
            print("AUDIT reviewer-only (0 merges, >=15 reviews):",
                  ", ".join(f"{p}({c})" for p, c in suspects))
        print()
        print("People (humans):", len(people), "| total merged PRs:", len(prs))
        print("\nTop 25 by merged PRs:")
        for p in sorted(people, key=lambda x: metrics[x]["merged_prs"], reverse=True)[:25]:
            print(f"  {p:24s} merged={metrics[p]['merged_prs']:4d} "
                  f"rev_given={metrics[p]['reviews_given']:4d} collab={metrics[p]['collaborators']:4d}")
        print("\nTop 25 by reviews given:")
        for p in sorted(people, key=lambda x: metrics[x]["reviews_given"], reverse=True)[:25]:
            print(f"  {p:24s} rev_given={metrics[p]['reviews_given']:4d} "
                  f"helped={metrics[p]['authors_helped']:4d} merged={metrics[p]['merged_prs']:4d}")
        print("\nTOP 15 by IMPACT:")
        for p in ranked[:15]:
            s = scored[p]
            print(f"  {p:24s} impact={s['impact']:5.1f}  ship={s['shipping']:5.1f} "
                  f"lev={s['leverage']:5.1f} inf={s['influence']:5.1f}")
        return

    # representative PRs for top engineers: most-engaged merged PRs
    def rep_prs(login, k=3):
        pl = sorted(authored.get(login, []),
                    key=lambda pr: (pr.get("reviews", {}).get("totalCount", 0)
                                    + pr.get("comments", {}).get("totalCount", 0)),
                    reverse=True)[:k]
        return [{"number": pr["number"], "title": pr["title"],
                 "reviews": pr.get("reviews", {}).get("totalCount", 0),
                 "comments": pr.get("comments", {}).get("totalCount", 0)} for pr in pl]

    PILLARS = [("shipping", "Shipping"), ("leverage", "Leverage"), ("influence", "Influence")]
    def archetype(p):
        s = scored[p]
        dom = max(PILLARS, key=lambda kv: s[kv[0]])[0]
        return {"shipping": "The Shipper", "leverage": "The Force Multiplier",
                "influence": "The Connector"}[dom]

    TOPN = 40
    board = []
    for rank, p in enumerate(ranked[:TOPN], 1):
        board.append({"rank": rank, "login": p, "archetype": archetype(p),
                      **scored[p], "metrics": metrics[p], "rep_prs": rep_prs(p)})

    out = {
        "meta": {
            "repo": raw["repo"],
            "collected_at": raw["collected_at"],
            "window_days": raw["days"],
            "total_merged_prs": len(prs),
            "total_engineers": len(people),
            "weights": {"shipping": W_SHIP, "leverage": W_LEV, "influence": W_INF},
        },
        "leaderboard": board,
    }
    json.dump(out, open("data.json", "w"), indent=2)
    print(f"Wrote data.json: {len(people)} engineers, top {TOPN} on board.")
    print("Top 5:", ", ".join(f"{b['login']}({b['impact']})" for b in board[:5]))


if __name__ == "__main__":
    main()
