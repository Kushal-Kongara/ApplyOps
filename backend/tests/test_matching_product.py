"""Product / AI relevance scoring tests.

Searches title + description together — a title alone saying "AI Engineer"
or "ChatGPT" is real evidence and must not score zero just because the
description happens not to repeat it.
"""

import unittest

from app.matching.product import MAX_PRODUCT_SCORE, score_product_relevance

POINTS_PER_CATEGORY = 2


class ScoreProductRelevanceTest(unittest.TestCase):
    def test_ai_engineer_title_alone_is_not_zero(self):
        result = score_product_relevance("AI Engineer\nBuild backend services.")
        self.assertGreater(result.points, 0)

    def test_applied_ai_title_alone_is_not_zero(self):
        result = score_product_relevance("Applied AI Engineer, Enterprise\nWork with customers.")
        self.assertGreater(result.points, 0)

    def test_agent_enablement_title_alone_is_not_zero(self):
        result = score_product_relevance("Software Engineer, Agent Enablement\nGeneral engineering work.")
        self.assertGreater(result.points, 0)

    def test_chatgpt_title_alone_is_not_zero(self):
        result = score_product_relevance("Full-Stack Engineer, ChatGPT Education & Learning\nBuild features.")
        self.assertGreater(result.points, 0)

    def test_generative_ai_phrase_is_recognized(self):
        result = score_product_relevance("We build generative AI products for enterprises.")
        self.assertGreater(result.points, 0)

    def test_ai_agents_and_rag_are_distinct_categories(self):
        text = "You'll build AI agents that use retrieval-augmented generation."
        result = score_product_relevance(text)
        self.assertEqual(result.points, POINTS_PER_CATEGORY * 2)

    def test_customer_facing_product_is_recognized(self):
        result = score_product_relevance("Ship customer-facing product features every week.")
        self.assertGreater(result.points, 0)

    def test_founding_engineer_and_startup_evidence(self):
        result = score_product_relevance("Founding engineer at an early-stage startup.")
        self.assertGreater(result.points, 0)

    def test_forward_deployed_and_enterprise_deployment(self):
        result = score_product_relevance("Forward deployed engineer handling enterprise deployment.")
        self.assertGreater(result.points, 0)

    def test_repeated_phrases_in_the_same_category_do_not_double_count(self):
        once = score_product_relevance("We use RAG. RAG is central. Retrieval augmented generation everywhere.")
        single_mention = score_product_relevance("We use RAG.")

        self.assertEqual(once.points, single_mention.points)

    def test_no_evidence_scores_zero(self):
        result = score_product_relevance("General backend maintenance work.")
        self.assertEqual(result.points, 0)

    def test_score_is_capped_at_max(self):
        text = (
            "AI Engineer, Applied AI. AI agents and agentic systems. LLMs and RAG. "
            "ChatGPT and generative AI. Customer-facing product. Product engineer, 0-to-1. "
            "Founding engineer at an early-stage startup. Forward deployed, enterprise deployment."
        )
        result = score_product_relevance(text)
        self.assertLessEqual(result.points, MAX_PRODUCT_SCORE)
        self.assertEqual(result.points, MAX_PRODUCT_SCORE)

    def test_evidence_lists_the_matched_category_labels(self):
        result = score_product_relevance("AI Engineer role.")
        self.assertTrue(any("ai" in label.lower() for label in result.evidence))


class AiAgentEvidenceTightenedTest(unittest.TestCase):
    """Bare 'agent'/'agentic' are too generic to count on their own."""

    def test_bare_agentic_does_not_trigger_ai_agent_evidence(self):
        result = score_product_relevance("We are building agentic systems for the future.")
        self.assertEqual(result.points, 0)

    def test_bare_agent_does_not_trigger_ai_agent_evidence(self):
        result = score_product_relevance("Work closely with our customer support agent team.")
        self.assertEqual(result.points, 0)

    def test_agentic_ai_phrase_still_counts(self):
        result = score_product_relevance("We build agentic AI systems.")
        self.assertGreater(result.points, 0)

    def test_ai_agent_phrase_still_counts(self):
        result = score_product_relevance("Design and ship AI agent workflows.")
        self.assertGreater(result.points, 0)

    def test_ai_agents_plural_phrase_still_counts(self):
        result = score_product_relevance("Build AI agents that automate support.")
        self.assertGreater(result.points, 0)

    def test_llm_agent_phrase_still_counts(self):
        result = score_product_relevance("You'll build an LLM agent for internal tooling.")
        self.assertGreater(result.points, 0)

    def test_llm_agents_plural_phrase_still_counts(self):
        result = score_product_relevance("Own our fleet of LLM agents.")
        self.assertGreater(result.points, 0)

    def test_autonomous_agent_phrase_still_counts(self):
        result = score_product_relevance("Build an autonomous agent that plans multi-step tasks.")
        self.assertGreater(result.points, 0)

    def test_agent_workflow_phrase_still_counts(self):
        result = score_product_relevance("Design robust agent workflows for our platform.")
        self.assertGreater(result.points, 0)

    def test_agent_enablement_phrase_still_counts(self):
        result = score_product_relevance("Software Engineer, Agent Enablement")
        self.assertGreater(result.points, 0)


if __name__ == "__main__":
    unittest.main()
