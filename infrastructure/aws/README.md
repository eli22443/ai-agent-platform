# AWS minimal deploy (Deploy Track / 14a)

Console-first record of the first cloud deployment. Product guide: [docs/deploy-track.md](../../docs/deploy-track.md).

**Status: 14a complete** — deployed and end-to-end tested successfully.

| Approach | Detail |
| --- | --- |
| Infrastructure | AWS Console |
| Image publish | One CLI step: build/push to ECR |
| IaC | None in 14a (no Terraform/CDK/CloudFormation) |
| External | Supabase Postgres, OpenAI, Pinecone, GitHub (D24) |

Region: **`eu-north-1`**.

---

## Verified working

- ECS Fargate API and worker services running
- ALB healthy; `GET /health` → `200` `{"status":"ok"}`
- API → ElastiCache Redis / ARQ → worker
- Worker → clone → index (OpenAI embeddings + Pinecone) → agent (Responses API)
- Task reaches `completed`; short-poll `GET /tasks/{task_id}` works

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
                 ┌─────────────────────┐
                 │ ALB (public subnets)│
                 │ HTTP :80            │
                 │ ai-agent-alb-sg     │
                 └──────────┬──────────┘
                            │ :8000
                            ▼
              ┌───────────────────────────┐
              │ ECS Fargate — API         │
              │ Private subnets           │
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
       │ Private subnets           │
       │ ai-agent-worker-sg        │
       │ (no inbound)              │
       └─────────────┬─────────────┘
                     │
          ┌──────────┼───────────┐
          ▼          ▼           ▼
       GitHub      OpenAI      Pinecone

Private ECS subnets → Regional NAT Gateway → Internet
(ECS tasks have Public IP OFF)
```

---

## AWS resources (as deployed)

### VPC

| Item | Value |
| --- | --- |
| Name | `ai-agent-vpc` |
| CIDR | `10.20.0.0/16` |
| Region | `eu-north-1` |

Do **not** use the default VPC for this deployment.

| Subnet | CIDR | AZ | Type |
| --- | --- | --- | --- |
| `public-1` | `10.20.1.0/24` | `eu-north-1a` | Public |
| `public-2` | `10.20.2.0/24` | `eu-north-1b` | Public |
| `private-1` | `10.20.11.0/24` | `eu-north-1a` | Private |
| `private-2` | `10.20.12.0/24` | `eu-north-1b` | Private |

- Public route table: `ai-agent-public-rt`
- Private route table: `ai-agent-private-rt` → `0.0.0.0/0` via NAT
- NAT Gateway: `ai-agent-nat` (public connectivity, EIP auto-allocated)

Private tasks reach OpenAI, Pinecone, GitHub, and Supabase via NAT **without** public IPs on the tasks.

### ECR

- Repository: `ai-agent-platform`
- Tag: `latest`
- One image for API + worker; worker uses a command override

```bash
REGION=eu-north-1
ACCOUNT=<ACCOUNT>
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
| `ai-agent-alb-sg` | TCP 80 from **your IP** only (not `0.0.0.0/0`) |
| `ai-agent-api-sg` | TCP 8000 from `ai-agent-alb-sg` |
| `ai-agent-worker-sg` | **None** |
| `ai-agent-redis-sg` | TCP 6379 from `ai-agent-api-sg` and `ai-agent-worker-sg` |

ALB is the only publicly exposed AWS component.

### ElastiCache Redis

| Setting | Value |
| --- | --- |
| Engine | Redis OSS |
| Cluster mode | Disabled |
| Node | `cache.t4g.micro`, 0 replicas |
| Port | 6379 |
| Encryption at rest | Enabled |
| Encryption in transit | Disabled (`redis://`, not `rediss://`) |
| Backups | 1 day |
| Subnet group | `ai-agent-redis` |
| SG | `ai-agent-redis-sg` |

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
| API task def | `ai-agent-api:1` |
| Worker service | `ai-agent-worker-service` |
| Worker task def | `ai-agent-worker:1` |
| Desired count | 1 each |
| Networking | Private subnets; **Public IP OFF** |
| Size | **0.5 vCPU / 1 GB** (both) |

API: image default CMD (Uvicorn), port 8000.  
Worker: no ports; command:

```json
["uv", "run", "arq", "app.workers.main.WorkerSettings"]
```

### ALB + target group

| Item | Value |
| --- | --- |
| ALB | `ai-agent-alb`, internet-facing, IPv4, public subnets |
| Listener | HTTP :80 → `ai-agent-api-tg` |
| Target group | IP targets, HTTP :8000 |
| Health check | `GET /health`, success `200` |

```bash
curl http://<ALB-DNS>/health
curl -s -X POST http://<ALB-DNS>/tasks \
  -H 'Content-Type: application/json' \
  -d '{"repository_url":"https://github.com/microsoft/python-sample-vscode-fastapi-tutorial","instruction":"Inspect this repository and identify the main application entry point, the API routes, and how the application is started. Do not modify any files. Summarize your findings with file paths."}'
curl -s http://<ALB-DNS>/tasks/<task_id>
```

Swagger: `http://<ALB-DNS>/docs`

---

## Compose → AWS

| Local | AWS |
| --- | --- |
| `api` | ECS Fargate API + ALB |
| `worker` | ECS Fargate worker |
| `redis` | ElastiCache Redis |
| `backend/.env` | Secrets Manager + task env |
| `localhost:8000` | ALB DNS |
| Image | ECR |
| Compose network | VPC + security groups + NAT |

---

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `/health` OK, `POST /tasks` **503** | `REDIS_URL` shape (`:6379/0` once); force redeploy after secret edit |
| **202** then stuck `pending` | Worker running; same Redis as API; worker logs; ARQ `process_task` |
| Worker can't reach GitHub/OpenAI/Pinecone | Private RT → NAT; NAT available; outbound allowed |
| Target unhealthy | Port 8000; path `/health`; ALB→API SG; API logs |
| Secrets fail | Execution role `GetSecretValue`; ARN + JSON key `::` form; region |
| Worker OOM | Raise Fargate memory above 1 GB |

---

## Cost

While running, expect charges for: **ALB**, **Fargate × 2**, **ElastiCache**, **NAT Gateway** (often material), ECR storage, plus OpenAI/Pinecone usage.

Private subnets + NAT are more secure than public-IP tasks, but **not** the cheapest demo layout. Tear down when idle.

---

## Teardown

1. Scale API and worker desired count to **0**, then delete services  
2. Delete ALB, then target group  
3. Delete ECS cluster if unused  
4. Delete ElastiCache Redis  
5. Delete NAT Gateway; release EIP if unused  
6. Delete security groups (after dependents)  
7. ECR images/repo optional  
8. Schedule Secrets Manager deletion  
9. CloudWatch log groups optional  
10. Route tables / subnets / VPC if removing the whole stack  
11. Project IAM roles optional  

---

## Phase 14b (next)

14a is the working baseline. **14b** hardening (not done):

- GitHub Actions + OIDC → ECR/ECS  
- Tighter IAM; HTTPS/ACM; ALB access control  
- NAT cost options; Redis encryption in transit  
- Supabase pooler verification (O7)  
- Autoscaling, alarms, rollback, secrets rotation, observability  

See [roadmap.md](../../docs/roadmap.md).
