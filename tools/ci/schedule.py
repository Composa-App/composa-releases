"""Pick at most one Composa pull request head with no test run yet, and dispatch web-tests-pr.yml for it.

Three steps, each run with only the credential it needs:

  runs      GITHUB_TOKEN of this repo: lists recent web-tests-pr.yml runs.
  pick      COMPOSA_PR_TOKEN, or the read-only deploy key when that token is
            not set: lists open Composa pull requests against main.
  dispatch  GITHUB_TOKEN: dispatches web-tests-pr.yml for the picked head.

They hand over through $RUNNER_TEMP/composa-schedule. Only pull request numbers
and commits are printed: both are already public in run names.

Usage: python3 -I -S -B tools/ci/schedule.py runs|pick|dispatch
"""

import json
import os
import re
import subprocess
import sys
import urllib.request

COMPOSA = "Composa-App/Composa"
WORKFLOW = "web-tests-pr.yml"
TEMP = os.environ.get("RUNNER_TEMP", "/tmp")
STATE = os.path.join(TEMP, "composa-schedule")
TITLE = re.compile(r"#(\d+) at ([0-9a-f]{40})")
# Without COMPOSA_PR_TOKEN the deploy key sees pull refs but not which are open;
# GitHub keeps refs/pull/<n>/merge for open pull requests, and only the newest
# few numbers are considered so a stale merge ref cannot keep an old one alive.
FALLBACK_NEWEST = 12


def github(method, url, token, body=None):
    request = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "composa-releases-ci",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def save(name, data):
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, name), "w") as f:
        json.dump(data, f)


def load(name):
    with open(os.path.join(STATE, name)) as f:
        return json.load(f)


def runs():
    token = os.environ["GH_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    data = github("GET", f"https://api.github.com/repos/{repo}/actions/workflows/{WORKFLOW}/runs?per_page=100", token)
    tested, busy = [], False
    for run in data.get("workflow_runs", []):
        match = TITLE.search(run.get("display_title") or "")
        if match:
            tested.append(match.group(2))
        if run.get("status") in ("queued", "in_progress", "waiting", "pending", "requested"):
            busy = True
    save("runs.json", {"tested": tested, "busy": busy})
    print(f"{len(tested)} recent runs; {'one is still going' if busy else 'none running'}.")
    return 0


def open_pulls_with_token(token):
    pulls = github("GET", f"https://api.github.com/repos/{COMPOSA}/pulls?state=open&base=main&sort=updated&direction=desc&per_page=50", token)
    return [(p["number"], p["head"]["sha"]) for p in pulls
            if (p.get("head", {}).get("repo") or {}).get("full_name") == COMPOSA]


def open_pulls_with_key(deploy_key):
    key = os.path.join(TEMP, "schedule-key")
    with open(os.open(key, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write(deploy_key.strip() + "\n")
    try:
        env = dict(os.environ, GIT_SSH_COMMAND=f"ssh -i {key} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new")
        out = subprocess.run(["git", "ls-remote", f"git@github.com:{COMPOSA}.git", "refs/pull/*/head", "refs/pull/*/merge"],
                             env=env, capture_output=True, text=True, timeout=120, check=True).stdout
    finally:
        os.remove(key)
    heads, merges = {}, set()
    for line in out.splitlines():
        sha, ref = line.split("\t")
        match = re.fullmatch(r"refs/pull/(\d+)/(head|merge)", ref)
        if not match:
            continue
        number = int(match.group(1))
        if match.group(2) == "head":
            heads[number] = sha
        else:
            merges.add(number)
    numbers = sorted((n for n in heads if n in merges), reverse=True)[:FALLBACK_NEWEST]
    return [(n, heads[n]) for n in numbers]


def pick():
    state = load("runs.json")
    if state["busy"]:
        save("pick.json", {})
        print("A run is still going; picking nothing this time.")
        return 0
    token = os.environ.get("COMPOSA_PR_TOKEN", "")
    deploy_key = os.environ.get("COMPOSA_SOURCE_DEPLOY_KEY", "")
    if token:
        pulls = open_pulls_with_token(token)
    elif deploy_key:
        pulls = open_pulls_with_key(deploy_key)
    else:
        print("Neither COMPOSA_PR_TOKEN nor the deploy key is available.")
        return 1
    tested = set(state["tested"])
    waiting = [(n, sha) for n, sha in pulls if sha not in tested]
    choice = waiting[0] if waiting else None
    save("pick.json", {"pr_number": str(choice[0]), "source_sha": choice[1]} if choice else {})
    print(f"{len(pulls)} open pull requests, {len(waiting)} heads not yet tested."
          + (f" Picked #{choice[0]} at {choice[1]}." if choice else ""))
    return 0


def dispatch():
    choice = load("pick.json")
    if not choice:
        print("Nothing to dispatch.")
        return 0
    if not re.fullmatch(r"[1-9][0-9]{0,6}", choice["pr_number"]) or not re.fullmatch(r"[0-9a-f]{40}", choice["source_sha"]):
        print("Bad pick.")
        return 1
    repo = os.environ["GITHUB_REPOSITORY"]
    github("POST", f"https://api.github.com/repos/{repo}/actions/workflows/{WORKFLOW}/dispatches", os.environ["GH_TOKEN"],
           {"ref": "main", "inputs": choice})
    print(f"Dispatched the tests for #{choice['pr_number']} at {choice['source_sha']}.")
    return 0


if __name__ == "__main__":
    steps = {"runs": runs, "pick": pick, "dispatch": dispatch}
    if len(sys.argv) != 2 or sys.argv[1] not in steps:
        print(__doc__)
        sys.exit(2)
    sys.exit(steps[sys.argv[1]]())
