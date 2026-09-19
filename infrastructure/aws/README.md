# AWS minimal deploy (Deploy Track / 14a)

Console-first record of the first cloud deployment. Product guide: [docs/deploy-track.md](../../docs/deploy-track.md).

**Status: 14a complete** — deployed and end-to-end tested; publicly reachable over **HTTPS** at `https://api.airepoagent.app`.

| Approach | Detail |
| --- | --- |
| Infrastructure | AWS Console |
| Image publish | One CLI step: build/push to ECR |
| IaC | None in 14a (no Terraform/CDK/CloudFormation) |
| External | Supabase Postgres, OpenAI, Pinecone, GitHub (D24) |
| Public URL | `https://api.airepoagent.app` (ACM + Vercel DNS → ALB) |

Region: **`eu-north-1`** (Europe / Stockholm).

---

## Verified working

- ECS Fargate API and worker services running
- ALB healthy; `GET /health` → `200` `{"status":"ok"}` (including via HTTPS hostname)
- API → ElastiCache Redis / ARQ → worker
- Worker → clone → index (OpenAI embeddings + Pinecone) → agent (Responses API)
- Task reaches `completed`; short-poll `GET /tasks/{task_id}` works
- Post–NAT-removal E2E re-verified (public-subnet ECS with public IPs)
- Custom domain + ACM HTTPS for `api.airepoagent.app`

### Successful E2E example

| Field | Value |
| --- | --- |
| Repo | `https://github.com/microsoft/python-sample-vscode-fastapi-tutorial` |
| Instruction | Inspect entry point, API routes, and how the app starts; read-only; summarize with paths |
| `task_id` | `feccdcfc-6635-449d-921b-247f3c0b3d12` |
| Pinecone namespace | `task-feccdcfc-6635-449d-921b-247f3c0b3d12` |
| Outcome | `status: completed`, `error: null` |

Pipeline:

```text
POST /tasks → Redis/ARQ → ECS worker → clone → chunk/index
  → OpenAI embeddings → Pinecone → agent (Responses API)
  → completed → GET /tasks/{task_id}
```

---

## Architecture

```text
                         Internet
                            │
                            ▼
              https://api.airepoagent.app
                     (Vercel DNS CNAME)
                            │
                            ▼
                    Internet Gateway
                            │
                 ┌──────────┴──────────┐
                 │                     │
                 ▼                     ▼
        Public Subnet 1         Public Subnet 2
        eu-north-1a             eu-north-1b
        (ALB ENI + ECS)         (ALB ENI + ECS)
                 │                     │
                 └──────────┬──────────┘
                            │
                            ▼
                 Application Load Balancer
                       ai-agent-alb
                    HTTPS :443 (ACM)
                            │ :8000
                            ▼
              ┌───────────────────────────┐
              │ ECS Fargate — API         │
              │ Public subnets            │
              │ Public IP ENABLED         │
              │ ai-agent-api-sg           │
              └─────────────┬─────────────┘
                            │
                 ┌──────────┴──────────┐
                 ▼                     ▼
          ElastiCache Redis      Supabase PostgreSQL
          :6379 (private)        (external)
                 │
                 │ ARQ
                 ▼
       ┌───────────────────────────┐
       │ ECS Fargate — Worker      │
       │ Public subnets            │
       │ Public IP ENABLED         │
       │ ai-agent-worker-sg        │
       │ (no inbound)              │
       └─────────────┬─────────────┘
                     │
          ┌──────────┼───────────┐
          ▼          ▼           ▼
       GitHub      OpenAI      Pinecone

ECS public subnets → public IPs → Internet Gateway → Internet
(No NAT Gateway — intentionally removed for cost)
```

**Traffic intent (security groups still enforce this):**

```text
Internet → ALB (HTTPS) → API ECS   (not Internet → API directly)
Worker: no unnecessary inbound; outbound for external APIs
Redis: private subnets only
```
---

## AWS resources (as deployed)

### VPC

| Item | Value |
| --- | --- |
| Name | `ai-agent` (confirm tag/name in console if renamed) |
| CIDR | `10.20.0.0/16` |
| Region | `eu-north-1` |
| AZs | `eu-north-1a`, `eu-north-1b` |

Do **not** use the default VPC for this deployment.

