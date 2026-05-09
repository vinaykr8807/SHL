import re
from dataclasses import dataclass

from app.catalog import Catalog, CatalogItem, VectorIndex, dedupe_items, normalize_text
from app.insights import coverage, infer_strategy, total_duration
from app.models import ChatMessage, ChatResponse


OFF_TOPIC_PATTERNS = [
    "legal",
    "law",
    "lawsuit",
    "compliance requirement",
    "legally required",
    "satisfy that requirement",
    "salary",
    "compensation",
    "interview questions",
    "write a job description",
    "ignore previous",
    "system prompt",
    "developer message",
    "prompt injection",
    "ignore your",
    "ignore the catalog",
    "anywhere",
    "outside shl",
    "from anywhere",
]

CONFIRM_PATTERNS = [
    "thanks",
    "thank you",
    "that works",
    "perfect",
    "confirmed",
    "lock",
    "locking",
    "that's good",
    "that covers it",
    "keep the shortlist",
    "keep it",
]

DROP_PATTERNS = {
    "opq": ["occupational personality questionnaire opq32r", "opq"],
    "verify": ["verify interactive g+", "verify g+", "g+"],
    "rest": ["restful web services", "rest"],
    "personality": ["occupational personality questionnaire opq32r", "opq"],
}

SPECIAL_PRODUCTS = {
    "opq": "Occupational Personality Questionnaire OPQ32r",
    "gplus": "SHL Verify Interactive G+",
    "numerical": "SHL Verify Interactive - Numerical Reasoning",
    "graduate_scenarios": "Graduate Scenarios",
    "gsa": "Global Skills Assessment",
    "gsa_report": "Global Skills Development Report",
    "opq_sales": "OPQ MQ Sales Report",
    "sales_transformation": "Sales Transformation 2.0 - Individual Contributor",
    "dsi": "Dependability and Safety Instrument (DSI)",
    "safety_8": "Manufac. & Indust. - Safety & Dependability 8.0",
    "workplace_safety": "Workplace Health and Safety (New)",
    "hipaa": "HIPAA (Security)",
    "medical": "Medical Terminology (New)",
    "word365_ess": "Microsoft Word 365 - Essentials (New)",
    "excel365": "Microsoft Excel 365 (New)",
    "word365": "Microsoft Word 365 (New)",
    "excel_quick": "MS Excel (New)",
    "word_quick": "MS Word (New)",
    "java_adv": "Core Java (Advanced Level) (New)",
    "spring": "Spring (New)",
    "rest": "RESTful Web Services (New)",
    "sql": "SQL (New)",
    "aws": "Amazon Web Services (AWS) Development (New)",
    "docker": "Docker (New)",
    "linux": "Linux Programming (General)",
    "networking": "Networking and Implementation (New)",
    "live_coding": "Smart Interview Live Coding",
    "svar_us": "SVAR Spoken English (US) (New)",
    "contact_center": "Contact Center Call Simulation (New)",
    "entry_customer": "Entry Level Customer Serv - Retail & Contact Center",
    "phone_sim": "Customer Service Phone Simulation",
    "finance": "Financial Accounting (New)",
    "stats": "Basic Statistics (New)",
}


@dataclass
class ConversationState:
    all_user_text: str
    last_user_text: str
    prior_items: list[CatalogItem]
    turn_count: int


