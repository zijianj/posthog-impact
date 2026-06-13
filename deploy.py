#!/usr/bin/env python3
"""Deploy index.html to GitHub Pages. Needs a token with `public_repo` scope.
Creates the repo (idempotent), pushes, enables Pages, waits for it to go live.
"""
import json, os, subprocess, sys, time, urllib.request, urllib.error

REPO_NAME = "posthog-impact"
HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, ".ph_token")).read().strip()


def api(method, path, body=None):
    url = "https://api.github.com" + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"token {TOKEN}", "Accept": "application/vnd.github+json",
        "User-Agent": "ph-deploy", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def sh(*args, check=True):
    r = subprocess.run(args, cwd=HERE, capture_output=True, text=True)
    if check and r.returncode != 0:
        print("ERR:", " ".join(args), "\n", r.stderr); sys.exit(1)
    return r


def main():
    st, me = api("GET", "/user")
    if st != 200:
        sys.exit(f"Token check failed ({st}): {me.get('message')}. "
                 "Does it have `public_repo` scope?")
    user = me["login"]
    print(f"Authenticated as {user}")

    # 1) create repo (ignore 422 = already exists)
    st, r = api("POST", "/user/repos", {
        "name": REPO_NAME, "private": False,
        "description": "Who moves PostHog forward? — the 5 most impactful engineers, last 90 days.",
        "homepage": f"https://{user}.github.io/{REPO_NAME}/", "has_issues": False,
        "has_wiki": False, "has_projects": False})
    print("repo create:", st, r.get("message", "ok"))

    # 2) git init + commit + push
    if not os.path.isdir(os.path.join(HERE, ".git")):
        sh("git", "init", "-q")
    sh("git", "checkout", "-q", "-B", "main")
    sh("git", "add", "index.html", "data.json", "README.md", "collect.py",
       "analyze.py", "build.py", "template.html", "deploy.py", ".gitignore")
    sh("git", "-c", "user.name=zijianj", "-c", "user.email=zijian.jiang@osaro.com",
       "commit", "-q", "-m", "PostHog engineering impact dashboard", check=False)
    remote = f"https://{user}:{TOKEN}@github.com/{user}/{REPO_NAME}.git"
    sh("git", "remote", "remove", "origin", check=False)
    sh("git", "remote", "add", "origin", remote)
    push = sh("git", "push", "-q", "-u", "origin", "main", "--force", check=False)
    if push.returncode != 0:
        print("push stderr:", push.stderr)
    else:
        print("pushed to main")

    # 3) enable Pages (idempotent)
    st, r = api("POST", f"/repos/{user}/{REPO_NAME}/pages",
                {"source": {"branch": "main", "path": "/"}})
    if st == 409 or (st == 422 and "already" in json.dumps(r).lower()):
        api("PUT", f"/repos/{user}/{REPO_NAME}/pages",
            {"source": {"branch": "main", "path": "/"}})
        print("pages: already enabled")
    else:
        print("pages enable:", st, r.get("message", r.get("html_url", "ok")))

    url = f"https://{user}.github.io/{REPO_NAME}/"
    print(f"\nPages URL: {url}\nWaiting for it to go live...")
    for i in range(40):
        time.sleep(6)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ph-deploy"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    print(f"LIVE ✅  {url}"); return
        except urllib.error.HTTPError as e:
            if e.code == 200:
                print(f"LIVE ✅  {url}"); return
        except Exception:
            pass
        print(f"  ...not yet ({(i+1)*6}s)")
    print(f"Still propagating — should be live shortly at {url}")


if __name__ == "__main__":
    main()
