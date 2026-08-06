# 06 · TabbyOS — Real Sessions, Human Hands, Zero Credential Theft

## Thesis

AI agents need authenticated browser sessions to do real work. OAuth flows, OTPs, CAPTCHAs, and MFA challenge prompts break pure automation on the spot. Every agent-driven web workflow — payroll, banking, booking, Salesforce, admin consoles — dies against a login wall the agent was never given keys to.

**TabbyOS is the Kubernetes-native service stack that gives agents persistent authenticated browser sessions, routes every "I need a human" moment (MFA, CAPTCHA, credential challenge) to a live operator, and treats the credential lifecycle as a security product — never as a stolen-ph database.** It builds on shipped production code (the `tabby` repo) and turns the boundary between automation and human intervention into an API.

## Why it matters

- **The agent boundary is real.** No agent automation is complete until it can log in, and no security team will let an agent hold production credentials. The human-in-the-loop for auth is not a workaround — it is the *design*.
- **The market is filled with brittle scrapers and worse.** The answer is a designed system: authenticated sessions + HITL at the credential moment + structured, decrypted credential retrieval *from a live session, not a vault of passwords*.
- **It is the natural partner of GateOS (01).** Credential+re-auth is exactly the ambiguity class a review queue should take — a human unblocks in seconds; the agent resumes.

## The core concept

**Return credentials from the live session, not from storage.** When an agent requests credentials for the service, the system *either* returns cached credentials from a live authenticated browser session *or* orchestrates a fresh login — OTP relay, CAPTCHA solve, credential entry by an operator — and returns the freshly-derived, structured, decrypted credentials. The session is the source of truth; no password file exists in the data path.

**Tenant-isolated, replay-safe.** Sessions are per-job, per-tenant; browser workers run in Kubernetes; the intervention queue is a real product surface (the same escalation philosophy as 01 GateOS's human queue).

**Kubernetes-native service stack** — Admin UI, API, Slack/Teams bots (NATS pub/sub), Playwright worker pools with live-VNC/stream handoff; Helm chart etc.

## What gets built

1. **Session orchestration service** — allocates workers, orchestrates login/interaction, manages session lifecycle (based on the Tabby codebase).
2. **HITL relay** — Slack + Teams bots + live stream integration; every challenge event gets a structured prompt, an answer, and a response back down the NATS wire back to the worker.
3. **Credential semantic layer** — a typed interface for "enter these credentials for Salesforce / banking / external tool" with decryption at the moment of use; rotation policy.
4. **Security boundary** — secrets out of memory, out of logs, out of the agent context, vault outside the data path; full audit trail coupling with 01 decision log and 08 replay.
5. **Policy integration** — *which* sessions are allowed to do *what* (kill switch per tenant, allowed-host list, session timeouts, quarantine after anomaly).

## Architecture sketch

```
agent request ── "I need to act as X on <web service>"
                    │
                    ▼
              Authorization API
          (policy: site allow-list, tenant, lockdown)
                    │
        ┌───────────┼────────────────┐
        ▼           ▼                ▼
   [cached session]  [fresh login]     [DENY / escalate]
        ▲             │                   ▲
        │        Playwright worker   human operator
        │        (Kube pod)             │ (Slack/Teams/VNC)
        │             │  MFA/OTP/CAPTCHA challenge
        │             └─────►  BOT relay  ◄───────┘
        └────── decrypted creds ──────┘
                    │
              agent continues work
              (decision logged, 01)
```

## Research / engineering program

- **R1: Challenge taxonomy + classifier.** A taxonomy of the sustained "human moment" (OAuth, OTP-only, CAPTCHA, re-auth, rate-limit wall, "accountlock"). A classifier that routes each to *bot* (mock), *human* (escalation), or *new session*. Knows the boundary because we encode it.
- **R2: Rotation & trust decay.** How long do live sessions stay valid across the target sites? What's the trust decay curve, the re-auth trigger — so credential of a "stale session" can't be returned?
- **R3: Session reuse vs. healing.** When a session breaks (logout, session injection, TOFU changes), is self-heal or human re-auth the right default? Compare heal-in-place vs restart worker.
- **R4: Site-policy as code.** The allow-list / SOP (Standard Operating Procedure) interpreter: How must sessions behave per site (timeouts, stealth, one-session-per-tenant)? Security boundary between *agent ability* and *site reality*.

## Prior work it builds on

- The **`tabby`** repo: browser HITL, Kubernetes Playwright workers, Slack/Teams bots, NATS pub/sub, Helm chart, credential relay — this spec is the productization/open-source of that.
- Adopt AI HITL design: signal-driven state machine, optimistic locking, tenant isolation, 3-action resolution — direct transfer.
- 01 GateOS (escalation queue philosophy), 08 Replay (audit/replay for what an agent did in a session).

## Risks / failure modes

- **The security surface is real.** A system that holds live sessions is a higher-value target; the *credential* has to be designed so the session IS a live ephemeral capability, not a stored secret for reuse beyond its session.
- **Platform ToS** — automating real-site auth violates user agreements. This is a stance + risk. Handle: the human operator is the *one who actually* interacts with the UI for the auth part; the agent only needs the result.
- **Session leakage across tenants.** The tenant-isolation architecture must be bulletproof; the worst case is an agent of tenant A seeing tenant B's session (audit + PKI boundaries must be designed, not afterthought).
- **No classic keys to test against** — security gain is a monitoring/audit, not a "it's safe" badge.

## Success (definition)

- An agent (running on the GateOS substrate) lands a real workflow end-to-end that required a live human login — booking, bank reconciliation, Salesforce — with the human only touched at the login boundary.
- Sessions are tied: challenge participation capped, tenant-isolated, audited in 08's replayable log.
- Security agreement: rotation/decay limits >0 enforced, no secrets written to the agent context, no session re-use beyond policy.