# Neural Ledger — Threat Model & Key Management

**Document version:** 1.0
**Date:** 28 April 2026
**Owner:** Backend / Security
**Phase:** 0 — Foundations

---

## 1. Purpose

This document captures the **security boundaries**, **trust assumptions**, and
**key-management strategy** for Neural Ledger. The product handles sensitive
financial data (transactions, account balances, vendor relationships) for
Pakistani SMEs, so confidentiality and integrity are non-negotiable.

---

## 2. Assets to Protect

| # | Asset | Sensitivity | Where it lives |
|---|---|---|---|
| A1 | User credentials (email + password) | High | `users.password_hash` (bcrypt) |
| A2 | Raw transaction line-items | **Critical** | Local agent → encrypted payload → S3 |
| A3 | Aggregated financial summaries (P&L, cash flow) | High | PostgreSQL, encrypted at rest |
| A4 | JWT signing key | Critical | KMS / `JWT_SECRET_KEY` env var |
| A5 | Per-org AES-256 data keys | Critical | KMS-wrapped DEKs |
| A6 | OpenAI API key | High | Vault / env var only |
| A7 | Audit log entries | Medium | append-only Postgres table |

---

## 3. Trust Boundaries

```
┌──────────────────────┐
│   SME's Computer     │   ← Untrusted edge: malware, multi-user, lost laptop
│   (Local Agent)      │
└──────────┬───────────┘
           │  TLS 1.3 + per-org AES-256
           ▼
┌──────────────────────┐
│   FastAPI Cloud      │   ← Trusted: VPC, IAM-controlled
│   (Ingestion + DB)   │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│   OpenAI API         │   ← Semi-trusted: only summaries, never raw rows
│   (Agent SDK)        │
└──────────────────────┘
```

**Boundary rules:**
1. **Raw transaction text never leaves the SME's machine unencrypted.**
2. The cloud **only ever sees AES-256-GCM ciphertext** until it decrypts in-memory for processing.
3. **OpenAI never receives raw rows** — only aggregated summaries with tx-id citations.

---

## 4. Threat Catalogue (STRIDE)

| Threat | Vector | Mitigation |
|---|---|---|
| **S — Spoofing** | Stolen JWT replay | Short-lived access tokens (30 min) + refresh rotation |
| **S — Spoofing** | Local agent impersonation | Per-install API key + org binding on first run |
| **T — Tampering** | MITM on payload | TLS 1.3 only; HSTS; cert pinning in agent |
| **T — Tampering** | DB row modification | Audit log + row-level integrity hashes (Phase 6) |
| **R — Repudiation** | "I didn't make that transaction" | Append-only `audit_log` table with user_id + tx_id |
| **I — Info Disclosure** | DB dump leak | AES-256-GCM column encryption for sensitive fields |
| **I — Info Disclosure** | LLM training on user data | OpenAI `data_training=false` flag + summaries only |
| **D — Denial of Service** | API flood | Rate limit per JWT (100 req/min) via Redis |
| **E — Elevation of Privilege** | Member → Admin | RBAC enforced at route + DB layer (`require_org_member("admin")`) |

---

## 5. Key Management — The Core Decision

### 5.1 Three Types of Keys

| Key | Purpose | Rotation cadence | Storage |
|---|---|---|---|
| **JWT signing key (HS256)** | Sign access/refresh tokens | 90 days | AWS KMS / SSM Param Store |
| **Master Encryption Key (KEK)** | Wraps per-org data keys | Yearly | AWS KMS (CMK, never exported) |
| **Per-Org Data Encryption Key (DEK)** | Encrypts that org's transactions | Per-org, on org creation | DB column, KMS-wrapped |

### 5.2 Per-Org AES-256 Key in KMS — Why

**Decision:** Each organisation gets its **own AES-256-GCM data key**, which is
itself **encrypted (wrapped) by a KMS Customer Master Key (CMK)**.

**Reasoning:**
- ✅ **Blast radius isolation** — leaking one org's DEK doesn't touch others.
- ✅ **Per-tenant key rotation** — we can rotate a single org's key without
  re-encrypting the whole DB.
- ✅ **Compliance-friendly** — auditors love being able to point at "this
  org's data is encrypted with this specific key."
- ✅ **KMS handles the hard part** — we never see the master key in plaintext;
  AWS rotates and audits it for us.

### 5.3 Envelope Encryption Flow

```
Encrypting a transaction summary for org X:
  1. Read wrapped_dek from organisations.encrypted_dek
  2. Call kms.Decrypt(wrapped_dek)  →  plaintext DEK (in memory only)
  3. plaintext DEK + AES-256-GCM   →  ciphertext
  4. Discard plaintext DEK from memory
  5. Store ciphertext

Decrypting:
  1. Same as step 1-2 above
  2. AES-GCM decrypt with DEK
  3. Discard DEK
```

**Current MVP implementation** (`app/core/security.py`):
- `_derive_org_key()` uses HKDF over a master env var (placeholder).
- **Production migration plan (Phase 5):** swap that derivation for
  `boto3 kms.GenerateDataKey()` and store the wrapped DEK on the
  `organisations` row.

---

## 6. Secrets in Source Control

- ❌ `.env` — **never** committed; `.gitignore` enforced.
- ✅ `.env.example` — placeholders only.
- ✅ Production secrets — AWS Secrets Manager → injected at container start.
- ✅ CI secrets — GitHub Actions `secrets.*` (test-only fake keys in `ci.yml`).

---

## 7. Open Questions / Phase 5 Work

1. **Hardware-backed key storage** — investigate AWS CloudHSM if SOC2-lite path
   demands it.
2. **Field-level encryption** — encrypt `transactions.party_name` and `memo`
   columns specifically, instead of whole-payload only.
3. **Bring-Your-Own-Key (BYOK)** — enterprise customers may require their own
   KMS CMK; defer until at least 3 customers ask.

---

## 8. Incident Response

If a key is suspected compromised:
1. **JWT key:** rotate `JWT_SECRET_KEY`, invalidate all tokens (force re-login).
2. **Per-org DEK:** generate new DEK via KMS, re-encrypt that org's data,
   destroy old DEK.
3. **Master KMS CMK:** rotate via AWS, re-wrap all DEKs.

All three drills must be **runbook-tested before GA** (Phase 6).
