from flask import Flask, request, jsonify, send_from_directory
import json
import os
import re
import time
import requests
from dotenv import load_dotenv

# Look for env in multiple places
env_path = os.path.join(os.getcwd(), ".env")
if not os.path.exists(env_path):
    env_path = os.path.join(os.getcwd(), "code", "config.env")

load_dotenv(dotenv_path=env_path)
print(f"DEBUG: Loaded env from {env_path}")

# Absolute path to public folder
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DIR = os.path.join(BASE_DIR, 'public')

app = Flask(__name__)

@app.route('/')
def serve_index():
    return send_from_directory(PUBLIC_DIR, 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory(PUBLIC_DIR, path)

@app.errorhandler(Exception)
def handle_exception(e):
    # Pass through HTTP errors
    if hasattr(e, 'code') and e.code < 500:
        return jsonify({"error": str(e)}), e.code
    
    # Handle others
    print(f"CRITICAL ERROR: {str(e)}")
    import traceback
    traceback.print_exc()
    return jsonify({
        "error": "Internal Server Error",
        "details": str(e)
    }), 500

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = "google/gemini-2.0-flash-001"

def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "message": "Bug Hunter API is running"}), 200

@app.route('/api/detect', methods=['GET', 'POST'])
def detect_bug():
    if request.method == 'GET':
        return jsonify({"message": "Please use POST to detect bugs."}), 200
        
    print(f"Received request: {request.path}")
    data = request.json
    if not data:
        return jsonify({"error": "No JSON data provided"}), 400
        
    code = data.get('code', '')
    context = data.get('context', '')
    hint = data.get('hint', '')
    
    if not code:
        return jsonify({"error": "Code snippet is required"}), 400

    if not OPENROUTER_API_KEY:
        return jsonify({"error": "OPENROUTER_API_KEY is not configured on the server."}), 500

    # Number the lines
    code_lines = code.strip().split("\n")
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
{hint}

INSTRUCTIONS:
1. Carefully examine each line of the code.
2. Use the hint and context to identify the SINGLE most critical line containing the root cause of the bug.
3. If multiple lines are involved, pinpoint the single exact line where the error originates or is most prominent.
4. Provide a clear, concise explanation of the bug.

RESPOND IN EXACTLY THIS JSON FORMAT:
{{"bug_line": <single_integer_line_number>, "explanation": "<clear explanation>"}}
"""

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://infenion.vercel.app/",
        "X-OpenRouter-Title": "Agentic Bug Hunter",
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": "You are a C++ bug detection expert. Respond only in JSON."},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"}
    }
    
    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
        response.raise_for_status()
        
        data = response.json()
        content = data['choices'][0]['message']['content']
        
        # Parse the JSON response
        text = content.strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        result = json.loads(text)
        
        # Validate lines
        lines = result.get("bug_lines", [])
        if not lines and "bug_line" in result:
            lines = [result["bug_line"]]
        elif not lines:
            match = re.search(r'"bug_line"\s*:\s*(\d+)', text)
            if match:
                lines = [int(match.group(1))]
                
        valid_lines = []
        for line in lines:
            try:
                ln = int(line)
                if 1 <= ln <= len(code_lines):
                    valid_lines.append(ln)
            except (ValueError, TypeError):
                continue
                
        if not valid_lines:
            valid_lines = [1]
            
        primary_line = str(valid_lines[0])
        explanation = clean_text(str(result.get("explanation", "Bug detected but explanation missing.")))
        
        return jsonify({
            "bug_line": primary_line,
            "explanation": explanation
        })

    except Exception as e:
        print(f"API Error: {str(e)}")
        return jsonify({
            "error": "Failed to analyze code.",
            "details": str(e)
        }), 500

# Required for Vercel
# Vercel needs the Flask app instance to be the entry point.
# It looks for an object named `app` in `api/index.py`.
