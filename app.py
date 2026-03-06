import json
import os
import re
import sys
import time

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def is_timeout_error(error: Exception) -> bool:
    message = str(error).lower()
    retryable_markers = [
        "request timed out",
        "connecttimeout",
        "timed out",
        "circuit breaker has opened",
        "please retry after a short delay",
        "repeated transient failures while enumerating tools",
    ]
    return any(marker in message for marker in retryable_markers)


def run_agent_with_retry(
    openai_client,
    *,
    agent_name: str,
    agent_version: str,
    user_message: str,
    max_retries: int = 2,
):
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = openai_client.responses.create(
                input=[{"role": "user", "content": user_message}],
                extra_body={
                    "agent": {
                        "name": agent_name,
                        "version": agent_version,
                        "type": "agent_reference",
                    }
                },
            )
            return response.output_text
        except Exception as error:
            last_error = error
            if not is_timeout_error(error) or attempt == max_retries:
                raise
            wait_seconds = attempt + 1
            print(f"Agent: Temporärer Verbindungs-/Tool-Fehler. Neuer Versuch in {wait_seconds}s ...")
            time.sleep(wait_seconds)

    if last_error is not None:
        raise last_error


def get_latest_agent_version(project_client: AIProjectClient, agent_name: str) -> str | None:
    versions = project_client.agents.list_versions(agent_name=agent_name, limit=1, order="desc")
    latest = next(iter(versions), None)
    if latest is None:
        return None
    return str(latest.version)


def extract_handover_json(text: str) -> dict | None:
    stripped = text.strip()

    # Support direct JSON payload responses.
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Support fenced JSON blocks.
    match = re.search(r"```json\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # Fallback: extract first JSON object from mixed text.
    match = re.search(r"(\{.*\})", stripped, flags=re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    return None


def resolve_helper_agent(handover: dict, project_client: AIProjectClient) -> tuple[str, str] | None:
    detected = str(handover.get("detected_agent", "")).lower()
    mapping: dict[str, tuple[str, str | None]] = {
        "reinigung": (
            require_env("DB_CLEANING_AGENT_NAME"),
            os.getenv("DB_CLEANING_AGENT_VERSION"),
        ),
        "sicherheit": (
            require_env("DB_SECURITY_AGENT_NAME"),
            os.getenv("DB_SECURITY_AGENT_VERSION"),
        ),
        "technik": (
            require_env("DB_TECHNIK_AGENT_NAME"),
            os.getenv("DB_TECHNIK_AGENT_VERSION"),
        ),
        "bistro": (
            require_env("DB_BISTRO_AGENT_NAME"),
            os.getenv("DB_BISTRO_AGENT_VERSION"),
        ),
    }
    helper = mapping.get(detected)
    if not helper:
        return None

    helper_name, helper_version = helper
    resolved_version = helper_version or get_latest_agent_version(project_client, helper_name)
    if not resolved_version:
        return None
    return helper_name, resolved_version


def main() -> None:
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)

    endpoint = require_env("AZURE_AI_PROJECT_ENDPOINT")
    orchestrator_agent_name = require_env("DB_ORCHESTRATOR_AGENT_NAME")
    orchestrator_agent_version = os.getenv("DB_ORCHESTRATOR_AGENT_VERSION")
    service_agent_name = require_env("DB_SERVICE_AGENT_NAME")
    service_agent_version = os.getenv("DB_SERVICE_AGENT_VERSION")

    concern = " ".join(sys.argv[1:]).strip()
    if not concern:
        concern = input("Bitte beschreiben Sie Ihr Anliegen: ").strip()

    if not concern:
        concern = "Im Wagen ist es sehr heiß und die Klimaanlage scheint defekt."

    project_client = AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    )
    openai_client = project_client.get_openai_client()

    if not orchestrator_agent_version:
        orchestrator_agent_version = get_latest_agent_version(project_client, orchestrator_agent_name)
    if not orchestrator_agent_version:
        raise RuntimeError(
            "Could not resolve DB_ORCHESTRATOR_AGENT_VERSION and no latest orchestrator version was found."
        )

    if not service_agent_version:
        service_agent_version = get_latest_agent_version(project_client, service_agent_name)
    if not service_agent_version:
        raise RuntimeError("Could not resolve DB_SERVICE_AGENT_VERSION and no latest service-agent version was found.")

    try:
        orchestrator_response = run_agent_with_retry(
            openai_client,
            agent_name=orchestrator_agent_name,
            agent_version=orchestrator_agent_version,
            user_message=concern,
        )

        handover_payload = extract_handover_json(orchestrator_response)
        if not handover_payload:
            print(f"Agent: {orchestrator_response}")
            return

        helper_agent = resolve_helper_agent(handover_payload, project_client)
        if not helper_agent:
            return

        helper_name, helper_version = helper_agent
        helper_input = (
            "Orchestrator handoff payload:\n"
            f"{json.dumps(handover_payload, ensure_ascii=False)}"
        )
        helper_response = run_agent_with_retry(
            openai_client,
            agent_name=helper_name,
            agent_version=helper_version,
            user_message=helper_input,
        )

        service_input = (
            "User concern:\n"
            f"{concern}\n\n"
            "Orchestrator handoff payload:\n"
            f"{json.dumps(handover_payload, ensure_ascii=False)}\n\n"
            "Helper agent response:\n"
            f"{helper_response}"
        )
        service_response = run_agent_with_retry(
            openai_client,
            agent_name=service_agent_name,
            agent_version=service_agent_version,
            user_message=service_input,
        )
        print(f"Agent: {service_response}")
    except Exception as error:
        if is_timeout_error(error):
            print("Agent: Temporärer Dienstfehler (z. B. Timeout/Circuit-Breaker). Bitte in 1-2 Minuten erneut versuchen.")
            return
        raise


if __name__ == "__main__":
    main()