# Neural Ledger — Backend (M1: Auth & Tenancy)

FastAPI + PostgreSQL backend for Neural Ledger.

## Stack

- **FastAPI** + async SQLAlchemy 2.0
- **PostgreSQL 16** (asyncpg driver)
- **JWT** (access + refresh) via `python-jose`
- **bcrypt** for password hashing
- **AES-256-GCM** for per-org payload encryption
- **Alembic** for migrations
- **pytest** + httpx for tests
- **Docker Compose** for local dev

## Quick start

```bash
# 1. Copy env file
cp .env.example .env

# 2. Spin up everything
docker-compose up --build

# 3. Open Swagger
open http://localhost:8000/docs
```

## Project structure

```
app/
├── main.py                   FastAPI factory + lifespan
├── core/
│   ├── config.py             pydantic-settings env loader
│   ├── security.py           bcrypt + JWT + AES-256-GCM
│   └── dependencies.py       get_db, current_user, require_org_member
├── db/
│   ├── base.py               Declarative base + UUID/Timestamp mixins
│   └── session.py            Async engine + session factory
├── models/
│   ├── user.py
│   └── org.py                Organisation + OrgMember (RBAC)
├── schemas/
│   ├── auth.py               Pydantic v2 — auth payloads
│   └── org.py                Pydantic v2 — org payloads
├── api/v1/
│   ├── auth.py               /register /login /refresh /me /logout
│   └── orgs.py               Full org CRUD + member management
└── alembic/                  Migrations

tests/                        pytest + httpx async tests
docs/THREAT_MODEL.md          Security model + KMS decision
```

## Endpoints

### Auth
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/auth/register` | Create user |
| POST | `/api/v1/auth/login`    | Get access + refresh tokens |
| POST | `/api/v1/auth/refresh`  | Rotate access token |
| GET  | `/api/v1/auth/me`       | Current user profile |
| POST | `/api/v1/auth/logout`   | Stateless logout |

### Organisations
| Method | Path | Purpose |
|---|---|---|
| POST   | `/api/v1/orgs` | Create org (creator becomes admin) |
| GET    | `/api/v1/orgs` | List my orgs |
| GET    | `/api/v1/orgs/{id}` | Org detail |
| PATCH  | `/api/v1/orgs/{id}` | Update (admin only) |
| DELETE | `/api/v1/orgs/{id}` | Soft delete (admin only) |
| POST   | `/api/v1/orgs/{id}/members` | Invite by email (admin) |
| GET    | `/api/v1/orgs/{id}/members` | List members |
| DELETE | `/api/v1/orgs/{id}/members/{user_id}` | Remove (admin) |

## Running tests

```bash
# Inside the API container or local venv with Postgres up
pytest -v
```

CI runs them automatically on every push.

## Security

See [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) for the full threat model
and per-org AES-256 / KMS key-management strategy.