class SHLRecommender:
    def __init__(self, catalog: Catalog, index: VectorIndex):
        self.catalog = catalog
        self.index = index

    def respond(self, messages: list[ChatMessage]) -> ChatResponse:
        state = self._state(messages)
        if not state.last_user_text:
            return ChatResponse(reply="Tell me the role or hiring situation, and I’ll narrow the SHL assessment options.", recommendations=[])

        refusal = self._refusal(state.last_user_text)
        if refusal:
            return ChatResponse(reply=refusal, recommendations=[], end_of_conversation=False)

        comparison = self._comparison(state)
        if comparison:
            return comparison

        if self._is_confirmation(state.last_user_text) and state.prior_items:
            return self._response(
                "Confirmed. I’ll keep this SHL shortlist as the selected assessment battery.",
                state.prior_items,
                end=True,
            )

        if self._too_vague(state):
            return ChatResponse(
                reply="I can help, but I need one bit more context before recommending: what role or job family are you hiring for, and is this for entry, graduate, mid-level, or senior candidates?",
                recommendations=[],
                end_of_conversation=False,
            )

        items = self._scenario_items(state)
        if not items:
            items = self._ranked_items(state.all_user_text)

        items = self._apply_refinements(state, items)
        if not items:
            return ChatResponse(
                reply="I could not ground a safe shortlist in the SHL catalog yet. Please share the role, seniority, and must-have skills.",
                recommendations=[],
                end_of_conversation=False,
            )

        reply = self._build_reply(state, items)
        return self._response(reply, items, end=False)

    def _state(self, messages: list[ChatMessage]) -> ConversationState:
        user_texts = [m.content for m in messages if m.role.lower() == "user"]
        assistant_text = "\n".join(m.content for m in messages if m.role.lower() == "assistant")
        return ConversationState(
            all_user_text="\n".join(user_texts),
            last_user_text=user_texts[-1] if user_texts else "",
            prior_items=self.catalog.from_recommendations_in_text(assistant_text),
            turn_count=len(messages),
        )

    def _refusal(self, text: str) -> str | None:
        lower = normalize_text(text)
        if any(pattern in lower for pattern in OFF_TOPIC_PATTERNS):
            return (
                "I can only help with SHL assessment selection from the catalog. "
                "I can describe what a listed SHL assessment measures, but I can’t provide legal, compliance, general hiring, or prompt/system-policy advice."
            )
        return None

    def _too_vague(self, state: ConversationState) -> bool:
        text = normalize_text(state.all_user_text)
        vague = {"assessment", "test", "solution", "hiring", "screening", "recruiting"}
        role_signals = [
            "java", "engineer", "developer", "sales", "admin", "assistant", "graduate", "finance",
            "contact", "centre", "center", "operator", "leadership", "executive", "healthcare",
            "manager", "customer", "rust", "analyst", "trainee", "excel", "word", "hipaa",
        ]
        return any(v in text for v in vague) and not any(r in text for r in role_signals)

    def _is_confirmation(self, text: str) -> bool:
        lower = normalize_text(text)
        return any(pattern in lower for pattern in CONFIRM_PATTERNS)

    def _comparison(self, state: ConversationState) -> ChatResponse | None:
        text = normalize_text(state.last_user_text)
        if not any(token in text for token in ["difference", "different", "compare", "vs", "versus"]):
            return None

        pairs = [
            ("opq", "opq mq sales", ["opq", "opq_sales"]),
            ("dsi", "safety dependability", ["dsi", "safety_8"]),
            ("dsi", "safety and dependability", ["dsi", "safety_8"]),
            ("contact center call simulation", "customer service phone simulation", ["contact_center", "phone_sim"]),
            ("verify", "technical", ["gplus"]),
        ]
        for left, right, keys in pairs:
            if left in text and right in text:
                items = [self._product(key) for key in keys]
                grounded = [item for item in items if item]
                reply = self._compare_reply(grounded)
                return self._response(reply, state.prior_items or grounded, end=False)

        mentioned = self._mentioned_catalog_items(state.last_user_text)
        if len(mentioned) >= 2:
            return self._response(self._compare_reply(mentioned[:2]), state.prior_items or mentioned[:2], end=False)
        if state.prior_items:
            return self._response(self._compare_reply(state.prior_items[:2]), state.prior_items, end=False)
        return ChatResponse(
            reply="Which two SHL assessments should I compare? I’ll ground the comparison in the catalog entries.",
            recommendations=[],
            end_of_conversation=False,
        )

    def _compare_reply(self, items: list[CatalogItem]) -> str:
        if len(items) < 2:
            item = items[0] if items else None
            if item:
                return f"{item.name} is listed as {', '.join(item.keys)}. Catalog description: {item.description}"
            return "I need two catalog assessment names to compare."
        a, b = items[0], items[1]
        return (
            f"{a.name} is a {', '.join(a.keys)} product. {a.description} "
            f"{b.name} is a {', '.join(b.keys)} product. {b.description} "
            "So the practical difference is the measurement focus and catalog category above; I would use the one whose description matches the role requirement more closely."
        )

    def _mentioned_catalog_items(self, text: str) -> list[CatalogItem]:
        found: list[CatalogItem] = []
        for item in self.catalog.items:
            if normalize_text(item.name) in normalize_text(text):
                found.append(item)
        return found

    def _product(self, key: str) -> CatalogItem | None:
        name = SPECIAL_PRODUCTS[key]
        return self.catalog.require(name)

    def _scenario_items(self, state: ConversationState) -> list[CatalogItem]:
        text = normalize_text(self._active_context(state))
        wanted: list[str] = []

        if "java" in text or "spring" in text or "full stack" in text or "microservice" in text:
            wanted += ["java_adv", "spring"]
            if "rest" in text and "drop rest" not in text:
                wanted.append("rest")
            if "sql" in text or "database" in text:
                wanted.append("sql")
            if "aws" in text or "cloud" in text:
                wanted.append("aws")
            if "docker" in text or "container" in text:
                wanted.append("docker")
            if "senior" in text or "architecture" in text or "architectural" in text:
                wanted.append("gplus")
            if "stakeholder" in text or "mentor" in text or "senior" in text:
                wanted.append("opq")

        if "rust" in text or "networking infrastructure" in text:
            wanted += ["live_coding", "linux", "networking"]
            if "cognitive" in text or "senior" in text:
                wanted.append("gplus")
            if "personality" in text or "senior" in text:
                wanted.append("opq")

        if "contact" in text or "call center" in text or "call centre" in text:
            if "us" in text or "english" in text:
                wanted.append("svar_us")
            wanted += ["contact_center", "entry_customer", "phone_sim"]

        if "graduate" in text and ("finance" in text or "financial" in text or "analyst" in text):
            wanted += ["numerical", "finance", "stats"]
            if "situational" in text or "judgement" in text or "judgment" in text:
                wanted.append("graduate_scenarios")
            wanted.append("opq")

        if "management trainee" in text or ("graduate" in text and "trainee" in text):
            wanted += ["gplus", "opq", "graduate_scenarios"]

        if "sales" in text and ("audit" in text or "reskill" in text or "re skill" in text or "restructuring" in text):
            wanted += ["gsa", "gsa_report", "opq", "opq_sales", "sales_transformation"]

        if "plant" in text or "chemical" in text or "safety" in text and "hipaa" not in text:
            wanted += ["dsi", "safety_8", "workplace_safety"]

        if "healthcare" in text or "hipaa" in text or "patient" in text:
            wanted += ["hipaa", "medical", "word365_ess", "dsi", "opq"]

        if "excel" in text or "word" in text or "admin assistant" in text or "administrative" in text:
            if "simulation" in text or "capabilities" in text or "capture" in text:
                wanted += ["excel365", "word365"]
            wanted += ["excel_quick", "word_quick"]
            if "skip personality" not in text and "drop opq" not in text:
                wanted.append("opq")

        if "personality" in text and not any(k in wanted for k in ["opq", "dsi"]):
            wanted.append("opq")
        if ("cognitive" in text or "reasoning" in text) and "gplus" not in wanted and "numerical" not in wanted:
            wanted.append("gplus")
        if ("situational" in text or "judgement" in text or "judgment" in text) and "graduate" in text:
            wanted.append("graduate_scenarios")

        items = [self._product(key) for key in wanted]
        return dedupe_items([item for item in items if item], limit=10)

    def _ranked_items(self, text: str) -> list[CatalogItem]:
        ranked = [item for item, score in self.index.search(text, top_k=25) if score > 0]
        useful = [
            item for item in ranked
            if not item.name.lower().endswith("report") or any(k in normalize_text(text) for k in ["report", "development", "leadership", "sales"])
        ]
        return dedupe_items(useful, limit=6)

    def _apply_refinements(self, state: ConversationState, items: list[CatalogItem]) -> list[CatalogItem]:
        text = normalize_text(state.last_user_text)
        text = text.replace("personality tests", "personality")
        if "add a personality measure" in text and any("opq" in normalize_text(item.name) for item in items):
            return items
        if state.prior_items and any(token in text for token in ["add", "drop", "remove", "replace", "actually", "keep"]):
            merged = list(state.prior_items)
        else:
            merged = list(items)

        for drop_key, fragments in DROP_PATTERNS.items():
            if (
                f"drop {drop_key}" in text
                or f"remove {drop_key}" in text
                or f"skip {drop_key}" in text
                or f"drop {drop_key} tests" in text
                or f"remove {drop_key} tests" in text
            ):
                merged = [item for item in merged if not any(fragment in normalize_text(item.name) for fragment in fragments)]

        additions: list[str] = []
        if "aws" in text:
            additions.append("aws")
        if "docker" in text:
            additions.append("docker")
        if "simulation" in text:
            additions += ["excel365", "word365"] if ("excel" in normalize_text(state.all_user_text) or "word" in normalize_text(state.all_user_text)) else []
        wants_personality = "personality" in text and not any(
            phrase in text for phrase in ["drop personality", "remove personality", "skip personality"]
        )
        if wants_personality and not any("opq" in normalize_text(item.name) for item in merged):
            additions.append("opq")
        if "situational" in text or "judgement" in text or "judgment" in text:
            additions.append("graduate_scenarios")

        merged += [self._product(key) for key in additions if self._product(key)]
        return dedupe_items([item for item in merged if item], limit=10)

    def _build_reply(self, state: ConversationState, items: list[CatalogItem]) -> str:
        latest = normalize_text(state.last_user_text)
        if "add a personality measure" in latest and any("opq" in normalize_text(item.name) for item in items):
            return (
                "OPQ32r is already included as the personality measure in this shortlist, so I would keep the battery unchanged. "
                "Use the cognitive and knowledge tests for the first screen, then keep OPQ32r for deeper behavioral fit validation where candidate time allows."
            )
        if state.prior_items and any(token in normalize_text(state.last_user_text) for token in ["add", "drop", "remove", "actually", "keep"]):
            return f"I updated the shortlist using your latest constraint and kept the earlier context. The current recommendation set has {len(items)} SHL catalog item(s), all grounded to catalog URLs."
        text = normalize_text(self._active_context(state))
        if "contact" in text or "call center" in text or "call centre" in text:
            return (
                "For entry-level English US inbound contact center roles, I recommend a staged assessment battery rather than a single test. "
                "Start with SVAR - Spoken English (US) to validate spoken English capability, then use Contact Center Call Simulation to observe practical call-handling behavior. "
                "For candidates who progress, add Entry Level Customer Service and Customer Service Phone Simulation to strengthen the behavioral, competency, and situational-judgment evidence. "
                "This keeps the first screen efficient while reserving the deeper fit signals for candidates who are worth more assessment time."
            )
        if "graduate" in text and ("finance" in text or "financial" in text or "analyst" in text):
            return (
                "For graduate financial analysts, I would start with numerical reasoning and finance knowledge, then add a broader work-style signal if you want a fuller graduate screen. "
                "This keeps the battery relevant for final-year students with little or no work experience."
            )
        if "rust" in text or "networking infrastructure" in text:
            return (
                "SHL's catalog does not show a Rust-specific knowledge test, so I would not present this as a direct Rust assessment. "
                "For a senior high-performance networking engineer, the closest catalog-grounded battery is Smart Interview Live Coding for role-specific coding evaluation, Linux Programming for systems depth, and Networking and Implementation for infrastructure knowledge. "
                "Because this is a senior role, Verify G+ adds reasoning evidence and OPQ32r can be used later if stakeholder behavior, ownership style, or team fit matters."
            )
        if "java" in text or "spring" in text:
            stack = ["Core Java"]
            if "spring" in text or "java" in text:
                stack.append("Spring")
            if "sql" in text or "database" in text:
                stack.append("SQL")
            if "aws" in text or "cloud" in text:
                stack.append("AWS")
            if "docker" in text or "container" in text:
                stack.append("Docker")
            stack_text = ", ".join(dict.fromkeys(stack))
            return (
                f"For this senior Java developer role, I would use a staged battery that first validates the hands-on stack and then adds broader senior-IC signals. "
                f"Core Java, Spring, SQL, AWS, and Docker cover the main technical requirements in the role context, so they should sit in the first screening layer. "
                "SHL Verify Interactive G+ is useful as a second signal because senior engineers need to reason through unfamiliar production issues, architecture tradeoffs, and ambiguous technical problems rather than only recall framework knowledge. "
                "OPQ32r is best kept as a later-stage fit measure when stakeholder collaboration, mentoring, ownership style, or team fit matter. "
                "If you need a shorter battery, I would keep Core Java, Spring, SQL, and one of AWS or Docker first, then move Verify G+ and OPQ32r to a finalist stage."
            )
        return f"I found {len(items)} SHL catalog-backed assessment(s) that match the role context. The shortlist below is ready to refine if you want to add, remove, or compare anything."

    def _active_context(self, state: ConversationState) -> str:
        latest = normalize_text(state.last_user_text)
        new_request_markers = [
            "recommend",
            "hiring",
            "screening",
            "we are screening",
            "i need",
            "what assessments",
            "assessment for",
        ]
        refinement_markers = ["add", "drop", "remove", "actually", "keep", "compare", "difference"]
        if any(marker in latest for marker in new_request_markers) and not any(marker in latest for marker in refinement_markers):
            return state.last_user_text
        return state.all_user_text

    def _response(self, reply: str, items: list[CatalogItem], end: bool) -> ChatResponse:
        safe_items = [item for item in dedupe_items(items, limit=10) if item.url in self.catalog.by_url]
        safe_items = [self.catalog.by_url[item.url] for item in safe_items]
        if safe_items:
            reply = f"{reply}\n\n{self._battery_plan(safe_items, reply)}"
        return ChatResponse(
            reply=reply,
            recommendations=[item.recommendation() for item in safe_items],
            end_of_conversation=end,
        )

    def _battery_plan(self, items: list[CatalogItem], context: str) -> str:
        strategy = infer_strategy(context)
        coverage_text = ", ".join(coverage(items)) or "Catalog match"
        return (
            f"Recommended battery design: {strategy}.\n"
            f"Coverage: {coverage_text}.\n"
            f"Estimated catalog time: {total_duration(items)}.\n"
            "Use the first-stage items for faster screening, then keep simulations, SJT, personality, or reporting products for deeper validation where relevant."
        )

    def _markdown_table(self, items: list[CatalogItem]) -> str:
        lines = [
            "| # | Name | Test Type | Keys | Duration | Languages | URL |",
            "|---|------|-----------|------|----------|-----------|-----|",
        ]
        for index, item in enumerate(items, start=1):
            keys = ", ".join(item.keys) or "-"
            languages = self._compact_languages(item.languages)
            duration = item.duration or "-"
            lines.append(
                f"| {index} | {item.name} | {item.test_type or '-'} | {keys} | {duration} | {languages} | <{item.url}> |"
            )
        return "\n".join(lines)

    def _compact_languages(self, languages: tuple[str, ...]) -> str:
        if not languages:
            return "-"
        if len(languages) <= 4:
            return ", ".join(languages)
        return f"{', '.join(languages[:4])} _(+{len(languages) - 4} more)_"
