from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str
    content: str


class Recommendation(BaseModel):
    name: str
    url: str
    test_type: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)
    user_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    recommendations: list[Recommendation] = Field(default_factory=list)
    end_of_conversation: bool = False


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    user_id: str
    username: str


class RecommendationDetailsRequest(BaseModel):
    urls: list[str] = Field(default_factory=list)
    messages: list[ChatMessage] = Field(default_factory=list)
