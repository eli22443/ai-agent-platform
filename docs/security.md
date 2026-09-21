# Security

Living threat model. **Not** a claim of production hardening — the public demo has **no app auth**.

**Implemented (1–9 + 14a):** secrets hygiene; URL/SSRF + clone limits; path/symlink confinement; tool + agent limits; untrusted framing in prompts; `agent_runs` / `tool_calls` audit; HTTPS demo on AWS.

## Implemented vs planned

| Control | Status | Where |
| --- | --- | --- |
| Secrets from env / Secrets Manager | Yes | `.env` ignored; SM in 14a |
| URL allow-list / SSRF | Yes | `url_validation.py` |
| Clone size / depth / timeout | Yes | repository service |
| Path confinement + symlink refuse | Yes | `tools/paths.py` |
| Tool validation / output caps | Yes | tool layer |
| Agent iteration / time / token limits | Yes | `agent/limits.py` |
| Tool-call audit trail | Yes | DB |
| Prompt injection → capability limits | Partial | read-only tools |
| Docker sandbox | No | Phase 10 |
| Auth / authz | No | Phase 12 |
| Log redaction / OTel | No | Phase 13 |
| OIDC CI + IAM harden | No | Phase 14b |
| Rate limits / quotas | No | Phase 15 |

## Premises

1. Repo is hostile **as code** and **as text** (prompt injection).
2. The model is not trusted — every tool validates its own args.

## Threats (compact)

| Threat | Controls | Phase |
| --- | --- | --- |
| Host code exec | No exec tools until Docker sandbox (CPU/mem/net/timeout, no secrets) | 10 |
| SSRF via clone URL | `https` + host allow-list; reject private/loopback/metadata; timeout/size | 4 |
| Prompt injection | Capability restriction (primary); data framing; audit; sandbox egress later | 5+ / 10 |
| Path escape | Resolve under workspace; reject `..` / absolute; refuse escaping symlinks | 5 |
| Secret leak | Env/SM only; never in git/DB; correlation IDs in errors | 1+ |
| Resource / cost DoS | Clone + agent limits; quotas later | 4, 6, 15 |
| Unauthenticated API | Public demo accepted (D28); rate limits / auth later | 12 / 15 |
| Dep install / supply chain | Only inside sandbox | 10 |
| Unwanted git push | Isolated clone; reviewable diff; no auto-push | 11 |
| IDOR when multi-user | Owner column + service-layer checks | 12 |

## Cloud demo posture (14a)

| Item | Posture |
| --- | --- |
| URL | `https://api.airepoagent.app` — no app auth |
| TLS | ALB + ACM |
| ECS | Public subnets OK for egress; **API port only from ALB SG** |
| Worker | No inbound; outbound to Redis/DB/APIs/GitHub |
| Redis | Private; 6379 from API/worker SGs only |
| Supabase | TLS; creds in Secrets Manager |
| Audit | `agent_runs` / `tool_calls` |

Treat as a **public demo**, not multi-tenant. Checklist: [deploy-track.md](deploy-track.md); inventory: [aws README](../infrastructure/aws/README.md).

## Accepted risks

| Risk | Revisit |
| --- | --- |
| No auth on public HTTPS | Phase 12 / ALB restrict |
| Public repos only | Phase 12 |
| Prompt injection not fully preventable | Continuous (capability limits) |
| No local Docker → Phase 10 blocked | Before sandbox work |

Do **not** fake a sandbox with host execution.
