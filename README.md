# AI Research Agent

Point it at a topic and it runs the whole pipeline itself: pulls sources, drafts a report, screens the output for safety, evaluates its own quality, and remembers what it found. It's not a wrapper around a single prompt — it's a real multi-agent system deployed on AWS, complete with automated red-teaming and per-request LLM grading.

---

## The Stack

| Piece | Role in the system |
|---|---|
| **FastAPI** | Public REST layer — accepts a topic, hands back a report |
| **LangGraph** | Orchestrates a 4-stage agent chain: Search → Summarize → Draft → Verify |
| **TensorZero** | Sits in front of the LLM calls; primary model is GPT-4o with Groq Llama-3 as fallback |
| **AWS Bedrock Guardrails** | Screens both inbound prompts and outbound reports for unsafe content |
| **Redis (ElastiCache)** | Handles the semantic cache, session state, and the job queue |
| **PostgreSQL + pgvector (RDS)** | Durable memory store — reports are embedded and kept searchable |
| **LangSmith** | Captures a trace of every agent run and scores each report via LLM-as-judge |
| **PyRIT 0.14.0** | Fires scripted attacks (jailbreak, XPIA, crescendo, skeleton key) at the deployed app |
| **Terraform** | Stands up the entire AWS footprint from a single apply |
| **GitHub Actions** | Builds images and rolls them out to ECS on every push, with rollback on failure |

---

## Repo Layout

```
PROJECT/
├── app/
│   ├── main.py           API routes, background worker, everything else
│   ├── agents.py         The LangGraph agent chain
│   ├── cache.py          Semantic caching on Redis
│   ├── guardrails.py     Bedrock-backed safety checks
│   ├── memory.py         Redis session state + pgvector long-term memory
│   ├── queue.py          Job queue built on Redis Streams
│   ├── output.py         PDF/JSON export and report diffing
│   ├── eval.py           LangSmith judge-model evaluation
│   ├── config.py         Pulls runtime config from Secrets Manager
│   ├── auth.py           API key check middleware
│   ├── retry.py          Backoff logic around LLM calls
│   ├── pool.py           Postgres connection pooling
│   └── Dockerfile
├── pyrit_dashboard/
│   ├── main.py           Standalone red-team dashboard (PyRIT 0.14.0)
│   ├── requirements.txt
│   └── Dockerfile
├── tensorzero/
│   ├── tensorzero.toml   Model routing + system prompts
│   └── Dockerfile
├── terraform/
│   └── main.tf           Full AWS infra definition
├── .github/workflows/
│   └── deploy.yml        CI/CD with automatic rollback
├── bootstrap.bat         One-time backend init (Windows)
├── bootstrap.sh          One-time backend init (Mac/Linux)
├── requirements.txt
├── index.html            Frontend
└── README.md
```

---

## Before You Start

You'll need these on your machine:

| Tool | Get it | Verify |
|---|---|---|
| AWS CLI | https://aws.amazon.com/cli/ | `aws --version` |
| Terraform | https://developer.hashicorp.com/terraform/install | `terraform --version` |
| Git | https://git-scm.com/downloads | `git --version` |

You do **not** need Docker locally — image builds happen entirely in GitHub Actions.

---

## Getting It Running

### Step 1 — Set up AWS credentials

```bash
aws configure
```

You'll be prompted for:
- **Access Key ID** — from AWS Console → your account name → Security Credentials → Create access key
- **Secret Access Key** — only shown once, so copy it right away
- **Region** — `us-east-1`
- **Output format** — `json`

---

### Step 2 — Bootstrap the Terraform backend

Terraform state lives in S3 with locking via DynamoDB, and that has to exist before anything else does. The bootstrap script creates both.

**Windows:**
```cmd
bootstrap.bat
```

**Mac / Linux / Git Bash:**
```bash
chmod +x bootstrap.sh
./bootstrap.sh
```

You should see:
```
S3 bucket  : research-agent-tfstate
DynamoDB   : research-agent-tf-locks
Bootstrap complete.
```

---

### Step 3 — Push to GitHub and wire up secrets

1. Create a new repo (call it `research-agent` or whatever you like) at https://github.com

2. Push the project:
```bash
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/YOUR_USERNAME/research-agent.git
git push -u origin main
```

3. Under repo → Settings → Secrets and variables → Actions, add:

| Secret | Value |
|---|---|
| `AWS_ACCESS_KEY_ID` | The key from Step 1 |
| `AWS_SECRET_ACCESS_KEY` | The key from Step 1 |

---

### Step 4 — Stand up the infrastructure

```bash
cd terraform
terraform init
terraform apply -var="app_image=placeholder" -var="pyrit_image=placeholder"
```

Confirm with `yes`. Expect this to run 5–10 minutes.

It provisions: VPC + subnets, ECS cluster, ALB, ElastiCache Redis, RDS Postgres, a Bedrock Guardrail, Secrets Manager entries, ECR repos, IAM roles, VPC endpoints, auto-scaling policies, and an EventBridge rule for the weekly red-team run.

Hang onto the outputs when it finishes:
```
alb_dns        = "research-agent-alb-xxxxxxx.us-east-1.elb.amazonaws.com"
app_ecr_url    = "123456789.dkr.ecr.us-east-1.amazonaws.com/research-agent-app"
pyrit_ecr_url  = "123456789.dkr.ecr.us-east-1.amazonaws.com/research-agent-pyrit"
```

---

### Step 5 — Collect your API keys

Three keys, all needed:

