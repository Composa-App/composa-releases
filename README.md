# composa-releases

The release pipeline for **Composa**. This repository holds workflows and credentials. **It holds no app source.**

Source lives in the private repository Composa-App/Composa. A read-only deploy key clones it onto the runner for the length of a job and removes it afterwards.

## Why this repo is public

GitHub's free plan only offers required reviewers on public repositories. That reviewer is what gates production. Being public costs nothing here: there is no source, GitHub encrypts secrets, and a pull request from a fork never receives them.

**These logs are public.** Workflows print outcomes, counts and commit IDs. They never print query results, row contents, deployment URLs or secrets.

## Workflows

| Workflow | Does | Environment |
| --- | --- | --- |
| **Composa database ops** (`db-ops.yml`) | Lists pending migrations, proves them in a transaction that rolls back, or applies them with the Supabase CLI | `composa-staging`, `composa-production` |
| **Composa web deploy** (`web-deploy.yml`) | Deploys a commit to Vercel: a preview for staging, the live site for production | `composa-staging`, `composa-production` |
| **Composa web tests** (`web-tests-pr.yml`) | Runs Composa's `npm run verify` and the RLS proof at the head of a Composa pull request, posts the results on that pull request, and deploys that head to a Vercel preview linked there | `composa-staging` |
| **Composa web tests on a schedule** (`web-tests-schedule.yml`) | Every 15 minutes, dispatches the web tests for one open Composa pull request head that has no run yet | `composa-staging` |

## Free test runs for Composa pull requests

Actions minutes are free on public repositories, so Composa's tests run here
instead of in Composa's own verify workflow. The schedule picks up each new
pull request head within about 15 minutes, one run at a time. To test a head
right away, run **Composa web tests** by hand with the pull request number and
its head commit.

The log shows only pass or fail and counts per stage. Failing test names, and
the last lines of a failed build, go to a comment on the Composa pull request,
which also gets a `composa-releases / web tests` commit status.

## Free previews for Composa pull requests

The same run deploys the pull request head to a Vercel preview, which uses
Vercel's Preview settings (composa-staging), and links it in a comment on the
pull request. This replaces Composa's own pr-preview.yml, which stops when
Composa's Actions minutes run out. Vercel builds the code; the runner only
uploads it. The link goes only to the pull request, so the preview is skipped
when `COMPOSA_PR_TOKEN` is not set.

Secrets in the `composa-staging` environment:

| Secret | Needed for | What it is |
| --- | --- | --- |
| `COMPOSA_SOURCE_DEPLOY_KEY` | fetching the pull request head | already there for the deploy workflows |
| `COMPOSA_UI_DEPLOY_KEY` | `npm ci` of the private `@composa/ui` dependency | a read-only deploy key on Composa-UI/react-ui (Bitwarden: COMPOSA_RELEASES_UI_DEPLOY_KEY) |
| `COMPOSA_PR_TOKEN` | posting results and preview links; listing open pull requests exactly | a fine-grained token for Composa-App/Composa with Pull requests and Commit statuses set to read and write |
| `VERCEL_TOKEN` | deploying previews | already there for the deploy workflow |

Without `COMPOSA_PR_TOKEN` the tests still run and the run shows pass or fail,
but nothing is posted on the pull request, no preview is made, and the schedule finds open pull
requests from their merge refs instead.

Each token is present only in the step that needs it, and removed before any
Composa code runs.

Every production run waits for a required reviewer to approve it. Runs are started from `main` of this repository only, and take source from `main` of Composa-App/Composa or a full commit given as `sha`.
