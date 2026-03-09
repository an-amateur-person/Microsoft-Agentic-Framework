import json
import os
import re
from base64 import b64encode
from pathlib import Path

import streamlit as st
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from openai import APIConnectionError, APIError, APITimeoutError, OpenAI


BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
DBSERVICE_ICON = ASSETS_DIR / "DBService.png"
ORCHESTRATOR_LABEL = "orchestrator"
DBSERVICE_LABEL = "dbservice"

AGENT_NAME_BY_KEY = {
    ORCHESTRATOR_LABEL: "Orchestrator",
    DBSERVICE_LABEL: "DBService",
    "reinigung": "Reinigung",
    "sicherheit": "Sicherheit",
    "technik": "Technik",
    "bistro": "Bistro",
}

AGENT_ICON_BY_KEY = {
    DBSERVICE_LABEL: DBSERVICE_ICON,
    "reinigung": ASSETS_DIR / "DBReinigung.png",
    "sicherheit": ASSETS_DIR / "DBSicherheit.png",
    "technik": ASSETS_DIR / "DBTechnik.png",
    "bistro": ASSETS_DIR / "DBBistro.png",
}

HELPER_ICON_BY_DETECTED_AGENT = {
    "reinigung": ASSETS_DIR / "DBReinigung.png",
    "sicherheit": ASSETS_DIR / "DBSicherheit.png",
    "technik": ASSETS_DIR / "DBTechnik.png",
    "bistro": ASSETS_DIR / "DBBistro.png",
}


def is_identity_only_mode() -> bool:
    value = os.getenv("DB_IDENTITY_ONLY", "false").strip().lower()
    return value not in {"0", "false", "no", "off"}


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
            "agent_reference": {
                "type": "agent_reference",
                "name": agent_name,
                "version": agent_version,
            }
        },
    )
    return response.output_text


def image_to_data_uri(path: Path | None) -> str | None:
    if not path or not path.exists():
        return None
    suffix = path.suffix.lower().lstrip(".") or "png"
    encoded = b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/{suffix};base64,{encoded}"


