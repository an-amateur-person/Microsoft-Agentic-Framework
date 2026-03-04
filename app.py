import asyncio
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

from agent_framework import Message
from agent_framework.azure import AzureOpenAIResponsesClient
from agent_framework.orchestrations import HandoffBuilder
from azure.identity import AzureCliCredential, DefaultAzureCredential

from dotenv import load_dotenv


def read_prompt(file_name: str) -> str:
    prompt_path = Path(__file__).resolve().parent / "prompts" / file_name
    return prompt_path.read_text(encoding="utf-8")


def normalize_deployment_name(value: str) -> str:
    if not value.startswith(("http://", "https://")):
        return value

    parts = [part for part in urlparse(value).path.split("/") if part]
    if "deployments" in parts:
        idx = parts.index("deployments")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return value


def extract_last_text(output: object) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, Message):
        return output.text or str(output)
    if isinstance(output, list) and output:
        last_item = output[-1]
        if isinstance(last_item, Message):
            return last_item.text or str(last_item)
        return str(last_item)
    return str(output)


async def main() -> None:
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)

    credential = AzureCliCredential() if shutil.which("az") else DefaultAzureCredential()
    deployment_name = normalize_deployment_name(os.environ["AZURE_OPENAI_RESPONSES_DEPLOYMENT_NAME"])

    client = AzureOpenAIResponsesClient(
        project_endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
        deployment_name=deployment_name,
        credential=credential,
    )

    service_agent = client.as_agent(
        name="DBServiceAgent",
        instructions=read_prompt("DBService.md"),
    )
    security_agent = client.as_agent(
        name="DBSecurityAgent",
        instructions=read_prompt("DBsecurity.md"),
    )
    technik_agent = client.as_agent(
        name="DBTechnikAgent",
        instructions=read_prompt("DBtechnik.md"),
    )
    cleaning_agent = client.as_agent(
        name="DBCleaningAgent",
        instructions=read_prompt("DBCleaning-DO.md"),
    )

    workflow = (
        HandoffBuilder(name="DB Incident Handoff Workflow")
        .participants([service_agent, security_agent, technik_agent, cleaning_agent])
        .with_start_agent(service_agent)
        .add_handoff(service_agent, [security_agent, technik_agent, cleaning_agent])
        .add_handoff(security_agent, [service_agent])
        .add_handoff(technik_agent, [service_agent])
        .add_handoff(cleaning_agent, [service_agent])
        .build()
    )

    default_concern = "Im Wagen ist es sehr heiß und die Klimaanlage scheint defekt. Mein Kind fühlt sich unwohl."
    concern = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else ""
    if not concern:
        user_input = input("Bitte beschreiben Sie Ihr Anliegen: ").strip()
        concern = user_input or default_concern

    run_result = await workflow.run(concern)
    outputs = run_result.get_outputs()
    final_output = outputs[-1] if outputs else "Keine Antwort erhalten."
    print(f"Agent: {extract_last_text(final_output)}")


if __name__ == "__main__":
    asyncio.run(main())