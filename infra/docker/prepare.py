"""Copy validated local settings into private Docker env files, without logging secrets."""

import json
from pathlib import Path
import secrets
import sys


def main():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "backend"))
    from app.config import settings
    from pydantic import SecretStr
    destination = root / "infra/docker"
    files = [destination / ".env", destination / "backend.env"]
    if any(path.exists() for path in files):
        if all(path.exists() for path in files):
            print("Private Docker settings already exist; preserved unchanged.")
            return
        raise RuntimeError("Incomplete private settings; restore the missing file before continuing")
    password = secrets.token_urlsafe(32)
    values = {}
    for key in type(settings).model_fields:
        value = getattr(settings, key)
        if value is None:
            continue
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        elif isinstance(value, (list, dict, bool)):
            value = json.dumps(value)
        values[key] = str(value)
    values.update(DATABASE_URL=f"mysql+pymysql://lab_agent:{password}@mysql:3306/lab_agent?charset=utf8mb4",
        CHROMA_HOST="chroma", CHROMA_PORT="8001", KNOWLEDGE_DIR="/app/data/knowledge",
        AGENT_CHECKPOINT_PATH="/app/data/agent/checkpoints.sqlite", AGENT_TOOL_TRANSPORT="mcp",
        AGENT_MCP_URL="http://mcp:8002/mcp",
        AGENT_MCP_ALLOWED_HOSTS=json.dumps(["mcp", "localhost", "127.0.0.1", "::1"]))
    if not settings.RAG_ENABLED:
        raise RuntimeError("This full-stack Compose includes the RAG worker; enable RAG locally before preparing")
    if any("\n" in value or "\r" in value for value in values.values()):
        raise ValueError("Multiline values cannot be exported into a raw env file")
    files[0].write_text(f"WEB_PORT=18081\nMYSQL_PASSWORD={password}\nMYSQL_ROOT_PASSWORD={secrets.token_urlsafe(32)}\n", encoding="utf-8")
    files[1].write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    print("Private Docker settings generated. Existing model configuration and JWT key preserved.")


if __name__ == "__main__":
    main()
