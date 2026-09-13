"""Static alias tables used by title, skill, and location scoring.

Every list here is written in `normalize_text()` form (lowercase, no
punctuation) so it can be compared directly against normalized job text.
Keeping these as data — not scattered regexes — is what makes it possible to
extend Phase 2 (new role, new skill, new city) without touching scoring
logic.
"""

from app.matching.text import normalize_text

# --- Title role families -----------------------------------------------
#
# Each family is a set of phrasings that mean the same role. `full_stack`
# covers "full-stack", "full stack", and "fullstack" alike. `software_engineer`
# is deliberately kept separate: it is a real, wanted title, but it's also
# the generic bucket every other engineering title also technically belongs
# to, so it is scored lower than a specific match (see matching/titles.py).
ROLE_FAMILIES: dict[str, list[str]] = {
    "full_stack": ["full stack", "fullstack"],
    "front_end": ["front end", "frontend"],
    "back_end": ["back end", "backend"],
    "forward_deployed": ["forward deployed"],
    "founding_engineer": ["founding engineer"],
    "product_engineer": ["product engineer"],
    "applied_ai": ["applied ai"],
    "ai_engineer": ["ai engineer"],
    "software_engineer": ["software engineer", "software developer"],
}
ROLE_FAMILIES = {key: [normalize_text(p) for p in phrases] for key, phrases in ROLE_FAMILIES.items()}

GENERIC_ENGINEERING_MARKERS = [
    normalize_text(term)
    for term in ("engineer", "engineering", "developer", "programmer", "swe")
]

# Built-in management/leadership exclusion — checked regardless of what a
# profile's own `excluded_title_terms` happens to list, so a title like
# "Manager, Applied AI Engineering" (word order defeats a literal
# "engineering manager" phrase match) still gets caught. Deliberately does
# NOT include "lead" — a Lead/Technical Lead title is often still an IC
# role, not a management one.
MANAGEMENT_TITLE_MARKERS = [
    normalize_text(term)
    for term in ("manager", "engineering manager", "director", "vice president", "vp", "head of")
]

# --- Skills ---------------------------------------------------------------
#
# Canonical skill name -> every normalized phrase that counts as evidence of
# it. A skill not listed here still works: score_skills() falls back to the
# skill's own normalized name as its only alias, so an arbitrary profile
# skill never needs a code change.
SKILL_ALIASES: dict[str, list[str]] = {
    "React": ["react", "react js", "reactjs"],
    "TypeScript": ["typescript", "ts"],
    "JavaScript": ["javascript", "js"],
    "Node.js": ["node js", "nodejs", "node"],
    "NestJS": ["nestjs", "nest js"],
    "Python": ["python"],
    "Java": ["java"],
    "SQL": ["sql"],
    "PostgreSQL": ["postgresql", "postgres"],
    "Prisma": ["prisma"],
    "REST APIs": ["rest api", "rest apis", "restful api", "restful apis"],
    "AWS": ["aws", "amazon web services"],
    "ECS": ["ecs"],
    "Fargate": ["fargate"],
    "RDS": ["rds"],
    "S3": ["s3"],
    "CloudFront": ["cloudfront"],
    "Docker": ["docker"],
    "GitHub Actions": ["github actions"],
    "CI/CD": ["ci cd", "cicd", "continuous integration"],
    "LLMs": ["llm", "llms", "large language model", "large language models"],
    "AI Agents": ["ai agent", "ai agents"],
    "RAG": ["rag", "retrieval augmented generation"],
    "Prompt Engineering": ["prompt engineering"],
    "Vapi": ["vapi"],
    "ElevenLabs": ["elevenlabs", "eleven labs"],
}
SKILL_ALIASES = {name: [normalize_text(p) for p in phrases] for name, phrases in SKILL_ALIASES.items()}

