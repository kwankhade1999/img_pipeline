# Shopping Assistant Service

An AI-powered shopping assistant that analyzes a room image and recommends matching products using **OpenAI GPT-4o** and a **PostgreSQL + pgvector** vector store.

---

## How It Works

The service runs a 3-step RAG (Retrieval-Augmented Generation) pipeline on every request:

```
User sends: room image + text prompt
              |
              v
  Step 1 — GPT-4o Vision
  "Describe the style of this room"
              |
              v  room_description
  Step 2 — OpenAI Embeddings + pgvector
  Embed (room_description + prompt) → similarity search in vectordb
              |
              v  matching products
  Step 3 — GPT-4o RAG
  "Recommend products from this list for this room"
              |
              v
  { "content": "Brief room description... recommendations... [id1],[id2],[id3]" }
```

---

## API

**`POST /`**

```json
{
  "message": "I need a lamp for my living room",
  "image": "https://example.com/room.jpg"
}
```

**Response:**

```json
{
  "content": "Your room has a modern minimalist style with neutral tones... I recommend the Bamboo Glass Jar... [OLJCESPC7Z], [L9ECAV7KIM], [2ZYFJ3GM2N]"
}
```

---

## Tech Stack

| Component | Technology |
|---|---|
| Web Framework | Flask |
| LLM (Vision + Text) | OpenAI GPT-4o (`gpt-4o`) |
| Embeddings | OpenAI `text-embedding-3-small` |
| Vector Store | PostgreSQL + pgvector (`vectordb:5432`) |
| LLM Orchestration | LangChain + LangChain-Postgres |
| Tracing | LangSmith (optional) |

---

## Prerequisites

| Requirement | Details |
|---|---|
| Kubernetes cluster | MicroK8s or EKS |
| OpenAI API Key | `sk-...` — [platform.openai.com](https://platform.openai.com) |
| LangChain API Key | `ls-...` — [smith.langchain.com](https://smith.langchain.com) (optional, for tracing) |
| vectordb running | In-cluster `vectordb` service (pgvector) |

---

## Environment Variables

All credentials are injected via the `shopping-assistant-secrets` Kubernetes Secret.

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key for GPT-4o and embeddings |
| `LANGCHAIN_API_KEY` | LangChain/LangSmith API key (optional) |
| `DATABASE_URL` | `postgresql+psycopg://authuser:<pass>@vectordb:5432/shoppingdb` |
| `COLLECTION_NAME` | LangChain PGVector collection name (e.g. `products`) |

---

## Step-by-Step Setup

### Step 1 — Deploy vectordb

`vectordb` is a dedicated PostgreSQL + pgvector instance. It is completely separate from the `postgres` instance used by authservice.

```bash
kubectl apply -f GitOps/base/vectordb/deployment.yaml
kubectl apply -f GitOps/base/vectordb/service.yaml
```

The init ConfigMap automatically:
- Enables the `vector` extension
- Creates the `langchain_pg_collection` and `langchain_pg_embedding` tables

### Step 2 — Create Kubernetes Secrets

```bash
# postgres-secret is shared with vectordb for its DB password
kubectl create secret generic postgres-secret \
  --from-literal=password=Manoj7100

# Shopping assistant API keys and DB connection
kubectl create secret generic shopping-assistant-secrets \
  --from-literal=OPENAI_API_KEY=sk-your-openai-key \
  --from-literal=LANGCHAIN_API_KEY=ls-your-langchain-key \
  --from-literal=DATABASE_URL="postgresql+psycopg://authuser:Manoj7100@vectordb:5432/shoppingdb" \
  --from-literal=COLLECTION_NAME=products
```

### Step 3 — Load Product Embeddings

Before the service can recommend products, embed the product catalog into vectordb. Run this once as a setup script:

```python
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector
from langchain_core.documents import Document
import os

products = [
    Document(
        page_content="Aviator Sunglasses - Retro-style gold aviator sunglasses",
        metadata={"id": "OLJCESPC7Z", "name": "Aviator Sunglasses", "categories": "accessories"}
    ),
    Document(
        page_content="Tank Top - Unisex white tank with minimalist design",
        metadata={"id": "66VCHSJNUP", "name": "Tank Top", "categories": "clothing"}
    ),
    # ... add all products from productcatalogservice/products.json
]

vectorstore = PGVector(
    embeddings=OpenAIEmbeddings(model="text-embedding-3-small"),
    collection_name="products",
    connection=os.environ["DATABASE_URL"],
)
vectorstore.add_documents(products)
print("Products embedded successfully.")
```

### Step 4 — Deploy the Shopping Assistant

```bash
kubectl apply -f GitOps/base/shoppingassistantservice/deployment.yaml
kubectl apply -f GitOps/base/shoppingassistantservice/service.yaml
```

Verify the pod is running:

```bash
kubectl get pods -l app=shoppingassistantservice
kubectl logs -l app=shoppingassistantservice
```

### Step 5 — Test the Service

Port-forward to test locally:

```bash
kubectl port-forward svc/shoppingassistantservice 8080:8080
```

Send a test request:

```bash
curl -X POST http://localhost:8080/ \
  -H "Content-Type: application/json" \
  -d '{
    "message": "I need a lamp for my living room",
    "image": "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9e/Living_room_MiD.jpg/1280px-Living_room_MiD.jpg"
  }'
```

---

## GitOps Deployment

ArgoCD manages this service automatically. The ArgoCD Application is defined in:
- `GitOps/shoppingassistantservice/app.yaml`
- `GitOps/argocd-app.yaml`

Any push to the `main` branch of `ITkannadigaru/GitOps` triggers an automatic sync.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Pod in `CrashLoopBackOff` | Run `kubectl logs` — likely a missing secret key |
| `relation "langchain_pg_embedding" does not exist` | vectordb init script didn't run — delete and re-apply vectordb deployment |
| Empty recommendations | Product embeddings not loaded — run Step 3 |
| `AuthenticationError: OpenAI` | Wrong or missing `OPENAI_API_KEY` in the secret |
| `connection refused vectordb:5432` | vectordb pod not running — check `kubectl get pods -l app=vectordb` |
| Embedding model mismatch | Products must be embedded with the same model used at query time (`text-embedding-3-small`) |
