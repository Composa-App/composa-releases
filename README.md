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

Every production run waits for a required reviewer to approve it. Runs are started from `main` of this repository only, and take source from `main` of Composa-App/Composa or a full commit given as `sha`.
