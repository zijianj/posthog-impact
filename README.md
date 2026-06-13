# Who moves PostHog forward? — Engineering Impact Dashboard

**▶ Live dashboard: https://zijianj.github.io/posthog-impact/**

An interactive, single-screen dashboard that ranks the **5 most impactful engineers**
in [`posthog/posthog`](https://github.com/posthog/posthog) over the **last 90 days** —
and, critically, shows *why*, with every underlying number visible.

## The core idea: impact ≠ volume

Lines of code, commit counts, and PR counts measure *activity*, not *impact*. They reward
noise and miss the engineers who make everyone else faster. This dashboard scores impact on
**three transparent pillars**, deliberately weighting collaboration (65%) over raw output:

| Pillar | Question it answers | Signals (from the PR + review graph) | Weight |
|---|---|---|---|
| 🚀 **Shipping** | Do they reliably land meaningful work? | merged PRs (65%) + distinct active weeks (35%) | 35% |
| 🤝 **Leverage** | Do they multiply the team? | PRs reviewed for others (60%) + distinct teammates helped (40%) | 35% |
| 🧭 **Influence** | Does the team depend on them? | distinct review collaborators (55%) + review engagement their PRs attract (45%) | 30% |

Each engineer gets a 0–100 score per pillar, where **100 = the strongest engineer in that
dimension**. The pillars blend into a final impact score. **Lines of code are never scored.**

This surfaces *different archetypes* of impact — not just one shape of "productive":
- **The Shipper** — tops output *and* stays central (e.g. `pauldambra`)
- **The Force Multiplier** — modest commit count, but reviews hundreds of PRs and unblocks
  dozens of teammates (e.g. `gantoine` — #3 overall, yet wouldn't crack the top 20 by commits)
- **The Connector** — deeply networked across the codebase (e.g. `webjunkie`, `Gilbert09`)

## Why you can trust it

- **Every number is shown.** No black-box "Score: 207." Each card lists merged PRs, active
  weeks, reviews given, teammates helped, and collaborators — plus links to the actual PRs
  they shipped, so you can spot-check in one click.
- **Stress-test it yourself.** Drag the weight sliders (or click a pillar) and the board
  re-ranks live. The top names are stable across reasonable weightings — that robustness is
  the point.
- **Honest limits.** This captures collaboration that happens *on GitHub*. Deep design work,
  incident response, and mentorship in Slack/Linear/docs won't fully show up. It's a strong,
  validatable starting point for a conversation — not a verdict.

## Data & method

- **Source:** GitHub GraphQL API. Every PR **merged into `posthog/posthog` in the last 90
  days** (~8,400 PRs) with its full review graph.
- **Bots excluded:** dependabot, github-actions, and AI agents (greptile, copilot, codex,
  cursor, etc.) — one AI reviewer alone had left **2,689 reviews** and would have dwarfed every
  human. Filtering these is essential to a fair ranking.
- **Normalization:** each raw metric is scaled relative to the strongest engineer on it, so no
  single mega-metric dominates.

## Reproduce it

```bash
echo "GITHUB_TOKEN" > .ph_token   # any token; public_repo scope only needed to deploy
python3 collect.py                # pull 90d of merged PRs + reviews  -> raw_prs.json
python3 analyze.py                # compute the 3 pillars + ranking    -> data.json
python3 build.py                  # inline data into a self-contained  -> index.html
python3 deploy.py                 # create repo, push, enable Pages
```

`index.html` is fully self-contained (data embedded, no external JS libraries, no network
calls beyond avatar images) — it loads instantly and can be opened directly in a browser.