| Subnet | CIDR | AZ | Type |
| --- | --- | --- | --- |
| `ai-agent-public-1` | `10.20.1.0/24` | `eu-north-1a` | Public |
| `ai-agent-public-2` | `10.20.2.0/24` | `eu-north-1b` | Public |
| `ai-agent-private-1` | `10.20.11.0/24` | `eu-north-1a` | Private |
| `ai-agent-private-2` | `10.20.12.0/24` | `eu-north-1b` | Private |

- Public route tables: `0.0.0.0/0` → Internet Gateway (resources with public IPv4 can reach the Internet directly)
- **NAT Gateway:** deleted (`ai-agent-nat`). Do **not** recreate unless ECS tasks move back to private subnets that need outbound Internet

**Current placement**

| Tier | Subnets | Resources |
| --- | --- | --- |
| Public | `ai-agent-public-1/2` | ALB, ECS API, ECS worker |
| Private | `ai-agent-private-1/2` | ElastiCache Redis only |

### ECR

- Repository: `ai-agent-platform`
- Tag: `latest`
- One image for API + worker; worker uses a command override

**Preferred:** from the repo root, build, push, and force-redeploy API + worker:

```bash
./infrastructure/aws/docker.sh
```

Manual equivalent (build/push only; still force-redeploy ECS afterward):

```bash
REGION=eu-north-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REPO="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/ai-agent-platform"

aws ecr get-login-password --region "${REGION}" \
  | docker login --username AWS --password-stdin \
      "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

docker build -t ai-agent-platform:latest ./backend
docker tag ai-agent-platform:latest "${REPO}:latest"
docker push "${REPO}:latest"
```

### Secrets Manager

Secret: `ai-agent-platform/app`

| Key | Notes |
| --- | --- |
| `DATABASE_URL` | Supabase; `postgresql+psycopg://…` + `?sslmode=require` |
| `OPENAI_API_KEY` | |
| `PINECONE_API_KEY` | |
| `PINECONE_INDEX` | |
| `REDIS_URL` | `redis://<primary-endpoint>:6379/0` |

Working Redis URL shape:

```text
redis://ai-agent-redis.fberqq.ng.0001.eun1.cache.amazonaws.com:6379/0
```

**Do not** append the port twice (`…:6379:6379/0`). After changing a secret, **force a new ECS deployment** — secrets are injected at container start.

### IAM

| Role | Purpose |
| --- | --- |
| `ai-agent-ecs-task-execution-role` | ECR pull, CloudWatch logs, `secretsmanager:GetSecretValue` |
| Task role | No extra AWS API permissions in 14a |

Execution-role secret resource pattern (suffix wildcard required):

```text
arn:aws:secretsmanager:eu-north-1:<ACCOUNT>:secret:ai-agent-platform/*
```

JSON secret injection example:

```text
arn:aws:secretsmanager:eu-north-1:<ACCOUNT>:secret:ai-agent-platform/app-XXXX:DATABASE_URL::
```

### Security groups

| SG | Inbound |
| --- | --- |
| `ai-agent-alb-sg` | TCP **443** (HTTPS) from the Internet for public demo access; HTTP :80 only if still used for redirect/legacy |
| `ai-agent-api-sg` | TCP 8000 from `ai-agent-alb-sg` (not from `0.0.0.0/0`) |
| `ai-agent-worker-sg` | **None** |
| `ai-agent-redis-sg` | TCP 6379 from `ai-agent-api-sg` and `ai-agent-worker-sg` |

ALB is the only intentionally public entry point. Public IPs on ECS tasks do **not** mean the app port should be open to the Internet — keep API inbound restricted to the ALB SG.

**Auth note:** the API is publicly reachable over HTTPS with **no application authentication** yet (Phase 12). Treat as a demo surface; add auth or tighten ALB access before treating it as multi-tenant.

### ElastiCache Redis

| Setting | Value |
| --- | --- |
| Name | `ai-agent-redis` |
| Engine | Redis OSS |
| Cluster mode | Disabled |
| Node | `cache.t4g.micro`, 0 replicas |
| Port | 6379 |
| Encryption at rest | Enabled |
| Encryption in transit | Disabled (`redis://`, not `rediss://`) |
| Backups | 1 day |
| Subnet group | **private subnets only** (`ai-agent-private-1`, `ai-agent-private-2`) |
| SG | `ai-agent-redis-sg` |

