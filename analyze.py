#!/usr/bin/env python3
"""Impact model v2 — favors *impact* over *activity*.

Three pillars (raw numbers always shown so a leader can validate):

  REACH      (30%)  How broadly does their work land?
                    - distinct subsystems they ship into (60%)
                    - merged PRs (40%, a volume anchor)
  LEVERAGE   (35%)  How much do they accelerate others?
                    - review influence: reviews weighted by how much they shape
                      work — changes-requested > commented > approved (60%)
                    - distinct teammates whose PRs they reviewed (40%)
  CONNECTION (35%)  Do they bridge the org? (cross-team connectors)
                    - subsystems they review across, beyond their own (40%)
                    - collaborators whose home subsystem differs from theirs (30%)
                    - network betweenness: sit on paths linking separate groups (30%)

Collaboration (Leverage+Connection = 70%) is weighted above individual output on
purpose: we want the engineers who make PostHog *move faster*, not just commit most.
Lines of code are never scored.
"""
import json, sys, re
from collections import defaultdict, Counter, deque
from datetime import datetime

W_REACH, W_LEV, W_CONN = 0.30, 0.35, 0.35

BOT_LOGINS = {
    "dependabot", "dependabot-preview", "github-actions", "renovate",
    "sentry-io", "posthog-bot", "posthog-contributions-bot", "codecov",
    "codecov-commenter", "snyk-bot", "sonarcloud", "greenkeeper", "imgbot",
    "allcontributors", "pre-commit-ci", "coderabbitai", "graphite-app",
    "github-advanced-security", "vercel", "netlify",
    "greptile-apps", "copilot-pull-request-reviewer", "copilot-swe-agent",
    "chatgpt-codex-connector", "devin-ai-integration", "cursor", "veria-ai",
    "stamphog", "hex-security-app", "mendral-app", "posthog",
}
BOT_SUBSTR = ("copilot", "greptile", "codex-connector", "coderabbit",
              "dependabot", "renovate", "snyk", "sonarcloud")

def is_bot(login):
    if not login:
        return True
    l = login.lower()
    if l in BOT_LOGINS:
        return True
    if l.endswith(("[bot]", "-bot", "_bot", "-app", "-apps")):
        return True
    if any(s in l for s in BOT_SUBSTR):
        return True
    return bool("bot" in l and re.search(r"(^|[-_])bot([-_]|$)", l))


def area(path):
    """Map a file path to a subsystem. depth-2, but depth-3 under frontend/src."""
    p = path.split("/")
    if len(p) >= 3 and p[0] == "frontend" and p[1] == "src" and "." not in p[2]:
        return f"frontend/src/{p[2]}"
    if len(p) >= 2 and "." not in p[1]:
        return f"{p[0]}/{p[1]}"
    return p[0]


def pr_areas(pr):
    return {area(f["path"]) for f in (pr.get("files") or {}).get("nodes", []) if f.get("path")}


# infra/config/test areas that get touched incidentally — noise for "centred on"
_NOISE_TOP = {".github", "bin", "docker", ".vscode", ".cursor", "requirements"}
def is_noise_area(a):
    return ("/" not in a) or a.split("/")[0] in _NOISE_TOP or a.endswith("__snapshots__")


def betweenness(adj):
    """Brandes' unweighted betweenness centrality (undirected)."""
    nodes = list(adj)
    CB = dict.fromkeys(nodes, 0.0)
    for s in nodes:
        S, P = [], {w: [] for w in nodes}
        sigma = dict.fromkeys(nodes, 0); sigma[s] = 1
        d = dict.fromkeys(nodes, -1); d[s] = 0
        Q = deque([s])
        while Q:
            v = Q.popleft(); S.append(v)
            for w in adj[v]:
                if d[w] < 0:
                    Q.append(w); d[w] = d[v] + 1
                if d[w] == d[v] + 1:
                    sigma[w] += sigma[v]; P[w].append(v)
        delta = dict.fromkeys(nodes, 0.0)
        while S:
            w = S.pop()
            for v in P[w]:
                delta[v] += (sigma[v] / sigma[w]) * (1 + delta[w])
            if w != s:
                CB[w] += delta[w]
    return {v: c / 2.0 for v, c in CB.items()}


