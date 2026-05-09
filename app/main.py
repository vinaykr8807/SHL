from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.catalog import Catalog, VectorIndex
from app.config import get_settings
from app.llm import ReplyPolisher
from app.llamaindex_adapter import OptionalLlamaIndex
from app.models import AuthResponse, ChatRequest, ChatResponse, LoginRequest, RecommendationDetailsRequest, RegisterRequest
from app.recommender import SHLRecommender
from app.storage import Storage
from app.insights import build_detail, coverage, infer_strategy, total_duration


settings = get_settings()
catalog = Catalog(settings.resolve(settings.catalog_path))
vector_index = VectorIndex(catalog, settings.embedding_model, settings.enable_sentence_transformer)
recommender = SHLRecommender(catalog, vector_index)
storage = Storage(settings.resolved_database_path, settings.resolved_evidence_dir)
polisher = ReplyPolisher(settings)
llama_index = OptionalLlamaIndex(catalog)

app = FastAPI(title="Conversational SHL Assessment Recommender")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = settings.root_dir / "frontend"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/login")
def login_page() -> FileResponse:
    return FileResponse(static_dir / "login.html")


@app.get("/chatbot")
def chatbot_page() -> FileResponse:
    return FileResponse(static_dir / "chatbot.html")


@app.get("/memory/{user_id}")
def memory_page(user_id: str) -> FileResponse:
    return FileResponse(static_dir / "memory.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/debug/index")
def debug_index() -> dict[str, str | int]:
    return {
        "catalog_items": len(catalog.items),
        "index_mode": vector_index.mode,
        "llamaindex": llama_index.status(),
        **polisher.route_status(),
    }


@app.post("/auth/register", response_model=AuthResponse)
def register(payload: RegisterRequest) -> AuthResponse:
    try:
        user = storage.create_user(payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AuthResponse(**user)


@app.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest) -> AuthResponse:
    user = storage.authenticate(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    return AuthResponse(**user)


@app.get("/users/{user_id}/conversations")
def conversations(user_id: str) -> list[dict[str, str]]:
    return storage.list_conversations(user_id)


@app.get("/users/{user_id}/memory")
def user_memory(user_id: str) -> dict:
    memory = storage.load_user_memory(user_id)
    if not memory:
        raise HTTPException(status_code=404, detail="User memory not found.")
    return memory


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    memory = storage.load_user_memory(payload.user_id)
    memory_summary = memory.get("summary", "") if memory else ""
    response = recommender.respond(payload.messages)
    if response.recommendations and polisher.enabled:
        items = [catalog.by_url[rec.url] for rec in response.recommendations if rec.url in catalog.by_url]
        response.reply = polisher.polish(response.reply, payload.messages, items, memory_summary)
    storage.save_conversation(payload.user_id, payload.messages, response)
    if payload.user_id:
        updated_summary = polisher.summarize_memory(memory_summary, payload.messages, response.reply)
        storage.update_user_memory_summary(payload.user_id, updated_summary)
    return response


@app.post("/recommendation-details")
def recommendation_details(payload: RecommendationDetailsRequest) -> dict:
    user_messages = [message.content for message in payload.messages if message.role.lower() == "user"]
    context = user_messages[-1] if user_messages else ""
    items = [catalog.by_url[url] for url in payload.urls if url in catalog.by_url]
    return {
        "strategy": infer_strategy(context),
        "coverage": coverage(items),
        "total_duration": total_duration(items),
        "items": [build_detail(item, context) for item in items],
    }