Public subnets were removed from the Redis subnet group. Redis stays a private VPC resource with no direct Internet exposure.

### CloudWatch

| Log group | Contents |
| --- | --- |
| `/ecs/ai-agent-api` | `/health`, `POST /tasks`, poll |
| `/ecs/ai-agent-worker` | ARQ, clone, index, OpenAI, Pinecone, completion |

Frequent `/health` lines are expected (ALB target-group checks).

### ECS

| Item | Value |
| --- | --- |
| Cluster | `ai-agent-cluster` (Fargate) |
| API service | `ai-agent-api-service-2sdqusn9` |
| API task def | `ai-agent-api` (see current revision in console) |
| Worker service | `ai-agent-worker-service` |
| Worker task def | `ai-agent-worker` (see current revision in console) |
| Desired count | 1 each |
| Networking | **Public** subnets; **Assign public IP ENABLED** |
| Size | **0.25 vCPU / 0.5 GB** (both API and worker) |

API: image default CMD (Uvicorn), port 8000.  
Worker: no ALB exposure; no ports required; command:

```json
["uv", "run", "arq", "app.workers.main.WorkerSettings"]
```

**Changing CPU/memory:** create a new task-definition revision → update the service to that revision → wait for deployment → verify tasks and app behavior. A new revision alone does not replace running tasks.

### ALB + target group

| Item | Value |
| --- | --- |
| ALB | `ai-agent-alb`, internet-facing, IPv4, public subnets |
| ALB DNS | `ai-agent-alb-1520727908.eu-north-1.elb.amazonaws.com` |
| HTTPS listener | **:443** → `ai-agent-api-tg`, ACM cert for `api.airepoagent.app` |
| Target group | IP targets, HTTP :8000 |
| Health check | `GET /health`, success `200` |

ALB ENI Elastic IPs (do **not** release while the ALB uses them):

| Public IP | Private IP | Notes |
| --- | --- | --- |
| `13.53.108.139` | `10.20.2.175` | ALB ENI |
| `13.63.94.132` | `10.20.1.44` | ALB ENI |

Preferred public base URL: **`https://api.airepoagent.app`**

```bash
curl https://api.airepoagent.app/health
curl -s -X POST https://api.airepoagent.app/tasks \
  -H 'Content-Type: application/json' \
  -d '{"repository_url":"https://github.com/microsoft/python-sample-vscode-fastapi-tutorial","instruction":"Inspect this repository and identify the main application entry point, the API routes, and how the application is started. Do not modify any files. Summarize your findings with file paths."}'
curl -s https://api.airepoagent.app/tasks/<task_id>
```

Swagger / demo UI: `https://api.airepoagent.app/docs` and `https://api.airepoagent.app/`

### HTTPS, domain, and DNS

| Item | Value |
| --- | --- |
| Domain | `airepoagent.app` (purchased via Vercel; **Vercel DNS** authoritative) |
| Nameservers | `ns1.vercel-dns.com`, `ns2.vercel-dns.com` |
| API hostname | `https://api.airepoagent.app` |
| Future frontend (not deployed) | `https://airepoagent.app` |
| ACM certificate | Public cert for `api.airepoagent.app`, DNS validation, RSA 2048, export disabled, status **ISSUED** |
| Traffic CNAME (Vercel) | `api` → `ai-agent-alb-1520727908.eu-north-1.elb.amazonaws.com` |

**DNS roles (do not confuse them):**

1. **ACM validation CNAME** — proves domain ownership for certificate issue/renewal. Keep it; it does **not** route API traffic.
2. **`api` CNAME** — routes `api.airepoagent.app` to the ALB.

Verified resolution (example):

```text
nslookup api.airepoagent.app 8.8.8.8
→ ai-agent-alb-1520727908.eu-north-1.elb.amazonaws.com
→ 13.63.94.132, 13.53.108.139
```

Vercel is used here for **domain + DNS only**. It does not host the API; the API remains on AWS ECS behind the ALB (D10 / D28).

### Elastic IP inventory