# --- Locations --------------------------------------------------------------
#
# Small, finite gazetteers, not an exhaustive geocoder — see docs/phase-02
# "known limitations" for what that trades away.
US_STATE_ABBREVIATIONS = [
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "dc", "fl", "ga", "hi", "id",
    "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo",
    "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa",
    "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
]
US_PLACE_NAMES = [
    "california", "new york", "washington", "seattle", "texas", "massachusetts",
    "illinois", "colorado", "georgia", "florida", "oregon", "north carolina",
    "pennsylvania", "virginia", "los angeles", "san diego", "santa monica",
    "chicago", "austin", "boston", "denver", "atlanta", "miami", "houston",
    "dallas", "portland", "philadelphia", "phoenix", "salt lake city",
    "nashville", "raleigh", "minneapolis", "detroit", "charlotte",
    "united states", "usa", "us",
]
US_LOCATION_MARKERS = [normalize_text(m) for m in (US_STATE_ABBREVIATIONS + US_PLACE_NAMES)]

INTERNATIONAL_PLACE_NAMES = [
    "india", "canada", "ontario", "toronto", "vancouver", "montreal", "uk",
    "united kingdom", "london", "ireland", "dublin", "germany", "munich",
    "berlin", "france", "paris", "japan", "tokyo", "singapore", "australia",
    "sydney", "south korea", "seoul", "brazil", "sao paulo", "mexico",
    "poland", "warsaw", "sweden", "stockholm", "switzerland", "zurich",
    "spain", "madrid", "portugal", "lisbon", "netherlands", "amsterdam",
    "emea", "apac", "latam", "philippines", "manila", "china", "beijing",
    "shanghai", "hong kong", "taiwan", "taipei", "vietnam", "indonesia",
    "italy", "rome", "austria", "vienna", "belgium", "brussels", "denmark",
    "copenhagen", "norway", "oslo", "finland", "helsinki", "israel",
    "tel aviv", "uae", "dubai", "south africa", "new zealand", "auckland",
    "mumbai", "delhi", "bangalore",
]
INTERNATIONAL_LOCATION_MARKERS = [normalize_text(m) for m in INTERNATIONAL_PLACE_NAMES]

# --- Product / AI relevance evidence ---------------------------------------
#
# Each category is a distinct kind of evidence, searched over *title +
# description* together — a title alone saying "AI Engineer" or "ChatGPT"
# is real evidence, not something this component ignores. Matching more
# than one phrase within the same category still only counts once (see
# matching/product.py): the score reflects how many distinct kinds of
# relevant evidence exist, not how many synonyms happened to appear.
PRODUCT_EVIDENCE_CATEGORIES: dict[str, list[str]] = {
    "AI role (AI/applied-AI engineer)": ["ai engineer", "applied ai", "ai engineering"],
    # Bare "agent"/"agentic" are too generic (real-estate agent, customer
    # service agent, "agentic" used loosely) to count on their own — every
    # phrase here specifically ties the word to AI/LLM agent systems.
    "AI agents / agentic systems": [
        "agentic ai", "ai agent", "ai agents", "llm agent", "llm agents",
        "autonomous agent", "agent workflow", "agent workflows", "agent enablement",
    ],
    "LLMs / RAG": [
        "llm", "llms", "large language model", "large language models",
        "rag", "retrieval augmented generation",
    ],
    "generative AI / ChatGPT": ["chatgpt", "generative ai", "gen ai"],
    "customer-facing product": ["customer facing", "customer-facing"],
    "product ownership (0-to-1 / full-stack)": [
        "product engineer", "full stack ownership", "own the full stack", "end to end ownership",
        "0 to 1", "zero to one", "greenfield",
    ],
    "startup / founding environment": [
        "startup", "founding team", "founding engineer", "early stage", "seed stage", "series a",
    ],
    "forward-deployed / enterprise deployment": [
        "forward deployed", "customer implementation", "solutions engineering",
        "professional services", "enterprise deployment",
    ],
}
PRODUCT_EVIDENCE_CATEGORIES = {
    label: [normalize_text(p) for p in phrases] for label, phrases in PRODUCT_EVIDENCE_CATEGORIES.items()
}
