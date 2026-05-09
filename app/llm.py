import random
import re
from dataclasses import dataclass

import httpx

from app.catalog import CatalogItem
from app.config import Settings
from app.models import ChatMessage


@dataclass(frozen=True)
class LLMRoute:
    provider: str
    api_key: str
    model: str


class ReplyPolisher:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.routes = self._build_routes(settings)
        self.enabled = bool(self.routes)

    def _build_routes(self, settings: Settings) -> list[LLMRoute]:
        routes: list[LLMRoute] = []
        providers = settings.provider_order_list
        for provider in providers:
            if provider.lower() == "groq":
                for key in settings.groq_key_list:
                    for model in settings.groq_model_list:
                        routes.append(LLMRoute("groq", key, model))
            if provider.lower() == "gemini":
                for key in settings.gemini_key_list:
                    for model in settings.gemini_model_list:
                        routes.append(LLMRoute("gemini", key, model))
        return routes

    def polish(
        self,
        base_reply: str,
        messages: list[ChatMessage],
        items: list[CatalogItem],
        memory_summary: str = "",
    ) -> str:
        if not self.enabled or not items:
            return base_reply

        prompt = self._prompt(base_reply, messages, items, memory_summary)
        routes = self.routes[:]
        random.shuffle(routes)
        for route in routes[: self._attempt_count(maximum=2)]:
            try:
                if route.provider == "groq":
                    text = self._call_groq(route, prompt)
                else:
                    text = self._call_gemini(route, prompt)
                if text:
                    cleaned = self._sanitize_output(text)
                    if self._is_safe_polish(cleaned, base_reply, items):
                        return cleaned
            except Exception:
                continue
        return base_reply

    def route_status(self) -> dict[str, int]:
        return {
            "total_routes": len(self.routes),
            "groq_routes": len([route for route in self.routes if route.provider == "groq"]),
            "gemini_routes": len([route for route in self.routes if route.provider == "gemini"]),
            "max_attempts": self.settings.llm_max_attempts,
        }

    def summarize_memory(self, previous_summary: str, messages: list[ChatMessage], response_text: str) -> str:
        prompt = (
            "Summarize this user's SHL assessment-selection conversation memory for a visual analytics dashboard. "
            "Keep durable preferences, role contexts, constraints, selected assessments, refinements, and open questions. "
            "Do not invent facts. Do not write an introduction such as 'Here's a summary'. "
            "Use exactly these markdown headings when relevant: **Role Contexts:**, **Constraints:**, **Selected Assessments:**, **Refinements:**, **Open Questions:**. "
            "Use short bullet points. Keep it under 180 words.\n\n"
            f"Previous memory summary:\n{previous_summary or 'None yet.'}\n\n"
            "Latest conversation payload:\n"
            + "\n".join(f"{m.role}: {m.content}" for m in messages[-8:])
            + f"\nassistant_latest: {response_text}"
        )
        groq_routes = [route for route in self.routes if route.provider == "groq"]
        random.shuffle(groq_routes)
        for route in groq_routes[: self._attempt_count(maximum=1)]:
            try:
                text = self._call_groq(route, prompt)
                if text:
                    return self._sanitize_output(text)[:2000]
            except Exception:
                continue
        return self._fallback_summary(previous_summary, messages, response_text)

    def _fallback_summary(self, previous_summary: str, messages: list[ChatMessage], response_text: str) -> str:
        latest_user = next((m.content for m in reversed(messages) if m.role.lower() == "user"), "")
        fragment = f"Latest user need: {latest_user[:240]}. Latest assistant response included: {response_text[:260]}."
        if previous_summary:
            return f"{previous_summary}\n{fragment}"[-2000:]
        return fragment

    def _prompt(
        self,
        base_reply: str,
        messages: list[ChatMessage],
        items: list[CatalogItem],
        memory_summary: str,
    ) -> str:
        catalog_lines = "\n".join(
            f"- {item.name} | {item.url} | test_type={item.test_type} | keys={', '.join(item.keys)} | duration={item.duration or '-'} | languages={', '.join(item.languages[:8]) or '-'} | {item.description[:420]}"
            for item in items[:10]
        )
        allowed_names = ", ".join(item.name for item in items[:10])
        history = "\n".join(f"{m.role}: {m.content}" for m in messages[-6:])
        return (
            "You are a strictly factual SHL assessment catalog assistant. Output only the final user-facing answer. "
            "Never include hidden reasoning, analysis, scratchpad text, XML tags, <think> blocks, or planning notes. "
            "Rewrite the base reply into a professional support-chat response, but do not change its meaning. "
            "The SHL catalog lines are the only source of truth. If a fact is not in those lines or the base reply, do not say it. "
            "You may mention only these assessment names: "
            f"{allowed_names}. "
            "Do not add new product names, URLs, claims, legal advice, hiring advice, compliance conclusions, or external knowledge. "
            "Mention the recommended catalog items consistently with the supplied list. "
            "Do not suggest adding an item that is already in the supplied catalog lines. "
            "Do not contradict caveats in the base reply, especially when the base reply says a specific test does not exist. "
            "Do not include a markdown table. Do not include raw URLs. Do not use markdown bold, headings, numbered lists, or bullet lists. "
            "Use the user's memory summary only for continuity, not as catalog evidence. "
            "Keep it practical and recruiter-friendly: 5 to 7 complete sentences with sequencing logic, tradeoffs, and how to use the battery. Do not cut off mid-sentence.\n\n"
            f"User memory summary:\n{memory_summary or 'No stored memory yet.'}\n\n"
            f"Conversation:\n{history}\n\n"
            f"Catalog lines:\n{catalog_lines}\n\n"
            f"Base reply:\n{base_reply}"
        )

    def _call_groq(self, route: LLMRoute, prompt: str) -> str:
        from groq import Groq

        client = Groq(api_key=route.api_key, timeout=5)
        response = client.chat.completions.create(
            model=route.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=760,
        )
        return response.choices[0].message.content.strip()

    def _call_gemini(self, route: LLMRoute, prompt: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{route.model}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 760},
        }
        with httpx.Client(timeout=5) as client:
            response = client.post(url, params={"key": route.api_key}, json=payload)
            response.raise_for_status()
            data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(part.get("text", "") for part in parts).strip()

    def _attempt_count(self, maximum: int) -> int:
        return max(1, min(maximum, self.settings.llm_max_attempts))

    def _sanitize_output(self, text: str) -> str:
        text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<analysis>[\s\S]*?</analysis>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"```(?:thinking|analysis|scratchpad)[\s\S]*?```", "", text, flags=re.IGNORECASE)
        text = re.sub(r"(?is)^.*?</think>", "", text)
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"\|.*\|", "", text)
        text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _is_safe_polish(self, text: str, base_reply: str, items: list[CatalogItem]) -> bool:
        if not text:
            return False
        lowered = text.lower()
        unsafe_markers = ["<think", "ignore previous", "as an ai", "i cannot access", "according to my knowledge"]
        if any(marker in lowered for marker in unsafe_markers):
            return False
        if "http://" in lowered or "https://" in lowered or "|---" in text or "| # |" in text:
            return False
        if len(text) < 180 and len(base_reply) > 260:
            return False
        if not text.rstrip().endswith((".", "?", "!")):
            return False
        if "rust-specific" in base_reply.lower() and "does not" not in lowered and "no rust" not in lowered:
            return False

        allowed_names = {item.name.lower() for item in items}
        catalog_like_phrases = [
            "assessment",
            "test",
            "questionnaire",
            "simulation",
            "verify",
            "opq",
            "svar",
        ]
        if any(phrase in lowered for phrase in catalog_like_phrases):
            mentioned_allowed = any(name in lowered for name in allowed_names)
            base_mentions_allowed = any(name in base_reply.lower() for name in allowed_names)
            if base_mentions_allowed and not mentioned_allowed:
                return False
        return True