| Public IP | Association | Action |
| --- | --- | --- |
| `13.53.108.139` | ALB ENI | Keep |
| `13.63.94.132` | ALB ENI | Keep |
| `13.51.87.208` | EC2 `i-0db8d25a39405b231` (older project) | Keep unless retiring that instance |
| `16.192.204.128` | Former NAT | **Released** after NAT deletion |
| `51.20.158.244` | Former NAT | **Released** after NAT deletion |

---

## Compose → AWS

| Local | AWS |
| --- | --- |
| `api` | ECS Fargate API + ALB |
| `worker` | ECS Fargate worker |
| `redis` | ElastiCache Redis (private subnets) |
| `backend/.env` | Secrets Manager + task env |
| `localhost:8000` | `https://api.airepoagent.app` (ALB + ACM) |
| Image | ECR |
| Compose network | VPC + security groups (no NAT) |

---

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `/health` OK, `POST /tasks` **503** | `REDIS_URL` shape (`:6379/0` once); force redeploy after secret edit |
| **202** then stuck `pending` | Worker running; same Redis as API; worker logs; ARQ `process_task` |
| Worker can't reach GitHub/OpenAI/Pinecone | Task has public IP; public subnet route → IGW; outbound SG/NACL allowed |
| Target unhealthy | Port 8000; path `/health`; ALB→API SG; API logs |
| Secrets fail | Execution role `GetSecretValue`; ARN + JSON key `::` form; region |
| Worker OOM | Raise Fargate memory (new task-def revision + service update); current baseline is 0.5 GB |
| API reachable without ALB | Tighten `ai-agent-api-sg` — app port must come from `ai-agent-alb-sg` only |
| HTTPS / cert errors | ACM status ISSUED; listener uses cert for `api.airepoagent.app`; keep ACM validation CNAME in Vercel DNS |
| Hostname does not resolve | Vercel `api` CNAME → ALB DNS name; propagation / authoritative NS |

---

## Cost

**Major optimization already applied:** NAT Gateway removed (hourly + data-processing charges). ECS tasks use public IPs via the Internet Gateway instead.

While running, expect charges for: **ALB**, **Fargate × 2** (0.25 vCPU / 0.5 GB each), **ElastiCache**, ECR storage, plus OpenAI/Pinecone usage.

This public-subnet ECS layout is appropriate for a **development/demo** deployment. It is cheaper than private tasks + NAT, with a larger network attack surface — mitigate with security groups as above. Tear down when idle.

---

## Teardown

1. Scale API and worker desired count to **0**, then delete services  
2. Delete ALB, then target group (ALB EIPs go with the ENIs — do not manually release them first)  
3. Delete ECS cluster if unused  
4. Delete ElastiCache Redis  
5. Delete security groups (after dependents)  
6. ECR images/repo optional  
7. Schedule Secrets Manager deletion  
8. CloudWatch log groups optional  
9. Route tables / subnets / VPC if removing the whole stack  
10. Project IAM roles optional  
11. Older EC2 EIP `13.51.87.208` only if that instance is intentionally retired  

NAT Gateway and its EIPs are already gone — skip recreating them during teardown.

---

## Current infrastructure checklist

- [x] VPC + Internet Gateway
- [x] Two public + two private subnets
- [x] ALB across public subnets
- [x] ECS API + worker (public subnets, public IPs enabled)
- [x] Redis private; subnet group = private subnets only
- [x] NAT Gateway deleted; NAT EIPs released
- [x] Fargate API/worker sized to 0.25 vCPU / 0.5 GB
- [x] Application E2E tested after networking changes
- [x] ACM certificate for `api.airepoagent.app` (ISSUED)
- [x] Vercel DNS `api` CNAME → ALB
- [x] Public HTTPS access at `https://api.airepoagent.app`

---

## Phase 14b (next)

14a is the working baseline (including public HTTPS hostname). **14b** hardening (not done):

- GitHub Actions + OIDC → ECR/ECS  
- Tighter IAM; auth / access control for the now-public API (Phase 12 or interim ALB restriction)  
- Documented networking/cost (NAT already removed; revisit private ECS if hardening requires it)  
- Redis encryption in transit  
- Supabase pooler verification (O7)  
- Autoscaling, alarms, rollback, secrets rotation, observability  
- Optional: apex `airepoagent.app` frontend host  

See [roadmap.md](../../docs/roadmap.md).
