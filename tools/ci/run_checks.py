"""Run Composa's checks on the fetched source and print only pass or fail and counts.

This log is public. Every stage writes its output to a private file under
$RUNNER_TEMP/composa-private, which never leaves the runner. Test names of
failures go to results.json for post_results.py, which posts them on the
Composa pull request, never here.

The stages mirror Composa's own `npm run verify`, plus the RLS proof that
Composa's verify.yml runs as a second job.

Usage: python3 -I -S -B tools/ci/run_checks.py [--only STAGE ...]
"""

import argparse
import json
import os
import subprocess
import sys
import time

TEMP = os.environ.get("RUNNER_TEMP", "/tmp")
SRC = os.path.join(TEMP, "composa-source")
PRIVATE = os.path.join(TEMP, "composa-private")

# name, command, kind, timeout in minutes. kind picks how counts are read.
STAGES = [
    ("boundaries", ["npm", "run", "verify:boundaries"], "plain", 5),
    ("plugin types", ["npm", "run", "typecheck:plugin"], "plain", 5),
    ("unit tests", ["npx", "vitest", "run", "--reporter=dot", "--reporter=json", "--outputFile.json={dir}/vitest.json"], "vitest", 20),
    ("build", ["npm", "run", "build"], "plain", 10),
    ("browser tests", ["npx", "playwright", "test", "--reporter=dot,json"], "playwright", 30),
    ("auth browser tests", ["npx", "playwright", "test", "--config", "playwright.production-auth.config.ts", "--reporter=dot,json"], "playwright", 15),
    ("template browser tests", ["npx", "playwright", "test", "--config", "playwright.templates.config.ts", "--reporter=dot,json"], "playwright", 20),
    # Composa's verify.yml rls-proof job: every migration in order against a throwaway Postgres, then the assertions.
    ("database policies", ["bash", "-c", 'psql "postgresql://postgres@localhost:5432/postgres" -v ON_ERROR_STOP=1 -f supabase/rls-probe.sql '
                           '$(ls supabase/migrations/*.sql | sort | sed "s/^/-f /") -f supabase/rls-assert.sql'], "plain", 10),
]

# Keep any credential out of the stages, even one the step did not mean to pass.
DROP = ("TOKEN", "KEY", "SECRET", "PASSWORD", "PGPASS")


def clean_env(stage_dir):
    env = {k: v for k, v in os.environ.items() if not any(d in k.upper() for d in DROP)}
    env["CI"] = "1"
    env["PLAYWRIGHT_JSON_OUTPUT_NAME"] = os.path.join(stage_dir, "playwright.json")
    env["FORCE_COLOR"] = "0"
    env["PGPASSWORD"] = "postgres"  # the throwaway service container's, not a secret
    return env


def vitest_counts(stage_dir):
    with open(os.path.join(stage_dir, "vitest.json")) as f:
        data = json.load(f)
    failed = []
    for file in data.get("testResults", []):
        name = os.path.relpath(file.get("name", ""), SRC)
        for test in file.get("assertionResults", []):
            if test.get("status") == "failed":
                failed.append(f"{name} > {test.get('fullName') or test.get('title')}")
        if file.get("status") == "failed" and not any(t.get("status") == "failed" for t in file.get("assertionResults", [])):
            failed.append(f"{name} (file failed to run)")
    return {
        "passed": data.get("numPassedTests", 0),
        "failed": data.get("numFailedTests", 0),
        "skipped": data.get("numPendingTests", 0) + data.get("numTodoTests", 0),
    }, failed


def playwright_counts(stage_dir):
    with open(os.path.join(stage_dir, "playwright.json")) as f:
        data = json.load(f)
    stats = data.get("stats", {})
    failed = []

    def walk(suite, trail):
        title = suite.get("title") or ""
        here = trail + ([title] if title else [])
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                if test.get("status") == "unexpected":
                    failed.append(" > ".join(here + [spec.get("title", "")]))
        for child in suite.get("suites", []):
            walk(child, here)

    for suite in data.get("suites", []):
        walk(suite, [])
    return {
        "passed": stats.get("expected", 0),
        "failed": stats.get("unexpected", 0),
        "flaky": stats.get("flaky", 0),
        "skipped": stats.get("skipped", 0),
    }, sorted(set(failed))


def run_stage(index, name, command, kind, minutes):
    stage_dir = os.path.join(PRIVATE, f"{index:02d}")
    os.makedirs(stage_dir, exist_ok=True)
    command = [part.replace("{dir}", stage_dir) for part in command]
    started = time.time()
    with open(os.path.join(stage_dir, "output.log"), "wb") as log:
        try:
            code = subprocess.run(command, cwd=SRC, env=clean_env(stage_dir), stdout=log, stderr=subprocess.STDOUT,
                                  timeout=minutes * 60).returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            code, timed_out = 124, True
    result = {"name": name, "ok": code == 0, "seconds": round(time.time() - started), "timed_out": timed_out}
    if kind != "plain":
        try:
            counts, failed = (vitest_counts if kind == "vitest" else playwright_counts)(stage_dir)
            result["counts"] = counts
            result["failed_tests"] = failed[:50]
        except (OSError, ValueError):
            result["counts"] = None
    if kind == "plain" and code != 0:
        # The last lines of a failed type check or build name files and lines, not data.
        with open(os.path.join(stage_dir, "output.log"), "rb") as f:
            tail = f.read()[-4000:].decode("utf-8", "replace").splitlines()[-25:]
        result["tail"] = tail
    return result


def describe(result):
    counts = result.get("counts")
    parts = ["passed" if result["ok"] else ("timed out" if result["timed_out"] else "FAILED")]
    if counts:
        parts.append(", ".join(f"{v} {k}" for k, v in counts.items() if v or k in ("passed", "failed")))
    elif result.get("counts", 0) is None:
        parts.append("no report")
    parts.append(f"{result['seconds']}s")
    return f"{result['name']}: " + "; ".join(parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", default=None)
    args = parser.parse_args()
    if not os.path.isdir(SRC):
        print("No Composa source on this runner.")
        return 1
    os.makedirs(PRIVATE, exist_ok=True)
    results = []
    stop = False
    for index, (name, command, kind, minutes) in enumerate(STAGES):
        if args.only and name not in args.only:
            continue
        if stop and name != "database policies":
            results.append({"name": name, "ok": False, "skipped": True, "seconds": 0, "timed_out": False})
            print(f"{name}: not run, an earlier stage failed to build")
            continue
        result = run_stage(index, name, command, kind, minutes)
        results.append(result)
        print(describe(result), flush=True)
        # Browser tests need a working build; stop after a failed build like `npm run verify` does.
        # The database proof does not need the build, so it still runs.
        if name == "build" and not result["ok"]:
            stop = True
    ok = all(r["ok"] for r in results)
    with open(os.path.join(PRIVATE, "results.json"), "w") as f:
        json.dump({"ok": ok, "stages": results}, f)
    print("All checks passed." if ok else "Some checks failed. Details go to the Composa pull request only.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
