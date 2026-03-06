"""
Agentic Bug Hunter — Infineon Hackathon
========================================
An agentic AI system that detects bugs in C++ code snippets using:
  1. MCP Server (search_documents tool) for documentation retrieval
  2. OpenRouter (Gemini 2.0 Flash) for bug analysis, line detection, and explanation

Usage:
    Create a 'code/config.env' file with OPENROUTER_API_KEY
    python code/main.py
"""

import csv
import json
import os
import sys
import time
import asyncio
import re
import requests
from pathlib import Path
from dotenv import load_dotenv

from fastmcp import Client
from fastmcp.client.transports import SSETransport


# ─────────────────────────────────────────────────────────────
#  Utilities
# ─────────────────────────────────────────────────────────────
def clean_text(text: str) -> str:
    """
    Clean text for CSV/Excel:
    1. Strip leading/trailing whitespace.
    2. Replace newlines, tabs, and carriage returns with spaces.
    3. Collapse multiple spaces into one.
    """
    if not text:
        return ""
    # Replace all whitespace characters (including \n, \r, \t) with a space
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


# ─────────────────────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────────────────────
# Load environment variables from config.env
env_path = Path(__file__).parent / "config.env"
load_dotenv(dotenv_path=env_path)

MCP_SERVER_URL = "http://localhost:8003/sse"
INPUT_CSV = os.path.join(os.path.dirname(__file__), "samples.csv")
OUTPUT_CSV = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output.csv")

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
# Using Gemini 2.0 Flash via OpenRouter for speed and efficiency
OPENROUTER_MODEL = "google/gemini-2.0-flash-001" 


# ─────────────────────────────────────────────────────────────
#  MCP Agent — Document Retrieval
# ─────────────────────────────────────────────────────────────
class MCPDocRetriever:
    """Agent responsible for retrieving documentation from MCP server."""

    def __init__(self, server_url: str):
        self.server_url = server_url
        self.transport = SSETransport(server_url)
        self.connection_failed = False

    async def search_documents(self, query: str) -> list[dict]:
        """Search documentation via MCP server's search_documents tool."""
        if self.connection_failed:
            return []

        try:
            async with Client(self.transport) as client:
                result = await client.call_tool(
                    "search_documents", {"query": query}
                )
                # Parse the result
                if result and hasattr(result, 'content') and len(result.content) > 0:
                    content = result.content[0].text if hasattr(result.content[0], 'text') else str(result.content[0])
                    try:
                        docs = json.loads(content)
                        if isinstance(docs, list):
                            return docs
                    except (json.JSONDecodeError, TypeError):
                        return [{"text": content, "score": 1.0}]
                elif result and isinstance(result, list) and len(result) > 0:
                     # Fallback for older fastmcp versions or different return types
                    content = result[0].text if hasattr(result[0], 'text') else str(result[0])
                    try:
                        docs = json.loads(content)
                        if isinstance(docs, list):
                            return docs
                    except (json.JSONDecodeError, TypeError):
                        return [{"text": content, "score": 1.0}]
                return []
        except Exception as e:
            if not self.connection_failed:
                print(f"\n  [MCP ERROR] Could not connect to doc server at {self.server_url}")
                print(f"  [TIP] Run 'python code/server/mcp_server.py' in a separate terminal to enable doc search.\n")
                self.connection_failed = True
            return []


