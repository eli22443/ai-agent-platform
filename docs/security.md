# Security

## Status

Living document. Controls are designed ahead of implementation and updated when exposure changes. Implemented through Phase 5: configuration hygiene, repository URL/SSRF validation and clone limits (Phase 4), and workspace path confinement for tools (Phase 5). Prompt-injection mitigations and further controls remain scheduled in the "Introduced" column; Phase 6 adds the agent loop that consumes repository text as untrusted data.

## Central premise

A repository supplied by a user is untrusted input in two distinct ways, and conflating them is the most common way to get this class of system wrong.

1. **As code.** Repository contents may be malicious. Executing tests means executing arbitrary code written by someone else.
2. **As text.** Repository contents enter the model's context. A file can contain text crafted to look like instructions to an AI agent.

The platform must be safe under the assumption that both are hostile simultaneously.

A third premise follows from the architecture: the model is not a trusted component. It produces tool calls and arguments, and those arguments are attacker-influenceable whenever repository content is in context. Every tool validates its own inputs regardless of the fact that a model produced them.

## Threat model

### Malicious repository code execution

Executing repository code on the application host would expose the filesystem, environment variables including API keys, the database connection, cloud instance credentials, and the internal network.

Controls: all execution of repository code happens inside a Docker sandbox with no application secrets present in its environment. No unrestricted host shell is exposed to the agent at any phase. Until the sandbox exists in Phase 10, no tool executes repository code at all, which is why `run_tests` is a Phase 10 tool and not a Phase 5 convenience.

Sandbox requirements: CPU and memory limits, execution timeout, filesystem isolation with only the workspace mounted, restricted or disabled networking, a non-root user, no privileged containers, no Docker socket mount, read-only root filesystem where practical, and guaranteed cleanup of containers and volumes.

Introduced: Phase 10.

### Server-side request forgery through the repository URL

The repository URL is user-supplied and is handed to a network client. Without validation it can be pointed at cloud instance metadata endpoints, internal services, or local addresses.

Controls: accept only `https://` and, if needed, `git://` from an allow-list of known hosts; reject `file://`, `ssh://`, and scp-style syntax; resolve the hostname and reject private, loopback, link-local, and unique-local address ranges, including the cloud metadata address; re-check after DNS resolution to reduce rebinding exposure; disable redirect following to unvalidated hosts; and apply a clone timeout and size cap. Validation lives in the repository service so there is exactly one entry point to audit.

Introduced: Phase 4, hardened in Phase 15.

### Prompt injection from repository content

A file such as a README or a source comment can contain text addressed to an AI agent. The realistic goals of such an injection are to make the agent exfiltrate data, call a mutating tool, or produce a misleading answer.

Controls, in order of actual effectiveness:

1. Capability restriction. An injection can only cause damage through tools the run was granted. Read-only runs cannot write, and no run can reach outside its workspace. This is the real defense.
2. Content framing. Repository content is inserted into the context as clearly delimited data, never as instructions.
3. System prompt instruction to treat repository text as data. Useful, but a mitigation rather than a boundary; it is not relied upon.
4. Egress restriction in the sandbox, so an injection that does reach a command cannot post data outward.
5. Run inspection. Every tool call is recorded, so anomalous behavior is visible after the fact.

The platform does not assume prompt injection can be prevented. It assumes it will succeed occasionally and limits what a successful injection can reach.

Introduced: Phase 5 onward, with egress control in Phase 10.

### Path traversal and workspace escape

Every tool that accepts a path receives it from the model, and the model may be influenced by repository content. A path such as `../../.env` or an absolute path targets application secrets.

Controls: resolve the path against the task's workspace root, fully resolve symlinks, and verify the result is still inside the root before any I/O; reject absolute paths and parent-directory traversal outright rather than normalizing them away; refuse to follow symlinks that point outside the workspace, since a cloned repository can contain them; and centralize this check in one helper that every tool uses, because a per-tool reimplementation is where this bug appears.

Introduced: Phase 5.

### Secret exposure

Secrets can leak into logs, into the model's context, into database records, into API responses, and into the sandbox environment.

Controls: secrets come from environment variables only and are never committed, with `.env` git-ignored and a `.env.example` carrying names but no values; the sandbox receives an explicit minimal environment with no platform credentials; no credential is ever written to a database record; logs redact known secret patterns and never log full request bodies containing credentials; error responses expose a correlation identifier rather than internal detail; and repository content that appears to contain credentials is not echoed back verbatim in results.

Introduced: Phase 1 for configuration hygiene, extended each phase that adds a credential.

