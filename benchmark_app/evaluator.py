"""
Evaluator: LLM-as-judge for benchmark answers
==============================================

Given a question, a reference answer with key_points, and a candidate answer,
score the candidate on:
- coverage: which key_points are mentioned (0-1 per key_point)
- factual_correctness: are the claims correct given the reference (0-1)
- relevance: does it answer the question asked (0-1)
- overall: weighted combination

Uses Claude as the judge with a structured prompt that forces JSON output.
"""

import json
import re
from dataclasses import dataclass, field, asdict


@dataclass
class EvalResult:
    question_id: str
    coverage_score: float = 0.0      # fraction of key_points covered (0-1)
    correctness_score: float = 0.0   # 0-1, factual alignment with reference
    relevance_score: float = 0.0     # 0-1, does it answer the question
    overall_score: float = 0.0       # weighted combination 0-1
    key_points_covered: list[str] = field(default_factory=list)
    key_points_missed: list[str] = field(default_factory=list)
    judge_notes: str = ""
    error: str = ""


JUDGE_PROMPT = """You are an expert evaluator of answers about hydrologic modeling. You will compare a CANDIDATE answer against a REFERENCE answer and a list of KEY POINTS that any good answer should cover.

Be strict but fair. Surface-level matches don't count — the candidate must show actual understanding.

QUESTION:
{question}

REFERENCE ANSWER (ground truth):
{reference}

KEY POINTS the candidate should cover:
{key_points}

CANDIDATE ANSWER (to evaluate):
{candidate}

Evaluate the candidate on three dimensions, each 0.0 to 1.0:

1. coverage: For each key point, is it addressed by the candidate? Coverage = (key points covered) / (total key points). A key point is "covered" if the candidate mentions the concept clearly, not just a similar word.

2. correctness: Are the technical claims in the candidate factually consistent with the reference? 1.0 = all consistent, 0.5 = mix of correct and incorrect, 0.0 = mostly wrong.

3. relevance: Does the candidate actually answer the question asked, or does it drift? 1.0 = directly addresses, 0.0 = off-topic.

Then produce overall = 0.4 * coverage + 0.4 * correctness + 0.2 * relevance.

For each key point, decide if it was covered. List the covered and missed ones separately.

OUTPUT FORMAT — respond with ONLY a JSON object, no other text:

{{
  "coverage_score": 0.0,
  "correctness_score": 0.0,
  "relevance_score": 0.0,
  "overall_score": 0.0,
  "key_points_covered": ["point text here", ...],
  "key_points_missed": ["point text here", ...],
  "judge_notes": "1-2 sentences explaining the score, in the same language as the question"
}}"""


def evaluate_answer(
    question_id: str,
    question: str,
    reference: str,
    key_points: list[str],
    candidate: str,
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
) -> EvalResult:
    """Run the LLM-as-judge on a single answer."""
    # Import here to keep the module importable even without anthropic installed
    import anthropic

    if not candidate or not candidate.strip():
        return EvalResult(
            question_id=question_id,
            judge_notes="Empty candidate answer.",
        )

    key_points_str = "\n".join(f"- {kp}" for kp in key_points)
    prompt = JUDGE_PROMPT.format(
        question=question,
        reference=reference,
        key_points=key_points_str,
        candidate=candidate,
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(b.text for b in response.content if hasattr(b, "text"))

        # Extract JSON — tolerate markdown code fences or stray text around it
        raw = raw.strip()
        # Strip ```json ... ``` fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        # If there's text around the JSON, grab the first {...} block
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            raw = match.group(0)

        data = json.loads(raw)

        return EvalResult(
            question_id=question_id,
            coverage_score=float(data.get("coverage_score", 0.0)),
            correctness_score=float(data.get("correctness_score", 0.0)),
            relevance_score=float(data.get("relevance_score", 0.0)),
            overall_score=float(data.get("overall_score", 0.0)),
            key_points_covered=list(data.get("key_points_covered", [])),
            key_points_missed=list(data.get("key_points_missed", [])),
            judge_notes=str(data.get("judge_notes", "")),
        )
    except json.JSONDecodeError as e:
        return EvalResult(
            question_id=question_id,
            error=f"JSON parse error: {e}. Raw: {raw[:200]}",
        )
    except Exception as e:
        return EvalResult(
            question_id=question_id,
            error=f"{type(e).__name__}: {e}",
        )


def aggregate_results(results: list[EvalResult]) -> dict:
    """Summary statistics over a list of eval results."""
    valid = [r for r in results if not r.error]
    if not valid:
        return {
            "n": 0,
            "n_errors": len(results),
            "mean_overall": 0.0,
            "mean_coverage": 0.0,
            "mean_correctness": 0.0,
            "mean_relevance": 0.0,
        }
    n = len(valid)
    return {
        "n": n,
        "n_errors": len(results) - n,
        "mean_overall": sum(r.overall_score for r in valid) / n,
        "mean_coverage": sum(r.coverage_score for r in valid) / n,
        "mean_correctness": sum(r.correctness_score for r in valid) / n,
        "mean_relevance": sum(r.relevance_score for r in valid) / n,
    }