# ─────────────────────────────────────────────────────────────
#  Bug Detection Agent — LLM Analysis
# ─────────────────────────────────────────────────────────────
class BugDetectionAgent:
    """Agent responsible for analyzing code and detecting bugs using OpenRouter."""

    def __init__(self, api_key: str, model_name: str):
        self.api_key = api_key
        self.model_name = model_name
        self.url = "https://openrouter.ai/api/v1/chat/completions"

    def detect_bug(
        self,
        code_id: str,
        buggy_code: str,
        context: str,
        explanation_hint: str,
        documentation: str,
    ) -> dict:
        """
        Analyze buggy code and return the bug line number and explanation.
        """

        # Number the lines for the LLM
        code_lines = buggy_code.strip().split("\n")
        numbered_code = "\n".join(
            f"{i+1}: {line}" for i, line in enumerate(code_lines)
        )

        prompt = f"""You are an expert C++ bug detection agent for Infineon semiconductor test systems.
You specialize in SmartRDI (Runtime Data Interface) API bugs.

TASK: Analyze the following C++ code snippet and find ALL lines containing bugs related to the SmartRDI API.

=== CODE (with line numbers) ===
{numbered_code}

=== CONTEXT / PURPOSE ===
{context}

=== HINT ABOUT THE BUG ===
{explanation_hint}

=== RELEVANT DOCUMENTATION FROM MANUAL ===
{documentation}

INSTRUCTIONS:
1. Carefully examine each line of the code.
2. Use the hint and the documentation to identify the SINGLE most critical line containing the root cause of the bug.
3. If multiple lines are involved, pinpoint the single exact line where the error originates or is most prominent.
4. Provide a clear, concise explanation of the bug.

RESPOND IN EXACTLY THIS JSON FORMAT:
{{"bug_line": <single_integer_line_number>, "explanation": "<clear explanation>"}}
"""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/infineon-hackathon",
            "X-OpenRouter-Title": "Agentic Bug Hunter",
        }

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": "You are a C++ bug detection expert. Respond only in JSON."},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"}
        }

        max_retries = 5
        base_delay = 5
        
        for attempt in range(max_retries):
            try:
                response = requests.post(self.url, headers=headers, data=json.dumps(payload), timeout=60)
                response.raise_for_status()
                data = response.json()
                content = data['choices'][0]['message']['content']
                return self._parse_response(content, code_lines)
            except Exception as e:
                print(f"  [LLM ERROR] Attempt {attempt+1} failed: {e}")
                if "429" in str(e) or (hasattr(e, 'response') and e.response.status_code == 429):
                    wait_time = base_delay * (attempt + 1)
                    print(f"  [QUOTA] Rate limit hit. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    time.sleep(2)
        
        return {"bug_line": "1", "explanation": clean_text("Failed to analyze after multiple attempts.")}

    def _parse_response(self, response_text: str, code_lines: list) -> dict:
        """Parse the LLM JSON response robustly."""
        try:
            # Clean up potential markdown
            text = response_text.strip()
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
            
            result = json.loads(text)
            
            # Handle both "bug_lines" (list) and "bug_line" (int/str) for robustness
            lines = result.get("bug_lines", [])
            if not lines and "bug_line" in result:
                lines = [result["bug_line"]]
            elif not lines:
                # If neither is found, let's try to extract from raw text if possible, else default
                match = re.search(r'"bug_line"\s*:\s*(\d+)', text)
                if match:
                    lines = [int(match.group(1))]
            
            # Ensure lines are valid integers and within range
            valid_lines = []
            for line in lines:
                try:
                    ln = int(line)
                    if 1 <= ln <= len(code_lines):
                        valid_lines.append(ln)
                except (ValueError, TypeError):
                    continue
            
            # If no valid lines found, fallback to line 1
            if not valid_lines:
                valid_lines = [1]
            
            # Take the very first valid line as the single bug line
            primary_line = str(valid_lines[0])
            explanation = clean_text(str(result.get("explanation", "Bug(s) detected")))

            return {"bug_line": primary_line, "explanation": explanation}
        except Exception as e:
            print(f"  [PARSE ERROR] {e}")
            return {"bug_line": "1", "explanation": f"Failed to parse LLM response"}


# ─────────────────────────────────────────────────────────────
#  Orchestrator Agent — Coordinates the pipeline
# ─────────────────────────────────────────────────────────────
class OrchestratorAgent:
    """Main orchestrator for the bug hunting pipeline."""

    def __init__(self):
        if not OPENROUTER_API_KEY:
            print("ERROR: OPENROUTER_API_KEY not found in config.env!")
            sys.exit(1)

        self.doc_retriever = MCPDocRetriever(MCP_SERVER_URL)
        self.bug_detector = BugDetectionAgent(OPENROUTER_API_KEY, OPENROUTER_MODEL)

    def read_samples(self) -> list[dict]:
        """Read and parse the samples CSV."""
        samples = []
        with open(INPUT_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                samples.append(row)
        print(f"[ORCHESTRATOR] Loaded {len(samples)} samples from {INPUT_CSV}")
        return samples

    async def process_sample(self, sample: dict, index: int, total: int) -> dict:
        """Process a single code sample."""
        code_id = sample.get("ID", "").strip()
        explanation_hint = sample.get("Explanation", "").strip()
        context = sample.get("Context", "").strip()
        buggy_code = sample.get("Code", "").strip()

        print(f"\n[{index+1}/{total}] Processing ID: {code_id}")

        # Step 1: Documentation retrieval
        search_query = f"{context} {explanation_hint}"
        docs = await self.doc_retriever.search_documents(search_query)

        doc_text = ""
        if docs:
            for i, doc in enumerate(docs[:3]):
                doc_text += f"\n--- Doc {i+1} ---\n{doc.get('text', '')}\n"
        
        # Step 2: Bug detection
        result = self.bug_detector.detect_bug(
            code_id=code_id,
            buggy_code=buggy_code,
            context=context,
            explanation_hint=explanation_hint,
            documentation=doc_text or "No documentation found.",
        )

        return {
            "ID": code_id,
            "Bug Line": result["bug_line"],
            "Explanation": result["explanation"],
        }

    def write_results(self, results: list[dict]):
        """Write all results to the CSV in one go to ensure order and avoid locks."""
        try:
            with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["ID", "Bug Line", "Explanation"])
                writer.writeheader()
                writer.writerows(results)
            print(f"\n[COMPLETE] Successfully saved {len(results)} results to {OUTPUT_CSV}")
        except PermissionError:
            print(f"\n[CRITICAL ERROR] Permission denied: '{OUTPUT_CSV}'")
            print("Please CLOSE the Excel file and run the script again.")
            sys.exit(1)

    async def run(self):
        """Execute the pipeline."""
        print("=" * 60)
        print(" AGENTIC BUG HUNTER — OpenRouter Mode")
        print("=" * 60)

        samples = self.read_samples()
        results = []

        for i, sample in enumerate(samples):
            try:
                result = await self.process_sample(sample, i, len(samples))
                results.append(result)
                print(f"  [OK] Processed ID {result['ID']}")
            except Exception as e:
                print(f"  [ERROR] {e}")
                results.append({"ID": sample.get("ID", "??"), "Bug Line": "1", "Explanation": clean_text(str(e))})

            # Small delay for API stability
            if i < len(samples) - 1:
                time.sleep(2)

        self.write_results(results)

# ─────────────────────────────────────────────────────────────
#  Entry Point
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    orchestrator = OrchestratorAgent()
    asyncio.run(orchestrator.run())
