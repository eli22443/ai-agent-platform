# EC2 demo host (compose + Cloudflare Tunnel)

On-demand **t4g.small** in `eu-north-1` running the same Docker Compose stack as local, with Cloudflare Tunnel for HTTPS. Instance is **stopped by default**; start it for demos.

| | |
| --- | --- |
| **Live demo URL** | `https://api.airepo.app` |
| **Health** | `https://api.airepo.app/health` |
| **Region / VPC** | `eu-north-1` / `ai-agent-vpc` / `ai-agent-public-1` |
| **Instance Name tag** | `ai-agent-demo` |
| **Secret** | `ai-agent-platform/app` (includes `CLOUDFLARE_TUNNEL_TOKEN`) |
| **Access** | AWS SSM Session Manager only (no SSH, no inbound SG rules) |

ECS / portfolio hostname (`https://api.airepoagent.app`) is documented under [`infrastructure/aws/`](../aws/README.md). Do not move that name onto this tunnel.

---

## DNS split

Two front doors on purpose:

| Hostname | Zone / DNS | Backend | Role |
| --- | --- | --- | --- |
| **`api.airepo.app`** | Cloudflare zone `airepo.app` → Tunnel | This EC2 compose stack | **Live demos** |
| **`api.airepoagent.app`** | Vercel DNS → ALB (ACM) | ECS Fargate (while it exists) | Deploy-track / ECS resume path |

Leave `airepoagent.app` on Vercel. After ECS teardown the Vercel CNAME can stay pointing at a gone ALB (it will 5xx until you rebuild); that preserves the resume path without touching demo DNS.

---

## Architecture

```text
  Demo browser
       │
       ▼
  Cloudflare edge TLS  (api.airepo.app)
       │  tunnel
       ▼
  cloudflared  ──http://api:8000──►  api ──► redis
                                      │
                                   worker ──► redis
                                      │
                                      ▼
                    Supabase / OpenAI / Pinecone / GitHub

  Laptop: start.sh / stop.sh / deploy.sh  ──SSM + EC2 API──►  instance
```

Compose files on the host:

```bash
docker compose -f docker-compose.yml -f docker-compose.ec2.yml \
  --env-file backend/.env up -d --build
```

The EC2 override publishes **no host ports**; the tunnel reaches the API on the compose network. `ports: !reset []` needs a current Compose V2 plugin (installed by `user-data.sh`, not the distro RPM alone).

`ai-agent.service` on boot: render `.env` from Secrets Manager → `compose up -d --build`. On stop: `compose down`. That is why `./start.sh` alone is enough after provision.

---

## Cost (eu-north-1 list, Nov 2026)

Unit prices used in the plan:

| Item | Price |
| --- | --- |
| `t4g.small` | $0.0172/hr (~$12.56/mo always on) |
| `t4g.micro` (optional later downsize) | $0.0086/hr |
| Public IPv4 (in-use, no EIP) | $0.005/hr (**$0 while stopped**) |
| EBS gp3 20 GB | ~$1.67/mo always |
| Secrets Manager (1 secret) | $0.40/mo always |
| Cloudflare Tunnel | $0 on Free/Hobby DNS |
| VPC / subnets / IGW / SGs | **$0** (custom VPC is not a surcharge vs default) |

Hourly while **running** (compute + public IPv4): small **$0.0222/hr**, micro **$0.0136/hr**.

Monthly **floor while stopped** (EBS + secret): **~$2.07/mo**.

| Demo pattern | Hours on / mo | **t4g.small** | t4g.micro |
| --- | ---: | ---: | ---: |
| Stopped most of the month | 0 | **~$2.07** | ~$2.07 |
| Light (≈2 demos × 2h) | 10 | **~$2.29** | ~$2.21 |
| Typical (≈2h × 20 weekdays) | 40 | **~$2.96** | ~$2.61 |
| Heavy (09–18 weekdays) | 180 | **~$6.07** | ~$4.52 |
| Always on | 730 | **~$18.28** | ~$12.00 |

Practical average with start/stop and ~20–40 demo hours/month on **t4g.small**: about **$3/mo**. OpenAI / Pinecone / Supabase are not included.

---

## One-time Cloudflare setup

Already done for this project; kept here if you recreate the tunnel.

1. In Cloudflare zone **`airepo.app`**, create a **remotely managed** tunnel.
2. Public hostname **`api.airepo.app`** → service `http://api:8000` (compose service name `api`, port 8000).
3. Put the tunnel token in Secrets Manager secret `ai-agent-platform/app` as JSON key **`CLOUDFLARE_TUNNEL_TOKEN`** (alongside the usual backend env keys).
4. Optional: if the GitHub repo is private, also store a read-only **`GITHUB_TOKEN`** in the same secret (used only for `git clone` / `git pull` on the host; stripped from container `.env`).

Do **not** point `api.airepoagent.app` at this tunnel.

---

## Prerequisites (laptop)

