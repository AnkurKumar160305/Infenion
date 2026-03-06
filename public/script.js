document.addEventListener('DOMContentLoaded', () => {
    const analyzeBtn = document.getElementById('analyze-btn');
    const btnText = analyzeBtn.querySelector('.btn-text');
    const loader = analyzeBtn.querySelector('.loader');
    
    const contextInput = document.getElementById('context');
    const hintInput = document.getElementById('hint');
    const codeInput = document.getElementById('code');
    
    const resultsSection = document.getElementById('results-section');
    const errorSection = document.getElementById('error-section');
    const errorMessage = document.getElementById('error-message');
    
    const bugLineNumber = document.getElementById('bug-line-number');
    const bugExplanation = document.getElementById('bug-explanation');
    const codePreview = document.getElementById('code-preview');

    analyzeBtn.addEventListener('click', async () => {
        const code = codeInput.value.trim();
        const context = contextInput.value.trim();
        const hint = hintInput.value.trim();

        if (!code) {
            showError("Please enter a C++ code snippet to analyze.");
            return;
        }

        // Reset UI state
        hideError();
        resultsSection.classList.add('hidden');
        setLoading(true);

        try {
            const response = await fetch('/api/detect', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ code, context, hint })
            });

            // Check if response is JSON
            const contentType = response.headers.get("content-type");
            if (!contentType || !contentType.includes("application/json")) {
                const text = await response.text();
                console.error('Non-JSON response:', text);
                throw new Error(`Server returned a non-JSON response (${response.status}). This usually means the API crashed or is misconfigured.`);
            }

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Failed to analyze code');
            }

            // Display results
            displayResults(data, code);
        } catch (error) {
            console.error('Error:', error);
            showError(error.message || "An unexpected error occurred while communicating with the server.");
        } finally {
            setLoading(false);
        }
    });

    function displayResults(data, originalCode) {
        bugLineNumber.textContent = data.bug_line;
        bugExplanation.textContent = data.explanation;
        
        // Render code preview with highlighting
        renderCodePreview(originalCode, parseInt(data.bug_line, 10));
        
        resultsSection.classList.remove('hidden');
        
        // Scroll to results
        resultsSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function renderCodePreview(code, highlightLineNumber) {
        const lines = code.split('\n');
        let html = '';
        
        // Determine range to show (context window)
        // Show 3 lines before and 3 lines after, or entire snippet if small
        const padding = 3;
        let startLine = 1;
        let endLine = lines.length;
        
        if (lines.length > 10) {
            startLine = Math.max(1, highlightLineNumber - padding);
            endLine = Math.min(lines.length, highlightLineNumber + padding);
        }

        for (let i = startLine; i <= endLine; i++) {
            const lineContent = lines[i - 1];
            const isHighlighted = i === highlightLineNumber;
            
            html += `
                <div class="code-line ${isHighlighted ? 'highlight' : ''}">
                    <div class="code-line-num">${i}</div>
                    <div class="code-line-content">${escapeHTML(lineContent)}</div>
                </div>
            `;
        }
        
        if (startLine > 1) {
            html = `<div class="code-line"><div class="code-line-num">...</div><div class="code-line-content"></div></div>` + html;
        }
        
        if (endLine < lines.length) {
            html += `<div class="code-line"><div class="code-line-num">...</div><div class="code-line-content"></div></div>`;
        }
        
        codePreview.innerHTML = html;
    }

    function setLoading(isLoading) {
        if (isLoading) {
            analyzeBtn.disabled = true;
            btnText.textContent = 'Analyzing...';
            loader.classList.remove('hidden');
        } else {
            analyzeBtn.disabled = false;
            btnText.textContent = 'Detect Bug';
            loader.classList.add('hidden');
        }
    }

    function showError(message) {
        errorMessage.textContent = message;
        errorSection.classList.remove('hidden');
        resultsSection.classList.add('hidden');
    }

    function hideError() {
        errorSection.classList.add('hidden');
    }

    // Utility text escaper
    function escapeHTML(str) {
        return str.replace(/[&<>'"]/g, 
            tag => ({
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                "'": '&#39;',
                '"': '&quot;'
            }[tag])
        );
    }
});
