# ECS deploy archive

Historical copies kept for the deploy-track / ECS resume path. **Not** executed by GitHub Actions (only repo-root `.github/workflows/` runs).

| File | Was |
| --- | --- |
| [`deploy.yml`](deploy.yml) | Snapshot of the OIDC → ECR → ECS pipeline (push-triggered). |

A copy also lives at [`.github/workflows/deploy.yml`](../../../.github/workflows/deploy.yml) (push to `main`/`master`). Live demos: [`infrastructure/ec2/`](../../ec2/README.md). Tests also run via [`tests.yml`](../../../.github/workflows/tests.yml).