### Resource exhaustion

A large or hostile repository can exhaust disk, and an unbounded agent run can exhaust budget.

Controls: clone depth and size limits with a timeout; per-task disk quota; workspace cleanup on completion and a sweeper for abandoned workspaces; agent iteration, wall-clock, and token limits as described in [agent-design.md](agent-design.md); tool output truncation; and sandbox CPU, memory, process, and time limits.

Cost is a security property here, not merely an operational one: an attacker who can trigger unbounded agent runs against a paid API has found a financial denial-of-service.

Introduced: Phase 4 for disk, Phase 6 for run limits, Phase 10 for execution limits, Phase 15 for quotas.

### Unauthenticated exposure

The initial platform has no authentication by design. Anything reachable can be invoked by anyone who can reach it.

Controls: keep the deployment private until Phase 15 hardening; if exposed, apply IP-based rate limiting and a global concurrency cap on agent runs; accept only public repositories; and expose no endpoint that reveals another caller's task content. Authentication in Phase 12 replaces this posture rather than supplementing it.

Introduced: Phase 15, or earlier if the API is exposed.

### Supply chain execution during dependency installation

Installing a repository's dependencies executes third-party code, and package build scripts run arbitrary commands. This is a distinct risk from running the repository's own code because it pulls in code from the network.

Controls: install only inside the sandbox, never on the host or in the application image; treat installation as untrusted execution with the same limits; and restrict network egress to the package registry when installation is required at all.

Introduced: Phase 10.

### Unintended repository modification

Once the agent can write files, a bad run can damage a user's work.

Controls: all modification happens in the platform's own isolated clone, never in a user-owned checkout; changes are never pushed automatically; the result of a modification run is a reviewable diff that the user inspects before anything is applied upstream; and write tools remain outside the granted tool set for analysis-only runs.

Introduced: Phase 11.

### Authorization gaps once multi-user

Adding user accounts without per-resource authorization checks creates direct object reference vulnerabilities across tasks and repositories.

Controls: every user-owned resource carries an owner column and every read and write path filters on the authenticated principal; authorization is enforced in the service layer rather than in individual routes; JWT verification uses the provider's published keys with signature, issuer, audience, and expiry all checked; and per-user quotas are enforced. Custom password authentication is not implemented under any circumstances.

Introduced: Phase 12.

## Control summary

| Control | Introduced |
| --- | --- |
| Secrets from environment only, `.env` git-ignored | Phase 1 |
| Repository URL validation and SSRF protection | Phase 4 |
| Clone size, depth, and timeout limits | Phase 4 |
| Workspace path confinement for all file tools | Phase 5 |
| Tool input validation and output truncation | Phase 5 |
| Agent iteration, wall-clock, and token limits | Phase 6 |
| Full tool-call audit trail | Phase 7 |
| Docker sandbox with resource and network limits | Phase 10 |
| Read-only versus mutating tool separation enforced | Phase 11 |
| No automatic push to user repositories | Phase 11 |
| Authentication, authorization, and per-user quotas | Phase 12 |
| Secret redaction in structured logs and traces | Phase 13 |
| Secrets from AWS Secrets Manager or Parameter Store | Phase 14 |
| Rate limiting, idempotency, workspace sweeper, cost controls | Phase 15 |

## Deployment security

For Phase 14 on AWS: no long-lived credentials in the application, using task roles instead; GitHub Actions authenticating through OIDC rather than stored access keys; secrets from Secrets Manager or Parameter Store injected at runtime; containers running as a non-root user; the database reachable only from the application security group; and CloudWatch retaining logs with redaction applied at the source.

## Known accepted risks

| Risk | Rationale | Revisit |
| --- | --- | --- |
| No authentication in the initial platform | Single-user demonstration; not publicly exposed | Phase 12, or immediately on public exposure |
| Public repositories only | Avoids handling third-party repository credentials before authorization exists | Phase 12 |
| Prompt injection cannot be fully prevented | Mitigated by capability restriction rather than eliminated | Continuous |
| Docker unavailable in the current WSL environment | Blocks Phase 10; Phases 1 through 9 are unaffected | Before Phase 10 |

The last row is the one to watch. Because `run_tests` and `run_command` require the sandbox, and Phase 11 code modification requires `run_tests`, the absence of Docker gates the second half of the roadmap. The correct response is to resolve the environment before Phase 10, not to substitute host execution. An interim local executor would not be an isolation boundary, and shipping one under the name "sandbox" would be worse than having no sandbox at all, because it would imply a guarantee that does not exist.