| Key | Source |
|---|---|
| `OPENAI_API_KEY` | https://platform.openai.com/api-keys |
| `GROQ_API_KEY` | https://console.groq.com/keys |
| `LANGSMITH_API_KEY` | https://smith.langchain.com → Profile → API Keys → Create |

LangSmith's free tier covers this — once the key is in, tracing and scoring happen automatically with no further config.

---

### Step 6 — Populate Secrets Manager

Terraform already writes in the Redis URL, database URL, Guardrail ID, and other runtime settings. The only gap is your three API keys.

Go to **AWS Console → Secrets Manager → `research-agent/config` → Retrieve secret value → Edit**, and swap out the placeholders:

```json
{
  "OPENAI_API_KEY":    "sk-...",
  "GROQ_API_KEY":      "gsk_...",
  "LANGSMITH_API_KEY": "ls__..."
}
```

Save, and don't touch the rest.

**Optional — lock down the API with a key:**

Add one more field to the same secret:
```json
"API_KEY": "any-string-you-choose"
```

Once set, every call to the app needs an `X-API-Key: your-string` header — the frontend has a field for this that persists in the browser. Skip it and the app just runs open.

---

### Step 7 — Let GitHub Actions finish the deploy

Your Step 3 push already kicked off a deployment. Head to **GitHub repo → Actions** and wait for it to go green — usually 5–10 minutes. In that run it:

1. Builds the app, PyRIT, and TensorZero images
2. Pushes them to ECR
3. Registers fresh ECS task definitions
4. Updates the ECS services
5. Watches for stability, and auto-rolls-back if something breaks

Green means live — reachable at the ALB URL from Step 4.

---

## Working With It

### Frontend

Navigate to:
```
http://<alb_dns>/
```

1. Drop in your API key if one is configured (browser-persisted)
2. Enter a topic
3. Pick an output format — text, PDF, or JSON
4. Hit **Start Research**; it polls on its own until finished
5. Use **Show Changes vs Previous** to diff against the last report on that topic

---

### API Reference

Include `X-API-Key: your-key` on every call if auth is enabled.

**Kick off a job:**
```bash
curl -X POST http://<alb_dns>/research \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{"topic": "AI chip market 2025", "session_id": "abc123", "output_format": "text"}'
```
Returns `{"job_id": "...", "session_id": "..."}`

**Check status / fetch result:**
```bash
curl http://<alb_dns>/result/<job_id> -H "X-API-Key: your-key"
```
`{"status": "pending"}` while running, full report once done.

**Grab the PDF:**
```bash
curl http://<alb_dns>/result/<job_id>/pdf -H "X-API-Key: your-key" -o report.pdf
```

**Pull session history:**
```bash
curl http://<alb_dns>/session/<session_id> -H "X-API-Key: your-key"
```

**Diff against the previous report:**
```bash
curl http://<alb_dns>/diff/<topic> -H "X-API-Key: your-key"
```

**System / Redis stats:**
```bash
curl http://<alb_dns>/stats -H "X-API-Key: your-key"
```

**Health probe (no auth required):**
```bash
curl http://<alb_dns>/health
```

---

## Tracing and Evaluation via LangSmith

Every job automatically:
1. Traces each agent node — search, summarize, draft, verify
2. Runs four LLM-as-judge checks (relevance, completeness, hallucination risk, overall quality)
3. Logs the results to a LangSmith dataset named `research-agent-reports`

Browse it at https://smith.langchain.com → project `research-agent`.

**Kick off a batch evaluation manually** (pulls recent topics from the DB):
```bash
curl -X POST http://<alb_dns>/run-evaluation \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{}'
```

Or target specific topics:
```bash
curl -X POST http://<alb_dns>/run-evaluation \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{"topics": ["quantum computing", "AI regulations"]}'
```

---

## Red-Teaming with PyRIT

Reachable at:
```
http://<alb_dns>:8001/
```

This dashboard throws four categories of attack at the live app to confirm the guardrails actually hold:

| Attack | Approach |
|---|---|
| **Jailbreak** | Directly tries to override the safety instructions |
| **XPIA** | Smuggles malicious instructions inside a research topic |
| **Crescendo** | Ramps up gradually from harmless questions toward harmful ones |
| **Skeleton Key** | Invokes fake authority (researcher role, CISO sign-off) to force compliance |

Pick **Run Selected Attacks**, give it 2–5 minutes, and you'll see each attempt marked BLOCKED or PASSED with a risk score attached.

Results persist in Redis across container restarts.

**Same thing via API:**
```bash
# Everything
curl http://<alb_dns>:8001/run-attacks

# Just a subset
curl "http://<alb_dns>:8001/run-attacks?types=jailbreak,xpia"

# Pull results
curl http://<alb_dns>:8001/results
```

An EventBridge rule also fires the full attack suite automatically every Monday at 2am UTC.

---

## Shutting It Down

```bash
cd terraform
terraform destroy -var="app_image=placeholder" -var="pyrit_image=placeholder"
```

#### Also clean up the ECR repo, S3 bucket, DynamoDB table, and Secrets Manager entry

```bash
aws secretsmanager delete-secret --secret-id "research-agent/config" --force-delete-without-recovery --region us-east-1
```

Confirm with `yes` when prompted. This tears down everything — ECS, RDS, Redis, ALB, VPC, the Bedrock Guardrail, Secrets Manager, ECR repos, all of it.

> **Note:** RDS has deletion protection turned on. Terraform can still remove it, but AWS takes a final snapshot first (`research-agent-postgres-final-snapshot`) so you don't lose data by accident.