"""Create Jibli's AgentCore Memory resource once, then paste the printed id into ai-core/.env.

    .venv/bin/python scripts/create_agentcore_memory.py

Two long-term strategies: semantic facts ("her husband takes no sugar") and user preferences ("small bread").
"""
import os
import sys
import time
from pathlib import Path

import boto3
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
region = os.getenv("AWS_REGION", "us-east-1")
ctl = boto3.client("bedrock-agentcore-control", region_name=region)

existing = [m for m in ctl.list_memories().get("memories", []) if m.get("id", "").startswith("JibliMemory-")]
if existing:
    print(f"Already exists. Put this in .env:\nAGENTCORE_MEMORY_ID={existing[0]['id']}")
    sys.exit(0)

mem = ctl.create_memory(
    name="JibliMemory",
    description="Jibli voice ordering: per-user facts and preferences",
    eventExpiryDuration=30,
    memoryStrategies=[
        {"semanticMemoryStrategy": {"name": "Facts", "namespaces": ["/users/{actorId}/facts/"]}},
        {"userPreferenceMemoryStrategy": {"name": "Preferences", "namespaces": ["/users/{actorId}/preferences/"]}},
    ],
)["memory"]
print("Creating", mem["id"], "(about 2-3 minutes)...")
while (status := ctl.get_memory(memoryId=mem["id"])["memory"]["status"]) not in ("ACTIVE", "FAILED"):
    time.sleep(10)
    print(" ", status)
print(f"{status}. Put this in .env:\nAGENTCORE_MEMORY_ID={mem['id']}")
