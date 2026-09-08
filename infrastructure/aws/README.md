# AWS minimal deploy (deploy track)

This directory holds AWS deployment notes and (eventually) infrastructure definitions for the **deploy track** — minimal ECS deployment after Phases 8–9.

**Canonical guide:** [docs/deploy-track.md](../../docs/deploy-track.md)

## Status

Documentation only. No Terraform, CDK, or CloudFormation in v1. First deploy may use AWS Console or CLI for learning.

## Target resources (14a)

| Resource | Purpose |
| --- | --- |
| ECR | Container images (API + worker, same image) |
| ECS Fargate | `api` and `worker` services |
| Application Load Balancer | HTTPS, health checks on API |
| ElastiCache Redis | ARQ job queue |
| Secrets Manager | `DATABASE_URL`, `REDIS_URL`, `OPENAI_*`, `PINECONE_*`, etc. |
| CloudWatch Logs | API and worker logs |
| Security groups | ALB → API; worker outbound only |

**External:** Supabase (Postgres), OpenAI, Pinecone, GitHub — not provisioned here (D24).

## First deploy steps

TBD when implementing 14a. Follow [deploy-track.md](../docs/deploy-track.md) steps B–E:

1. Supabase project + `alembic upgrade head`
2. Build and push image to ECR (`backend/Dockerfile`; local parity via root `docker-compose.yml`)
3. Create ElastiCache, ECS cluster, task definitions, services
4. Configure ALB → API target group
5. Run [verification checklist](../docs/deploy-track.md#verification-checklist)

**O1 note:** if Docker is unreachable in WSL, build images via GitHub Actions → ECR.

## Teardown

TBD. Delete ECS services, ALB, ElastiCache cluster, ECR images, and Secrets Manager entries to stop ongoing charges.

## Cost estimate

TBD. Expect ALB hourly charge, two small Fargate tasks, and ElastiCache node — plus external Supabase/OpenAI/Pinecone usage. Use smallest instance sizes for learning.

## Phase 14b (not here yet)

Full pipeline hardening — OIDC GitHub Actions deploy, IAM task roles, documented networking — is **14b** per [roadmap.md](../docs/roadmap.md).
