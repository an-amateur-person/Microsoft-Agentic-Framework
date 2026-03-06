import json
import os
import re
from pathlib import Path

import streamlit as st
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
DBSERVICE_ICON = ASSETS_DIR / "DBService.png"

HELPER_ICON_BY_DETECTED_AGENT = {
    "reinigung": ASSETS_DIR / "DBReinigung.png",
    "sicherheit": ASSETS_DIR / "DBSicherheit.png",
    "technik": ASSETS_DIR / "DBTechnik.png",
    "bistro": ASSETS_DIR / "DBBistro.png",
}


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def run_agent_with_retry(
    openai_client,
    *,
    agent_name: str,
    agent_version: str,
    user_message: str,
    max_retries: int = 2,
) -> str:
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


def get_latest_agent_version(project_client: AIProjectClient, agent_name: str) -> str:
    versions = project_client.agents.list_versions(agent_name=agent_name, limit=1, order="desc")
    latest = next(iter(versions), None)
    if latest is None:
        raise RuntimeError(f"Could not resolve latest version for agent '{agent_name}'")
    return str(latest.version)


def extract_handover_json(text: str) -> dict | None:
    stripped = text.strip()

    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"```json\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    match = re.search(r"(\{.*\})", stripped, flags=re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    return None


def resolve_helper_agent(handover: dict, project_client: AIProjectClient) -> tuple[str, str, str] | None:
    detected = str(handover.get("detected_agent", "")).lower()
    mapping: dict[str, tuple[str, str | None]] = {
        "reinigung": (require_env("DB_CLEANING_AGENT_NAME"), os.getenv("DB_CLEANING_AGENT_VERSION")),
        "sicherheit": (require_env("DB_SECURITY_AGENT_NAME"), os.getenv("DB_SECURITY_AGENT_VERSION")),
        "technik": (require_env("DB_TECHNIK_AGENT_NAME"), os.getenv("DB_TECHNIK_AGENT_VERSION")),
        "bistro": (require_env("DB_BISTRO_AGENT_NAME"), os.getenv("DB_BISTRO_AGENT_VERSION")),
    }

    helper = mapping.get(detected)
    if not helper:
        return None

    helper_name, helper_version = helper
    resolved_version = helper_version or get_latest_agent_version(project_client, helper_name)
    return helper_name, resolved_version, detected


def get_icon_path(path: Path) -> str | None:
    if not path.exists():
        return None
    return str(path)


def clean_agent_text(text: str) -> str:
    # Remove fenced payload so users see natural language first.
    return re.sub(r"```json\s*\{.*?\}\s*```", "", text, flags=re.DOTALL).strip()


def get_icon_path_for_detected_agent(detected_agent: str) -> str | None:
    icon_path = HELPER_ICON_BY_DETECTED_AGENT.get(detected_agent)
    if not icon_path or not icon_path.exists():
        return None
    return str(icon_path)


def get_clients() -> tuple[AIProjectClient, object]:
    if "project_client" not in st.session_state or "openai_client" not in st.session_state:
        endpoint = require_env("AZURE_AI_PROJECT_ENDPOINT")
        project_client = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
        openai_client = project_client.get_openai_client()
        st.session_state.project_client = project_client
        st.session_state.openai_client = openai_client
    return st.session_state.project_client, st.session_state.openai_client


def add_message(role: str, content: str, avatar: str | None = None) -> None:
    st.session_state.messages.append({"role": role, "content": content, "avatar": avatar})


def render_history() -> None:
    for message in st.session_state.messages:
        with st.chat_message(message["role"], avatar=message.get("avatar")):
            st.markdown(message["content"])


def main() -> None:
    load_dotenv(BASE_DIR / ".env", override=False)

    st.set_page_config(page_title="DB Service Assistant", page_icon="DB", layout="centered")
    st.title("DB Service Assistant")
    st.caption("Report concerns. Orchestrator routes helpers, DBService responds to users.")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    render_history()

    concern = st.chat_input("Describe your concern...")
    if not concern:
        return

    add_message("user", concern)
    with st.chat_message("user"):
        st.markdown(concern)

    try:
        project_client, openai_client = get_clients()
        orchestrator_agent_name = require_env("DB_ORCHESTRATOR_AGENT_NAME")
        orchestrator_agent_version = os.getenv("DB_ORCHESTRATOR_AGENT_VERSION") or get_latest_agent_version(
            project_client, orchestrator_agent_name
        )
        service_agent_name = require_env("DB_SERVICE_AGENT_NAME")
        service_agent_version = os.getenv("DB_SERVICE_AGENT_VERSION") or get_latest_agent_version(
            project_client, service_agent_name
        )

        orchestrator_response = run_agent_with_retry(
            openai_client,
            agent_name=orchestrator_agent_name,
            agent_version=orchestrator_agent_version,
            user_message=concern,
        )

        handover_payload = extract_handover_json(orchestrator_response)
        if not handover_payload:
            return

        helper_agent = resolve_helper_agent(handover_payload, project_client)
        if not helper_agent:
            return

        helper_name, helper_version, detected_agent = helper_agent
        helper_input = (
            "DBService handoff payload:\n" f"{json.dumps(handover_payload, ensure_ascii=False)}"
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

        dbservice_avatar = get_icon_path(DBSERVICE_ICON)
        service_text = clean_agent_text(service_response) or service_response
        add_message("assistant", f"**DBService**\n\n{service_text}", avatar=dbservice_avatar)
        with st.chat_message("assistant", avatar=dbservice_avatar):
            st.markdown(f"**DBService**\n\n{service_text}")

        avatar = get_icon_path_for_detected_agent(detected_agent)
        helper_title = detected_agent.capitalize()
        helper_text = f"**{helper_title} ({helper_name})**\n\n{helper_response}"
        add_message("assistant", helper_text, avatar=avatar)
        with st.chat_message("assistant", avatar=avatar):
            st.markdown(helper_text)

    except Exception:
        raise


if __name__ == "__main__":
    main()