def render_agent_board(active_agent: str | None, phase_text: str) -> None:
    cards: list[str] = []
    for key in [
        DBSERVICE_LABEL,
        "reinigung",
        "sicherheit",
        "technik",
        "bistro",
    ]:
        css_class = "active" if key == active_agent else "inactive"
        icon_data_uri = image_to_data_uri(AGENT_ICON_BY_KEY.get(key))
        if icon_data_uri:
            avatar_html = f'<img src="{icon_data_uri}" class="agent-avatar" alt="{AGENT_NAME_BY_KEY[key]}">' 
        else:
            fallback = AGENT_NAME_BY_KEY[key][:2].upper()
            avatar_html = f'<div class="agent-fallback">{fallback}</div>'

        cards.append(
            (
                f'<div class="agent-card {css_class}">'
                f"{avatar_html}"
                f'<div class="agent-name">{AGENT_NAME_BY_KEY[key]}</div>'
                "</div>"
            )
        )

    st.markdown(
        """
        <style>
        .stApp {
            background: #0e1117;
            color: #f0f2f6;
        }
        [data-testid="stSidebar"] {
            background: #161b22;
            border-right: 1px solid #263041;
        }
        .stChatMessage {
            background: #111824;
            border: 1px solid #263041;
        }
        .agent-shell {
            border-radius: 14px;
            padding: 14px;
            background: linear-gradient(145deg, #171d27 0%, #0f141d 100%);
            border: 1px solid #2e3a4b;
            margin: 0.25rem 0 1rem 0;
        }
        .agent-phase {
            font-size: 0.92rem;
            margin-bottom: 10px;
            color: #c8d2df;
            font-weight: 600;
            letter-spacing: 0.02em;
        }
        .agent-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 10px;
        }
        .agent-card {
            border-radius: 12px;
            padding: 10px 8px;
            border: 1px solid #2a3444;
            background: #0f1621;
            text-align: center;
            transition: all .18s ease;
        }
        .agent-card.inactive {
            opacity: 0.3;
            filter: grayscale(100%);
            transform: scale(0.98);
        }
        .agent-card.active {
            opacity: 1;
            filter: grayscale(0%);
            border: 2px solid #39a0ed;
            box-shadow: 0 8px 18px rgba(57, 160, 237, 0.2);
            transform: scale(1.01);
        }
        .agent-avatar {
            width: 54px;
            height: 54px;
            object-fit: contain;
            display: block;
            margin: 0 auto 6px auto;
        }
        .agent-fallback {
            width: 54px;
            height: 54px;
            border-radius: 50%;
            margin: 0 auto 6px auto;
            background: #1b2431;
            border: 1px solid #38485f;
            color: #d7e1ee;
            font-weight: 700;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.88rem;
        }
        .agent-name {
            font-size: 0.86rem;
            font-weight: 700;
            color: #e3ebf5;
            line-height: 1.2;
        }
        @media (max-width: 980px) {
            .agent-grid {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    board_html = (
        '<div class="agent-shell">'
        f'<div class="agent-phase">Current Stage: {phase_text}</div>'
        '<div class="agent-grid">'
        + "".join(cards)
        + "</div></div>"
    )
    st.markdown(board_html, unsafe_allow_html=True)


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
    cache = st.session_state.setdefault("helper_agent_version_cache", {})
    resolved_version = helper_version or cache.get(helper_name)
    if not resolved_version:
        resolved_version = get_latest_agent_version(project_client, helper_name)
        cache[helper_name] = resolved_version
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


def get_azure_credential():
    # Identity-only mode: prefer developer/user credentials and skip managed identity.
    if is_identity_only_mode():
        return DefaultAzureCredential(exclude_managed_identity_credential=True)

    # Fallback mode uses the full default chain, including managed identity when available.
    return DefaultAzureCredential()


def get_clients() -> tuple[AIProjectClient, object]:
    if "project_client" not in st.session_state or "openai_client" not in st.session_state:
        endpoint = require_env("AZURE_AI_PROJECT_ENDPOINT")
        project_client = AIProjectClient(endpoint=endpoint, credential=get_azure_credential())
        openai_client = project_client.get_openai_client()
        st.session_state.project_client = project_client
        st.session_state.openai_client = openai_client
    return st.session_state.project_client, st.session_state.openai_client


def get_runtime_agents(project_client: AIProjectClient) -> dict[str, str]:
    runtime_agents = st.session_state.get("runtime_agents")
    if runtime_agents:
        return runtime_agents

    orchestrator_agent_name = require_env("DB_ORCHESTRATOR_AGENT_NAME")
    orchestrator_agent_version = os.getenv("DB_ORCHESTRATOR_AGENT_VERSION") or get_latest_agent_version(
        project_client, orchestrator_agent_name
    )
    service_agent_name = require_env("DB_SERVICE_AGENT_NAME")
    service_agent_version = os.getenv("DB_SERVICE_AGENT_VERSION") or get_latest_agent_version(
        project_client, service_agent_name
    )

    runtime_agents = {
        "orchestrator_name": orchestrator_agent_name,
        "orchestrator_version": orchestrator_agent_version,
        "service_name": service_agent_name,
        "service_version": service_agent_version,
    }
    st.session_state.runtime_agents = runtime_agents
    return runtime_agents


def build_attachment_context(uploaded_file) -> tuple[str, str]:
    if uploaded_file is None:
        return "", ""

    file_bytes = uploaded_file.getvalue()
    size_bytes = len(file_bytes)
    mime_type = uploaded_file.type or "application/octet-stream"
    file_name = uploaded_file.name

    model_context = (
        "Attachment metadata:\n"
        f"- name: {file_name}\n"
        f"- type: {mime_type}\n"
        f"- size_bytes: {size_bytes}\n"
    )
    user_summary = f"Attached file: `{file_name}` ({mime_type}, {size_bytes} bytes)"

    text_like_suffixes = {".txt", ".md", ".csv", ".json", ".log", ".yaml", ".yml"}
    suffix = Path(file_name).suffix.lower()
    can_decode_text = mime_type.startswith("text/") or suffix in text_like_suffixes

    if can_decode_text:
        try:
            text_content = file_bytes.decode("utf-8", errors="ignore").strip()
            if text_content:
                # Keep payload bounded for model input.
                text_content = text_content[:4000]
                model_context += f"Attachment text content (truncated):\n{text_content}\n"
        except Exception:
            pass
    else:
        model_context += "Attachment is binary (image); metadata shared only.\n"

    return model_context, user_summary


def _uploaded_file_to_data_url(uploaded_file) -> tuple[str, str] | None:
    if uploaded_file is None:
        return None

    mime_type = uploaded_file.type or "application/octet-stream"
    if not mime_type.startswith("image/"):
        return None

    encoded = b64encode(uploaded_file.getvalue()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}", mime_type


def _extract_completion_text(completion) -> str:
    if not completion.choices:
        return ""

    message = completion.choices[0].message
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    text_chunks.append(str(text))
            else:
                text = getattr(item, "text", None)
                if text:
                    text_chunks.append(str(text))
        return "\n".join(text_chunks)

    return str(content)


def analyze_attachment_with_tool(uploaded_file, concern: str) -> dict | None:
    if uploaded_file is None:
        return None

    if is_identity_only_mode():
        return {
            "tool_used": False,
            "error": "Image analysis tool is disabled in identity-only mode.",
        }

    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "mistral-small-2503")
    timeout_seconds = float(os.getenv("AZURE_OPENAI_TIMEOUT_SECONDS", "30"))

    if not endpoint or not api_key:
        return {
            "tool_used": False,
            "error": "Missing AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_API_KEY",
        }

    data_url_payload = _uploaded_file_to_data_url(uploaded_file)
    if not data_url_payload:
        return {
            "tool_used": False,
            "error": "Attachment is not an image. Tool currently supports image analysis only.",
        }

    data_url, mime_type = data_url_payload

    client = OpenAI(base_url=endpoint, api_key=api_key, timeout=timeout_seconds)
    instruction = (
        "Analyze the uploaded issue image and return strict JSON with keys: "
        "issue_summary, severity, suggested_agent, confidence. "
        "suggested_agent must be one of: reinigung, sicherheit, technik, bistro. "
        "Do not include markdown or extra commentary."
    )

    try:
        completion = client.chat.completions.create(
            model=deployment,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": instruction,
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"User concern: {concern or '(none)'}",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                },
            ],
        )
    except APITimeoutError:
        return {
            "tool_used": False,
            "error": f"Attachment analysis timed out after {timeout_seconds:.0f}s",
        }
    except APIConnectionError as conn_error:
        return {
            "tool_used": False,
            "error": f"Attachment analysis connection failed: {conn_error}",
        }
    except APIError as api_error:
        return {
            "tool_used": False,
            "error": f"Attachment analysis API error: {api_error}",
        }

    raw_text = _extract_completion_text(completion).strip()
    parsed = extract_handover_json(raw_text)
    if parsed:
        parsed["tool_used"] = True
        parsed["mime_type"] = mime_type
        return parsed

    return {
        "tool_used": True,
        "mime_type": mime_type,
        "raw_result": raw_text,
    }


def add_message(role: str, content: str, avatar: str | None = None) -> None:
    st.session_state.messages.append({"role": role, "content": content, "avatar": avatar})


def render_history() -> None:
    for message in st.session_state.messages:
        with st.chat_message(message["role"], avatar=message.get("avatar")):
            st.markdown(message["content"])


def parse_chat_input_value(chat_value) -> tuple[str, object | None]:
    if chat_value is None:
        return "", None

    if isinstance(chat_value, str):
        return chat_value, None

    text = getattr(chat_value, "text", "") or ""
    files = getattr(chat_value, "files", None)
    if files is None and isinstance(chat_value, dict):
        text = chat_value.get("text", text) or ""
        files = chat_value.get("files")

    uploaded_file = files[0] if files else None
    return text, uploaded_file


def main() -> None:
    load_dotenv(BASE_DIR / ".env", override=False)

    st.set_page_config(page_title="DB Service Assistant", page_icon="DB", layout="centered")
    st.title("DB Service Assistant")
    st.caption("Hey there, traveler! I’m your personal travel assistant, ready to make every step of your journey smoother. Just tell me what you need, and I’ll get the right team working behind the scenes to make it happen!")

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "active_agent" not in st.session_state:
        st.session_state.active_agent = DBSERVICE_LABEL

    st.sidebar.header("Agent Network")

    board_placeholder = st.sidebar.empty()
    with board_placeholder.container():
        render_agent_board(st.session_state.active_agent, "Waiting for your concern")

    st.sidebar.markdown("---")
    if st.sidebar.button("Reset Chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.active_agent = DBSERVICE_LABEL
        st.rerun()

    render_history()

    st.caption("Tip: Click the upload icon in the chat box to attach a JPG, JPEG, or PNG.")

    chat_value = st.chat_input(
        "Describe your concern...",
        accept_file=True,
        file_type=["jpg", "jpeg", "png"],
    )
    concern, uploaded_file = parse_chat_input_value(chat_value)

    if not concern and uploaded_file is None:
        return

    attachment_context, attachment_summary = build_attachment_context(uploaded_file)
    concern_with_attachment = concern
    if attachment_context:
        concern_with_attachment = f"{concern}\n\n{attachment_context}"

    add_message("user", concern)
    with st.chat_message("user"):
        st.markdown(concern)
        if attachment_summary:
            st.caption(attachment_summary)

    process_status = st.status("Agents are thinking...", expanded=True)
    process_status.write("User concern received")

    try:
        # Keep DBService highlighted while orchestrator runs in the background.
        st.session_state.active_agent = DBSERVICE_LABEL
        with board_placeholder.container():
            render_agent_board(st.session_state.active_agent, "DBService is coordinating your request")
        process_status.write("DBService is analyzing and routing your concern")

        project_client, openai_client = get_clients()
        runtime_agents = get_runtime_agents(project_client)

        orchestrator_response = run_agent_with_retry(
            openai_client,
            agent_name=runtime_agents["orchestrator_name"],
            agent_version=runtime_agents["orchestrator_version"],
            user_message=concern_with_attachment,
        )
        process_status.write("Routing step completed")

        handover_payload = extract_handover_json(orchestrator_response)
        if not handover_payload:
            process_status.update(label="No handover payload returned", state="error", expanded=True)
            return

        tool_result = None
        if uploaded_file is not None:
            process_status.write("Orchestrator is invoking attachment analysis tool")
            try:
                tool_result = analyze_attachment_with_tool(uploaded_file, concern)
            except Exception as tool_error:
                tool_result = {
                    "tool_used": False,
                    "error": str(tool_error),
                }

            suggested_agent = ""
            if isinstance(tool_result, dict):
                suggested_agent = str(tool_result.get("suggested_agent", "")).lower().strip()

            if (
                suggested_agent in {"reinigung", "sicherheit", "technik", "bistro"}
                and str(handover_payload.get("detected_agent", "")).strip().lower() not in {"reinigung", "sicherheit", "technik", "bistro"}
            ):
                handover_payload["detected_agent"] = suggested_agent

        helper_agent = resolve_helper_agent(handover_payload, project_client)
        if not helper_agent:
            return

        helper_name, helper_version, detected_agent = helper_agent
        st.session_state.active_agent = detected_agent
        with board_placeholder.container():
            render_agent_board(st.session_state.active_agent, f"{AGENT_NAME_BY_KEY[detected_agent]} is handling details")
        process_status.write(f"{AGENT_NAME_BY_KEY[detected_agent]} is processing helper task")

        helper_input = (
            "DBService handoff payload:\n"
            f"{json.dumps(handover_payload, ensure_ascii=False)}\n\n"
            "Attachment tool result:\n"
            f"{json.dumps(tool_result, ensure_ascii=False)}"
        )
        helper_response = run_agent_with_retry(
            openai_client,
            agent_name=helper_name,
            agent_version=helper_version,
            user_message=helper_input,
        )
        process_status.write("Helper response received")

        service_input = (
            "User concern:\n"
            f"{concern}\n\n"
            f"{attachment_context}\n"
            "Orchestrator handoff payload:\n"
            f"{json.dumps(handover_payload, ensure_ascii=False)}\n\n"
            "Attachment tool result:\n"
            f"{json.dumps(tool_result, ensure_ascii=False)}\n\n"
            "Helper agent response:\n"
            f"{helper_response}"
        )
        service_response = run_agent_with_retry(
            openai_client,
            agent_name=runtime_agents["service_name"],
            agent_version=runtime_agents["service_version"],
            user_message=service_input,
        )
        process_status.write("DBService is finalizing user response")

        st.session_state.active_agent = DBSERVICE_LABEL
        with board_placeholder.container():
            render_agent_board(st.session_state.active_agent, "DBService is composing your response")

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

        process_status.update(label="Completed", state="complete", expanded=False)

    except Exception as error:
        process_status.update(label="Failed", state="error", expanded=True)
        process_status.write(f"Error: {error}")
        raise


if __name__ == "__main__":
    main()
