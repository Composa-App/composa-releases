"""Link a Vercel preview on the Composa pull request, never in this log.

Reads the link that `vercel deploy` wrote to $RUNNER_TEMP/composa-private/preview-url
and updates one comment on Composa-App/Composa pull request <n>, marked so later
runs edit it in place. Needs COMPOSA_PR_TOKEN: a token that can write pull
request comments on Composa-App/Composa. Without it, prints a line saying so and
exits cleanly.

Usage: python3 -I -S -B tools/ci/post_preview.py --pr-number N --source-sha SHA --run-url URL
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

REPO = "Composa-App/Composa"
MARKER = "<!-- composa-releases:preview -->"
TEMP = os.environ.get("RUNNER_TEMP", "/tmp")
LINK = os.path.join(TEMP, "composa-private", "preview-url")
# vercel deploy prints the deployment's own address on stdout.
PREVIEW = re.compile(r"https://[a-z0-9-]+\.vercel\.app")


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr-number", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-url", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[1-9][0-9]{0,6}", args.pr_number) or not re.fullmatch(r"[0-9a-f]{40}", args.source_sha):
        print("Bad pull request number or commit.")
        return 1
    token = os.environ.get("COMPOSA_PR_TOKEN", "")
    if not token:
        print("COMPOSA_PR_TOKEN is not set, so nothing was posted on the pull request.")
        return 0
    try:
        with open(LINK) as f:
            found = PREVIEW.findall(f.read())
    except OSError:
        found = []
    if not found:
        print("vercel deploy gave no preview link.")
        return 1
    text = "\n".join([
        MARKER,
        f"**Preview:** {found[-1]}",
        "",
        f"Built from `{args.source_sha[:12]}` by Vercel, deployed from a free runner in composa-releases: {args.run_url}",
    ])
    try:
        comments = api("GET", f"/repos/{REPO}/issues/{args.pr_number}/comments?per_page=100", token) or []
        mine = next((c for c in comments if MARKER in (c.get("body") or "")), None)
        if mine:
            api("PATCH", f"/repos/{REPO}/issues/comments/{mine['id']}", token, {"body": text})
        else:
            api("POST", f"/repos/{REPO}/issues/{args.pr_number}/comments", token, {"body": text})
    except urllib.error.HTTPError as error:
        print(f"Posting failed with HTTP {error.code}.")
        return 1
    print("Linked the preview on the pull request.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