- AWS CLI credentials for account `099357569747`, region `eu-north-1`
- `python3`, `curl`
- Repo contents for first boot: **`master` on GitHub must already include** `docker-compose.ec2.yml` and `infrastructure/ec2/` (user-data clones the remote; unpushed local files are invisible to the instance)

---

## Provision (once)

```bash
./infrastructure/ec2/provision.sh
# or, if you will watch logs yourself:
./infrastructure/ec2/provision.sh --no-wait
```

Creates (idempotent for SG/IAM; refuses a second instance):

- Security group `ai-agent-demo-sg` — **no inbound**, all outbound
- IAM role / instance profile `ai-agent-demo-ec2-role` — `AmazonSSMManagedInstanceCore` + `secretsmanager:GetSecretValue` on `arn:aws:secretsmanager:eu-north-1:099357569747:secret:ai-agent-platform/*`
- AL2023 arm64 `t4g.small`, 20 GB gp3, IMDSv2, public IP for egress (no NAT, no EIP)
- First boot: Docker + current Compose/buildx plugins, clone to `/opt/ai-agent-platform`, install `ai-agent.service`, first `compose up --build`

First boot builds the image on the instance (several minutes). Default wait polls `HEALTH_URL` for up to `WAIT_TIMEOUT_SECONDS` (20 min).

---

## Daily demo flow

```bash
./infrastructure/ec2/start.sh    # start instance → wait for /health
# … demo against https://api.airepo.app …
./infrastructure/ec2/stop.sh     # stop instance (compose down via systemd)
./infrastructure/ec2/status.sh   # state, public IP, health
```

While stopped you pay only EBS + the secret (~$2/mo). Public IPv4 charges stop with the instance.

---

## Deploy (manual, via SSM)

Instance must be **running**:

```bash
./infrastructure/ec2/start.sh    # if needed
./infrastructure/ec2/deploy.sh
```

On the host: `git pull` of `REPO_BRANCH` → refresh host helpers/unit → render `.env` from the secret → `compose up -d --build` → prune dangling images → laptop waits for health.

There is no ECS deploy job for this path; keep CI tests only (see plan todo `cicd`).

---

## Troubleshooting

### Session Manager shell

```bash
aws ssm start-session --region eu-north-1 \
  --target "$(./infrastructure/ec2/status.sh >/dev/null; \
    aws ec2 describe-instances --region eu-north-1 \
      --filters Name=tag:Name,Values=ai-agent-demo \
                Name=instance-state-name,Values=running \
      --query 'Reservations[0].Instances[0].InstanceId' --output text)"
```

Or copy the instance id from `./infrastructure/ec2/status.sh` and:

```bash
aws ssm start-session --region eu-north-1 --target i-...
```

### Useful on-instance commands

```bash
# First-boot log
sudo journalctl -u cloud-final -n 100   # or:
sudo tail -n 200 /var/log/ai-agent-user-data.log

# App unit
sudo systemctl status ai-agent.service
sudo journalctl -u ai-agent.service -n 100

# Compose (wrapper uses both compose files + backend/.env)
ai-agent-compose ps
ai-agent-compose logs -f api
ai-agent-compose logs -f cloudflared
ai-agent-compose logs -f worker

# Re-render env after secret edits (then restart stack)
ai-agent-render-env
sudo systemctl restart ai-agent.service
```

### Common failures

| Symptom | Likely cause |
| --- | --- |
| `provision.sh` / health never OK | Repo on GitHub missing `docker-compose.ec2.yml` / `infrastructure/ec2/`; check user-data log |
| Tunnel 502 / health fail, compose up | Missing or wrong `CLOUDFLARE_TUNNEL_TOKEN`; Cloudflare public hostname not `http://api:8000` |
| `deploy.sh` refuses | Instance stopped — run `start.sh` first |
| SSM “not Online” | Wait a minute after boot; IAM profile / SSM agent |
| OOM during first build | user-data adds 2 GB swap; still tight on small — retry or temporarily use a larger type |

---

## Caveats

- **In-flight ARQ jobs are lost on stop** (same as stopping ECS/Redis today). Finish demos before `stop.sh`.
- Image is **built on the instance** (no ECR required for demos). First boot and each deploy that changes the Dockerfile are slow.
- Public IP changes every start; that is fine — clients use the tunnel hostname, not the IP.
- Security group has no inbound rules; do not add SSH “for convenience.”
- Optional cost downsize later: set `INSTANCE_TYPE=t4g.micro` in `config.env` and replace the instance (micro was skipped for the first cut to keep builds comfortable).

---

## Resume ECS later

EC2 demos keep using **`api.airepo.app`** independently.

To bring back the portfolio/deploy-track URL:

1. Recreate ALB (+ ACM cert if needed) and ECS services as in [`infrastructure/aws/README.md`](../aws/README.md).
2. Point the existing Vercel DNS `api` CNAME for **`api.airepoagent.app`** at the new ALB.
3. Do not migrate that hostname onto Cloudflare Tunnel unless you intentionally retire the ECS resume path.

Keep VPC/public subnets/IGW and the Secrets Manager secret when tearing down ECS; those are shared with this demo host.