def main():
    raw = json.load(open("raw_prs.json"))
    prs = raw["prs"]

    authored = defaultdict(list)
    areas_auth = defaultdict(set)          # author -> {subsystems they ship into}
    auth_area_ct = defaultdict(Counter)    # author -> Counter(area -> #PRs) for home/top

    prs_reviewed = defaultdict(set)        # reviewer -> {pr#}
    authors_helped = defaultdict(set)      # reviewer -> {authors}
    rev_states = defaultdict(Counter)      # reviewer -> Counter(state)
    areas_rev = defaultdict(set)           # reviewer -> {subsystems they review in}
    rev_area_ct = defaultdict(Counter)     # reviewer -> Counter(area)

    collaborators = defaultdict(set)
    adj = defaultdict(set)
    all_areas = set()

    for pr in prs:
        a = (pr.get("author") or {}).get("login")
        if is_bot(a):
            continue
        ars = pr_areas(pr)
        all_areas |= ars
        authored[a].append(pr)
        areas_auth[a] |= ars
        for ar in ars:
            auth_area_ct[a][ar] += 1
        adj.setdefault(a, set())
        for rv in (pr.get("reviews") or {}).get("nodes", []):
            r = (rv.get("author") or {}).get("login")
            if is_bot(r) or r == a:
                continue
            prs_reviewed[r].add(pr["number"])
            authors_helped[r].add(a)
            rev_states[r][rv.get("state", "")] += 1
            areas_rev[r] |= ars
            for ar in ars:
                rev_area_ct[r][ar] += 1
            collaborators[a].add(r); collaborators[r].add(a)
            adj[a].add(r); adj[r].add(a)

    people = {p for p in (set(authored) | set(prs_reviewed)) if not is_bot(p)}
    for p in people:
        adj.setdefault(p, set())

    # home subsystem: most-touched area when authoring, else when reviewing
    home = {}
    for p in people:
        c = auth_area_ct[p] or rev_area_ct[p]
        home[p] = c.most_common(1)[0][0] if c else None

    cross_area_collab = {}
    for p in people:
        hp = home[p]
        cross_area_collab[p] = sum(
            1 for c in collaborators[p] if home.get(c) and hp and home[c] != hp)

    btw = betweenness({p: adj[p] for p in people})

    def infl(p):  # review-influence: weight by how much a review shapes the work
        s = rev_states[p]
        return 1.0 * s.get("CHANGES_REQUESTED", 0) + 0.7 * s.get("COMMENTED", 0) \
            + 0.3 * s.get("APPROVED", 0) + 0.7 * s.get("DISMISSED", 0)

    M = {}
    for p in people:
        M[p] = {
            "merged_prs": len(authored[p]),
            "areas_authored": len(areas_auth[p]),
            "areas_reviewed": len(areas_rev[p]),
            "reviews_given": len(prs_reviewed[p]),
            "changes_requested": rev_states[p].get("CHANGES_REQUESTED", 0),
            "review_influence": round(infl(p), 1),
            "authors_helped": len(authors_helped[p]),
            "collaborators": len(collaborators[p]),
            "cross_area_collaborators": cross_area_collab[p],
            "betweenness": round(btw[p], 1),
            "home_area": home[p],
            "top_areas": [a for a, _ in auth_area_ct[p].most_common()
                          if not is_noise_area(a)][:3],
        }

    def maxnorm(key):
        mx = max((M[p][key] for p in people), default=0) or 1
        return {p: 100.0 * M[p][key] / mx for p in people}

    nz = {k: maxnorm(k) for k in
          ("merged_prs", "areas_authored", "areas_reviewed", "review_influence",
           "authors_helped", "cross_area_collaborators", "betweenness")}

    # percentile (for exec-friendly "top X% bridge")
    def pctile(key):
        vals = sorted(M[p][key] for p in people)
        out = {}
        for p in people:
            v = M[p][key]
            rank = sum(1 for x in vals if x <= v)
            out[p] = round(100 * rank / len(vals))
        return out
    btw_pct = pctile("betweenness")

    scored = {}
    for p in people:
        reach = 0.60 * nz["areas_authored"][p] + 0.40 * nz["merged_prs"][p]
        lev = 0.60 * nz["review_influence"][p] + 0.40 * nz["authors_helped"][p]
        conn = (0.40 * nz["areas_reviewed"][p] + 0.30 * nz["cross_area_collaborators"][p]
                + 0.30 * nz["betweenness"][p])
        final = W_REACH * reach + W_LEV * lev + W_CONN * conn
        scored[p] = {"reach": round(reach, 1), "leverage": round(lev, 1),
                     "connection": round(conn, 1), "impact": round(final, 1)}

    ranked = sorted(people, key=lambda p: scored[p]["impact"], reverse=True)

    if "--diag" in sys.argv:
        print(f"people={len(people)} prs={len(prs)} subsystems={len(all_areas)}")
        print("review-state mix:",
              dict(sum((rev_states[p] for p in people), Counter())))
        print("\nTOP 15 by IMPACT:")
        for p in ranked[:15]:
            s = scored[p]; m = M[p]
            print(f"  {p:20s} I={s['impact']:5.1f} R={s['reach']:5.1f} L={s['leverage']:5.1f} "
                  f"C={s['connection']:5.1f} | {m['merged_prs']}pr {m['areas_authored']}sub "
                  f"rev{m['reviews_given']}({m['changes_requested']}cr)→{m['authors_helped']}ppl "
                  f"xarea{m['cross_area_collaborators']} btw{m['betweenness']:.0f}")
        return

    # ----- exec-friendly, evidence-based blurbs --------------------------------
    def archetype(p):
        s = scored[p]
        return max([("reach", "Broad Owner"), ("leverage", "Force Multiplier"),
                    ("connection", "Cross-Team Connector")], key=lambda kv: s[kv[0]])[1]

    def areas_phrase(p):
        ta = M[p]["top_areas"]
        nice = [a.replace("products/", "").replace("frontend/src/", "frontend·")
                 .replace("posthog/", "backend·") for a in ta[:2]]
        return " & ".join(nice) if nice else "the codebase"

    def bridge_clause(p):
        bp = btw_pct[p]
        if bp >= 92:
            return "ranks among PostHog's strongest bridges between separate teams"
        if bp >= 75:
            return "acts as a notable cross-team bridge"
        return f"connects {M[p]['cross_area_collaborators']} engineers across other areas"

    def blurb(p):
        m = M[p]
        dom = archetype(p)
        br = bridge_clause(p)
        if dom == "Cross-Team Connector":
            return (f"The org's connective tissue: reviews across <b>{m['areas_reviewed']} "
                    f"subsystems</b> and {br}. Influence reaches far beyond their own "
                    f"<b>{m['merged_prs']}</b> PRs.")
        if dom == "Force Multiplier":
            cr = (f" (<b>{m['changes_requested']}</b> pushing for changes)"
                  if m["changes_requested"] >= 3 else "")
            return (f"Reviewed <b>{m['reviews_given']} PRs</b>{cr} for <b>{m['authors_helped']} "
                    f"teammates</b> and {br}. Shapes far more code than the <b>{m['merged_prs']}</b> "
                    f"PRs they write.")
        return (f"Ships into <b>{m['areas_authored']} subsystems</b> (<b>{m['merged_prs']}</b> PRs, "
                f"centred on {areas_phrase(p)}) while still reviewing <b>{m['reviews_given']}</b> "
                f"PRs for {m['authors_helped']} teammates — wide ownership, active reviewer.")

    def rep_prs(p, k=2):
        pl = sorted(authored[p], key=lambda pr: (pr.get("reviews", {}).get("totalCount", 0)
                    + pr.get("comments", {}).get("totalCount", 0)), reverse=True)[:k]
        return [{"number": pr["number"], "title": pr["title"],
                 "reviews": pr.get("reviews", {}).get("totalCount", 0),
                 "comments": pr.get("comments", {}).get("totalCount", 0)} for pr in pl]

    board = []
    for rank, p in enumerate(ranked[:40], 1):
        board.append({"rank": rank, "login": p, "archetype": archetype(p),
                      "blurb": blurb(p), **scored[p],
                      "betweenness_pct": btw_pct[p],
                      "metrics": M[p], "rep_prs": rep_prs(p)})

    out = {"meta": {"repo": raw["repo"], "collected_at": raw["collected_at"],
                    "window_days": raw["days"], "total_merged_prs": len(prs),
                    "total_engineers": len(people), "total_subsystems": len(all_areas),
                    "weights": {"reach": W_REACH, "leverage": W_LEV, "connection": W_CONN}},
           "leaderboard": board}
    json.dump(out, open("data.json", "w"), indent=2)
    print(f"Wrote data.json: {len(people)} engineers, {len(all_areas)} subsystems.")
    print("Top 5:", ", ".join(f"{b['login']}({b['impact']},{b['archetype']})" for b in board[:5]))


if __name__ == "__main__":
    main()
