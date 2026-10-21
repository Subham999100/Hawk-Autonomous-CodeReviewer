import logging
from typing import Any, Dict
import httpx

from app.core.config import settings

logger = logging.getLogger("hawk.jev")


async def orchestrate_investigation_triage(
    objective: str,
    repository_name: str,
    tree_sample: list[str],
) -> Dict[str, Any]:
    """
    Integrates with TypeSafe AI Jev System One decision API (POST /v1/systemone).
    Provides rapid operational triage, question-based classification, and risk scoring
    to bound downstream LLM reasoning and file retrieval.
    """
    api_key = settings.jev_api_key.strip() if settings.jev_api_key else ""

    state_payload = {
        "objective": objective,
        "repository": repository_name,
        "file_paths_sample": tree_sample[:25],
    }

    questions_payload = {
        "investigation_scope": {
            "type": "choice",
            "instructions": "Determine the optimal engineering investigation strategy for this task",
            "options": [
                "standard_code_review",
                "performance_bottleneck",
                "security_vulnerability",
                "architectural_defect",
            ],
        },
        "requires_deep_retrieval": {
            "type": "noul",
            "instructions": "Does this investigation objective warrant retrieving the full file content budget?",
        },
        "complexity_score": {
            "type": "score",
            "instructions": "Rate the technical complexity and systemic impact of the reported engineering problem",
            "levels": ["low", "medium", "high", "critical"],
        },
    }

    if not api_key:
        logger.info("JEV_API_KEY is not configured; using deterministic rule-based triage heuristic.")
        return _fallback_triage(objective, repository_name, tree_sample)

    url = settings.jev_api_base_url
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.jev_model,
        "state": state_payload,
        "questions": questions_payload,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=body, headers=headers)

        if response.status_code == 200:
            data = response.json()
            logger.info("Jev System One decision received successfully: %s", data.get("answers", {}))
            return {
                "provider": "typesafe_jev",
                "model": settings.jev_model,
                "answers": data.get("answers", data),
                "status": "success",
            }
        else:
            logger.warning(
                "Jev API responded with status %d: %s. Using heuristic fallback.",
                response.status_code,
                response.text,
            )
            fallback = _fallback_triage(objective, repository_name, tree_sample)
            fallback["warning"] = f"Jev API error {response.status_code}"
            return fallback

    except Exception as exc:
        logger.warning("Failed to reach Jev System One API (%s). Using fallback triage.", str(exc))
        fallback = _fallback_triage(objective, repository_name, tree_sample)
        fallback["warning"] = f"Jev connection failed: {str(exc)}"
        return fallback


def _fallback_triage(objective: str, repository_name: str, tree_sample: list[str]) -> Dict[str, Any]:
    obj_lower = objective.lower()
    if any(k in obj_lower for k in ["slow", "latency", "memory", "cpu", "bottleneck", "timeout", "oom"]):
        scope = "performance_bottleneck"
        complexity = "medium"
    elif any(k in obj_lower for k in ["security", "auth", "token", "cve", "vulnerability", "secret", "credential"]):
        scope = "security_vulnerability"
        complexity = "high"
    elif any(k in obj_lower for k in ["architecture", "refactor", "design", "scale"]):
        scope = "architectural_defect"
        complexity = "high"
    else:
        scope = "standard_code_review"
        complexity = "low"

    return {
        "provider": "deterministic_heuristic",
        "model": "rule_engine_v1",
        "answers": {
            "investigation_scope": {
                "decision": scope,
                "confidence": 0.88,
            },
            "requires_deep_retrieval": {
                "probability": 0.92,
                "decision": True,
            },
            "complexity_score": {
                "level": complexity,
                "score": 0.75,
            },
        },
        "status": "fallback",
    }
