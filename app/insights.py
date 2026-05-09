from app.catalog import CatalogItem, normalize_text


def infer_strategy(text: str) -> str:
    lower = normalize_text(text)
    if any(term in lower for term in ["senior", "finalist", "deep dive", "senior ic"]):
        return "Finalist deep dive"
    if any(term in lower for term in ["volume", "screening", "screen 500", "entry level", "entry-level"]):
        return "High-volume screening"
    if any(term in lower for term in ["graduate", "trainee", "final year", "final-year"]):
        return "Graduate hiring"
    if any(term in lower for term in ["leadership", "executive", "director", "cxo"]):
        return "Leadership selection"
    if any(term in lower for term in ["reskill", "re skill", "development", "audit"]):
        return "Development and reskilling"
    return "Role-fit shortlist"


def stage_for(item: CatalogItem, context: str) -> str:
    lower = normalize_text(context)
    name = normalize_text(item.name)
    keys = " ".join(item.keys)
    if any(term in name for term in ["svar", "verify", "numerical", "ms excel", "ms word"]) or "Knowledge & Skills" in keys:
        return "Stage 1: Screen"
    if any(term in name for term in ["simulation", "scenarios", "phone"]):
        return "Stage 2: Work sample"
    if "Personality & Behavior" in keys or "Competencies" in keys:
        return "Stage 3: Fit validation"
    if "report" in name or "development" in lower:
        return "Stage 3: Reporting"
    return "Stage 2: Validate"


def score_item(item: CatalogItem, context: str) -> int:
    lower = normalize_text(context)
    haystack = normalize_text(item.searchable_text)
    score = 58
    for token in set(lower.split()):
        if len(token) > 2 and token in haystack:
            score += 3
    if "english us" in lower or "english usa" in lower or "us" in lower:
        if any("English (USA)" == lang for lang in item.languages):
            score += 8
    if "entry" in lower and any("Entry-Level" == level for level in item.job_levels):
        score += 6
    if "graduate" in lower and any("Graduate" == level for level in item.job_levels):
        score += 6
    if "senior" in lower and any(level in item.job_levels for level in ["Mid-Professional", "Professional Individual Contributor"]):
        score += 5
    if "simulation" in lower and "Simulations" in item.keys:
        score += 6
    if ("personality" in lower or "fit" in lower) and "Personality & Behavior" in item.keys:
        score += 6
    return max(55, min(score, 97))


def why_fit(item: CatalogItem, context: str) -> str:
    lower = normalize_text(context)
    name = normalize_text(item.name)
    if "svar" in name:
        return "Checks spoken English capability before candidates move into a longer contact-center workflow."
    if "contact center call simulation" in name:
        return "Adds a realistic call-handling work sample for inbound customer interactions."
    if "customer service phone simulation" in name:
        return "Useful as a deeper finalist validation because it includes phone-simulation evidence."
    if "entry level customer" in name:
        return "Covers customer-service behavioral fit and competencies for entry-level service roles."
    if "core java" in name:
        return "Targets the primary Java capability needed for backend engineering work."
    if "spring" in name:
        return "Matches the Spring framework requirement in the role description."
    if "sql" in name:
        return "Covers relational database knowledge that appears as a core role requirement."
    if "aws" in name:
        return "Adds cloud deployment coverage for AWS-heavy roles."
    if "docker" in name:
        return "Adds containerization coverage for cloud-native or microservice work."
    if "verify" in name:
        return "Adds a reasoning signal beyond learned technical knowledge."
    if "opq" in name:
        return "Adds workplace behavior evidence when fit, stakeholder work, or senior ownership matters."
    if "graduate scenarios" in name:
        return "Adds graduate-level situational judgment for work-context decision making."
    if "numerical" in name:
        return "Matches analytical or finance roles where numerical reasoning is important."
    if "financial accounting" in name:
        return "Provides domain knowledge coverage for finance analyst tasks."
    if item.description:
        return item.description[:180].rstrip() + "."
    return f"Matches the requested context through catalog category: {', '.join(item.keys)}."


def caution_for(item: CatalogItem, context: str) -> str:
    lower = normalize_text(context)
    if "short" in lower and item.duration and any(num in item.duration for num in ["25", "30", "35", "36"]):
        return "Longer than a lightweight screen; consider using it later in the funnel."
    if not item.languages:
        return "Language availability is not listed in the scraped catalog entry."
    if "english" in lower and "English (USA)" not in item.languages and "English International" not in item.languages:
        return "Check language fit before using this in an English workflow."
    return "No major catalog constraint detected."


def coverage(items: list[CatalogItem]) -> list[str]:
    mapping = {
        "Knowledge & Skills": "Job knowledge",
        "Simulations": "Work sample",
        "Ability & Aptitude": "Cognitive ability",
        "Personality & Behavior": "Behavioral fit",
        "Biodata & Situational Judgment": "Situational judgment",
        "Competencies": "Competencies",
        "Development & 360": "Development reporting",
    }
    seen: list[str] = []
    for item in items:
        for key in item.keys:
            label = mapping.get(key)
            if label and label not in seen:
                seen.append(label)
    return seen


def total_duration(items: list[CatalogItem]) -> str:
    minutes = 0
    unknown = False
    for item in items:
        digits = "".join(ch if ch.isdigit() else " " for ch in item.duration).split()
        if digits:
            minutes += int(digits[0])
        else:
            unknown = True
    if minutes and unknown:
        return f"About {minutes}+ minutes"
    if minutes:
        return f"About {minutes} minutes"
    return "Varies by assessment"


def build_detail(item: CatalogItem, context: str) -> dict:
    return {
        "name": item.name,
        "url": item.url,
        "test_type": item.test_type,
        "stage": stage_for(item, context),
        "fit_score": score_item(item, context),
        "why_fit": why_fit(item, context),
        "caution": caution_for(item, context),
        "duration": item.duration or "-",
        "keys": list(item.keys),
        "languages": list(item.languages[:6]),
    }
