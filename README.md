# Who makes PostHog move faster? — Engineering Impact Dashboard

**▶ Live dashboard: https://zijianj.github.io/posthog-impact/**

An interactive, single-screen dashboard that ranks the **5 engineers driving the most
organizational velocity** in [`posthog/posthog`](https://github.com/posthog/posthog) over
the **last 90 days** — and shows *why*, in plain English, with every number visible.

## The core idea: impact ≠ activity

Commits, lines, and PR counts measure *activity*. They reward volume and miss the engineers
who make everyone else faster. This dashboard scores **impact-oriented** signals on three
transparent pillars, and weights cross-org influence (70%) above individual output (30%):

| Pillar | Question it answers | Signals | Weight |
|---|---|---|---|
| 🚀 **Reach** | How broadly does their work land? | distinct **subsystems** they ship into (60%) + merged PRs (40%) | 30% |
| 🤝 **Leverage** | How much do they accelerate others? | **review influence** — changes-requested › commented › approved (60%) + distinct teammates helped (40%) | 35% |
| 🧭 **Connection** | Do they bridge separate teams? | subsystems they **review across** (40%) + collaborators whose home subsystem differs (30%) + **network betweenness** (30%) | 35% |

Each engineer scores 0–100 per pillar, where **100 = the strongest engineer in that
dimension**. Every raw number is shown on the card, and each top-5 engineer gets a short,
**evidence-backed explanation** written for a non-technical leader.

### Why these signals (not LOC/commits)
- **Subsystems touched** (not # files) — measures *breadth of where work lands*. A subsystem ≈ a top-level dir (`products/llm_analytics`, `posthog/hogql`, `rust/feature-flags`), with `frontend/src` split one level deeper.
- **Review influence** (not # reviews) — weights a review by how much it *shapes* the work: requesting changes › commenting › rubber-stamp approval.
- **Cross-area collaborators + betweenness** — directly captures the **cross-team connector**: people who work with engineers across *different* subsystems, and who structurally sit on the paths linking otherwise-separate groups (Brandes betweenness centrality on the review graph).

This surfaces *different archetypes* of impact, not one shape of "productive":
- **Force Multiplier** — e.g. `gantoine`: only 72 of their own PRs, but reviewed 323 PRs for 68 teammates and is the single strongest network bridge. **#1 overall, yet nowhere near the top by commit count.**
- **Cross-Team Connector** — e.g. `pauldambra`, `rnegron`: review across 100+ subsystems, linking separate teams.
- **Broad Owner** — e.g. `webjunkie`: ships into 196 distinct subsystems.

## Why you can trust it
- **Every number is shown**, no black-box scores — and the blurb cites the evidence.
- **Stress-test it live**: drag the pillar weight sliders (or click a pillar) and the board
  re-ranks instantly. The top names are stable across reasonable weightings — that's the point.
- **Honest limits**: this captures collaboration visible *on GitHub*. Design, incident response,
  and mentorship in Slack/Linear/docs won't fully show. "Subsystems touched" can over-credit
  wide-but-shallow changes. A strong, validatable starting point for a conversation — not a verdict.

## Data
- **Source:** GitHub GraphQL API — every PR **merged into `posthog/posthog` in the last 90
  days** (~8,400 PRs) with file paths and the full review graph.
- **Bots excluded:** dependabot, github-actions, and AI agents (greptile, copilot, codex,
  cursor, …) — one AI reviewer alone left **2,689 reviews** and would have dwarfed every human.
- **Normalization:** each metric is scaled relative to the strongest engineer on it.

## Reproduce it
```bash
echo "GITHUB_TOKEN" > .ph_token   # any token; public_repo scope only needed to deploy
python3 collect.py                # 90d of merged PRs + reviews + file paths -> raw_prs.json
python3 analyze.py                # 3 pillars + betweenness + blurbs         -> data.json
python3 build.py                  # inline data into a self-contained page   -> index.html
python3 deploy.py                 # create repo, push, enable GitHub Pages
```
`index.html` is fully self-contained (data embedded, no JS libraries, no network calls beyond
avatars) — it loads in ~0.04s and opens directly in any browser.
