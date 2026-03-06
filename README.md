# DB Service Multi-Agent UI

A basic Streamlit chat UI for customer concerns:
- `Orchestrator` determines the target helper agent.
- Helper agents (`Reinigung`, `Sicherheit`, `Technik`, `Bistro`) handle domain details.
- `DBService` is the user-facing responder and returns the final response shown to the user.
- DBService and helper responses are shown in chat with icons from `assets/`.

## Prerequisites

- Python 3.10+
- Azure login available for `DefaultAzureCredential` (for example, `az login`)
- A configured `.env` file in the project root

## Install

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run Streamlit UI

```powershell
.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

## Required Environment Variables

Set these in `.env`:

```dotenv
AZURE_AI_PROJECT_ENDPOINT="https://<your-ai-services-account>.services.ai.azure.com/api/projects/<your-project>"

DB_SERVICE_AGENT_NAME=<service-agent-name>
DB_ORCHESTRATOR_AGENT_NAME=<orchestrator-agent-name>
DB_CLEANING_AGENT_NAME=<cleaning-agent-name>
DB_SECURITY_AGENT_NAME=<security-agent-name>
DB_TECHNIK_AGENT_NAME=<technik-agent-name>
DB_BISTRO_AGENT_NAME=<bistro-agent-name>
```

## Optional Environment Variables

If omitted, latest version is resolved automatically for each agent:

```dotenv
DB_SERVICE_AGENT_VERSION=<version>
DB_ORCHESTRATOR_AGENT_VERSION=<version>
DB_CLEANING_AGENT_VERSION=<version>
DB_SECURITY_AGENT_VERSION=<version>
DB_TECHNIK_AGENT_VERSION=<version>
DB_BISTRO_AGENT_VERSION=<version>
```

## Files

- `streamlit_app.py`: Streamlit chat interface and Foundry agent routing logic
- `app.py`: CLI version of the same flow
- `assets/`: DBService and helper agent icons used by the UI
