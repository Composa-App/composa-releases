"""Post the checks' results on the Composa pull request, never in this log.

Reads $RUNNER_TEMP/composa-private/results.json (run_checks.py) and updates one
comment on Composa-App/Composa pull request <n>, marked so later runs edit it in
place. Needs COMPOSA_PR_TOKEN: a token that can write pull request comments on
Composa-App/Composa. Without it, prints a line saying so and exits cleanly, so
the run still shows pass or fail.

Usage: python3 -I -S -B tools/ci/post_results.py --pr-number N --source-sha SHA --run-url URL
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

REPO = "Composa-App/Composa"
MARKER = "<!-- composa-releases:web-tests -->"
TEMP = os.environ.get("RUNNER_TEMP", "/tmp")
RESULTS = os.path.join(TEMP, "composa-private", "results.json")


def api(method, path, token, body=None):
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "composa-releases-ci",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def stage_line(stage):
    if stage.get("skipped"):
        return f"| {stage['name']} | not run | |"
    counts = stage.get("counts") or {}
    detail = ", ".join(f"{v} {k}" for k, v in counts.items() if v or k in ("passed", "failed"))
    state = "passed" if stage["ok"] else ("timed out" if stage.get("timed_out") else "**failed**")
    return f"| {stage['name']} | {state} | {detail} | {stage['seconds']}s |"


def body(results, sha, run_url):
    ok = results["ok"]
    lines = [MARKER, f"### Composa checks {'passed' if ok else 'failed'} at `{sha[:12]}`", "",
             "| Stage | Result | Tests | Time |", "| --- | --- | --- | --- |"]
    lines += [stage_line(stage) for stage in results["stages"]]
    for stage in results["stages"]:
        if stage.get("failed_tests"):
            lines += ["", f"<details><summary>{stage['name']}: failing tests</summary>", ""]
            lines += [f"- {name}" for name in stage["failed_tests"]]
            lines += ["", "</details>"]
        if stage.get("tail"):
            lines += ["", f"<details><summary>{stage['name']}: last lines</summary>", "", "```"]
            lines += stage["tail"]
            lines += ["```", "", "</details>"]
    lines += ["", f"Run on a free runner in composa-releases: {run_url}"]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr-number", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--pending", action="store_true", help="Only mark the commit as being checked")
    args = parser.parse_args()
    if not re.fullmatch(r"[1-9][0-9]{0,6}", args.pr_number) or not re.fullmatch(r"[0-9a-f]{40}", args.source_sha):
        print("Bad pull request number or commit.")
        return 1
    token = os.environ.get("COMPOSA_PR_TOKEN", "")
    if not token:
        print("COMPOSA_PR_TOKEN is not set, so nothing was posted on the pull request.")
        return 0
    if args.pending:
        try:
            api("POST", f"/repos/{REPO}/statuses/{args.source_sha}", token, {
                "state": "pending", "context": "composa-releases / web tests",
                "description": "Running on a free runner", "target_url": args.run_url,
            })
        except urllib.error.HTTPError as error:
            print(f"Marking the commit failed with HTTP {error.code}.")
        return 0
    try:
        with open(RESULTS) as f:
            results = json.load(f)
    except (OSError, ValueError):
        results = {"ok": False, "stages": [{"name": "setup", "ok": False, "seconds": 0, "tail": ["The checks did not run. See the run for the failed step."]}]}
    text = body(results, args.source_sha, args.run_url)
    try:
        comments = api("GET", f"/repos/{REPO}/issues/{args.pr_number}/comments?per_page=100", token) or []
        mine = next((c for c in comments if MARKER in (c.get("body") or "")), None)
        if mine:
            api("PATCH", f"/repos/{REPO}/issues/comments/{mine['id']}", token, {"body": text})
        else:
            api("POST", f"/repos/{REPO}/issues/{args.pr_number}/comments", token, {"body": text})
        # A commit status lets the pull request show the result beside its checks.
        api("POST", f"/repos/{REPO}/statuses/{args.source_sha}", token, {
            "state": "success" if results["ok"] else "failure",
            "context": "composa-releases / web tests",
            "description": "All checks passed" if results["ok"] else "Some checks failed",
            "target_url": args.run_url,
        })
    except urllib.error.HTTPError as error:
        print(f"Posting failed with HTTP {error.code}.")
        return 1
    print("Posted the results on the pull request.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
