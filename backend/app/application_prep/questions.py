"""The default standard application question packet.

This phase doesn't scrape a real ATS form yet (see the phase spec) — this
fixed packet exists so the answering engine itself can be built and tested.
A custom question can also be added manually; both go through the exact
same resolution engine in `app/application_prep/resolver.py`, dispatched by
`category`.
"""

from app.application_prep.models import QuestionSpec

DEFAULT_QUESTIONS: list[QuestionSpec] = [
    QuestionSpec(id="full_name", question_text="Full name", question_type="text", category="identity"),
    QuestionSpec(id="email", question_text="Email", question_type="text", category="contact"),
    QuestionSpec(id="phone", question_text="Phone", question_type="text", category="contact"),
    QuestionSpec(id="location", question_text="Location", question_type="text", category="location"),
    QuestionSpec(id="linkedin", question_text="LinkedIn", question_type="text", category="identity", required=False),
    QuestionSpec(id="github", question_text="GitHub", question_type="text", category="identity", required=False),
    QuestionSpec(id="portfolio", question_text="Portfolio", question_type="text", category="identity", required=False),
    QuestionSpec(
        id="work_authorization", question_text="Are you authorized to work in your target country?",
        question_type="boolean", category="work_authorization",
    ),
    QuestionSpec(
        id="sponsorship_now", question_text="Do you require sponsorship to work now?",
        question_type="boolean", category="sponsorship",
    ),
    QuestionSpec(
        id="sponsorship_future", question_text="Will you require sponsorship in the future?",
        question_type="boolean", category="sponsorship",
    ),
    QuestionSpec(id="relocation", question_text="Are you willing to relocate?", question_type="text", category="relocation"),
    QuestionSpec(
        id="availability", question_text="When are you available to start?",
        question_type="text", category="availability",
    ),
    QuestionSpec(
        id="salary_expectation", question_text="What is your salary expectation?",
        question_type="text", category="salary", required=False,
    ),
    QuestionSpec(
        id="relevant_experience_summary", question_text="Describe your most relevant experience for this role.",
        question_type="textarea", category="experience",
    ),
    QuestionSpec(id="why_role", question_text="Why are you interested in this role?", question_type="textarea", category="role_motivation"),
    QuestionSpec(id="why_company", question_text="Why this company?", question_type="textarea", category="company_motivation"),
]
