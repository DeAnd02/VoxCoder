// ===== VoxCoder — Frontend Logic (Hacker Edition + Realtime STT) =====

const $ = (sel) => document.querySelector(sel);

// DOM refs
const btnMic         = $("#btn-mic");
const micLabel       = $(".mic-label");
const statusDot      = $("#status-dot");
const statusText     = $("#status-text");
const transcriptBody = $("#transcript-content");
const codeBody       = $("#code-content");
const outputBody     = $("#output-content");
const sysClockEl     = $("#sys-clock");
const reqCountEl     = $("#req-count");
const wsIndicator    = $("#ws-indicator");
const waveformCanvas = $("#waveform");

// Pipeline step elements
const stepMic   = $("#step-mic");
const stepStt   = $("#step-stt");
const stepAgent = $("#step-agent");
const stepExec  = $("#step-exec");

// State
let ws = null;
let isRecording = false;
let requestCount = 0;
let firstTranscript = true;
let firstCode = true;
let firstOutput = true;
let audioContext = null;
let analyser = null;
let scriptProcessor = null;
let micStream = null;
let waveformAnimId = null;
let liveTranscriptEl = null;   // current live transcript DOM element

// Code Tabs State
let codeTabs = [];
let activeTabId = null;
let tabCounter = 0;
let bootSequenceDone = false;

// Live Preview State
let previewCode = {
    html: "",
    css: "",
    js: "",
    other: null   // { code, language } for non-web languages
};

// ── Matrix Rain Background ────────────────────────────────────────────────

(function initMatrix() {
    const canvas = $("#matrix-bg");
    const ctx = canvas.getContext("2d");

    function resize() {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
    }
    resize();
    window.addEventListener("resize", resize);

    const chars = "01アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン{}()<>[];=/\\+-*&^%$#@!?";
    const fontSize = 14;
    const columns = Math.floor(canvas.width / fontSize);
    const drops = Array.from({ length: columns }, () => Math.random() * -100);

    function drawMatrix() {
        ctx.fillStyle = "rgba(5, 10, 14, 0.08)";
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        ctx.fillStyle = "#00ff88";
        ctx.font = `${fontSize}px monospace`;

        for (let i = 0; i < drops.length; i++) {
            const char = chars[Math.floor(Math.random() * chars.length)];
            ctx.fillText(char, i * fontSize, drops[i] * fontSize);

            if (drops[i] * fontSize > canvas.height && Math.random() > 0.975) {
                drops[i] = 0;
            }
            drops[i]++;
        }
    }

    setInterval(drawMatrix, 50);
})();

// ── System Clock ──────────────────────────────────────────────────────────

(function initClock() {
    function update() {
        const now = new Date();
        sysClockEl.textContent =
            String(now.getHours()).padStart(2, "0") + ":" +
            String(now.getMinutes()).padStart(2, "0") + ":" +
            String(now.getSeconds()).padStart(2, "0");
    }
    update();
    setInterval(update, 1000);
})();

// ── Waveform Visualizer ──────────────────────────────────────────────────

function startWaveform() {
    if (!analyser) return;
    const ctx = waveformCanvas.getContext("2d");
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    const W = waveformCanvas.width;
    const H = waveformCanvas.height;

    function draw() {
        waveformAnimId = requestAnimationFrame(draw);
        analyser.getByteTimeDomainData(dataArray);

        ctx.fillStyle = "rgba(5, 10, 14, 0.6)";
        ctx.fillRect(0, 0, W, H);

        ctx.lineWidth = 1.5;
        ctx.strokeStyle = "#f97316";
        ctx.shadowColor = "rgba(249, 115, 22, 0.5)";
        ctx.shadowBlur = 4;
        ctx.beginPath();

        const sliceWidth = W / bufferLength;
        let x = 0;
        for (let i = 0; i < bufferLength; i++) {
            const v = dataArray[i] / 128.0;
            const y = (v * H) / 2;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
            x += sliceWidth;
        }
        ctx.lineTo(W, H / 2);
        ctx.stroke();
        ctx.shadowBlur = 0;
    }
    draw();
}

function stopWaveform() {
    if (waveformAnimId) {
        cancelAnimationFrame(waveformAnimId);
        waveformAnimId = null;
    }
    const ctx = waveformCanvas.getContext("2d");
    ctx.fillStyle = "rgba(5, 10, 14, 1)";
    ctx.fillRect(0, 0, waveformCanvas.width, waveformCanvas.height);
    ctx.strokeStyle = "#1a2a3a";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, waveformCanvas.height / 2);
    ctx.lineTo(waveformCanvas.width, waveformCanvas.height / 2);
    ctx.stroke();
}

// Draw initial flat line
stopWaveform();

// ── Pipeline Steps ────────────────────────────────────────────────────────

function setPipelineStep(activeStep) {
    const steps = { mic: stepMic, stt: stepStt, agent: stepAgent, exec: stepExec };
    const order = ["mic", "stt", "agent", "exec"];
    const activeIdx = order.indexOf(activeStep);

    for (let i = 0; i < order.length; i++) {
        const el = steps[order[i]];
        el.classList.remove("active", "done");
        if (i < activeIdx) el.classList.add("done");
        else if (i === activeIdx) el.classList.add("active");
    }
}

function clearPipeline() {
    [stepMic, stepStt, stepAgent, stepExec].forEach((el) => {
        el.classList.remove("active", "done");
    });
}

// ── Glitch Effect ─────────────────────────────────────────────────────────

function triggerGlitch() {
    const el = $(".ascii-subtitle");
    if (!el) return;
    el.classList.remove("glitch-active");
    void el.offsetWidth; // force reflow to restart animation
    el.classList.add("glitch-active");
    setTimeout(() => el.classList.remove("glitch-active"), 400);
}

// ── Boot Sequence ─────────────────────────────────────────────────────────

function runBootSequence() {
    if (bootSequenceDone) return;
    bootSequenceDone = true;

    [transcriptBody, codeBody, outputBody].forEach(el => clearBootLines(el));

    const seq = [
        { panel: transcriptBody, delay: 0,   text: "sys: init voice_input.subsystem" },
        { panel: codeBody,       delay: 80,  text: "mistral-agent: api_client.LOADED" },
        { panel: outputBody,     delay: 160, text: "sandbox: container.MOUNTED" },
        { panel: transcriptBody, delay: 300, text: "voxtral-realtime: STT.ACTIVE" },
        { panel: codeBody,       delay: 380, text: "code_interpreter: ARMED" },
        { panel: outputBody,     delay: 460, text: "exec_engine: ONLINE" },
        { panel: transcriptBody, delay: 620, text: "// Hold [SPACE] or mic button to speak" },
    ];

    seq.forEach(({ panel, delay, text }) => {
        setTimeout(() => {
            const line = document.createElement("div");
            line.className = "boot-line boot-seq-line";
            const isComment = text.startsWith("//");
            line.innerHTML = isComment
                ? `<span class="dim">${text}</span>`
                : `<span class="dim">// </span><span class="ansi-green">${text}</span>`;
            panel.appendChild(line);
            panel.scrollTop = panel.scrollHeight;
        }, delay);
    });
}

// ── WebSocket ─────────────────────────────────────────────────────────────

function connectWS() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws`);

    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
        setStatus("ready", "CONNECTED");
        wsIndicator.textContent = "ON";
        wsIndicator.classList.add("online");
        runBootSequence();
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleMessage(msg);
    };

    ws.onclose = () => {
        setStatus("error", "DISCONNECTED");
        wsIndicator.textContent = "--";
        wsIndicator.classList.remove("online");
        setTimeout(connectWS, 2000);
    };

    ws.onerror = () => { ws.close(); };
}

function wsSend(data) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(data);
}

// ── Message Handler ───────────────────────────────────────────────────────

function handleMessage(msg) {
    try {
        switch (msg.type) {
            case "transcript_delta":
                appendLiveTranscript(msg.text);
                break;
            case "transcript":
                finalizeLiveTranscript(msg.text);
                break;
            case "code":
                addCode(msg.content, msg.language || "python");
                break;
            case "output":
                setPipelineStep("exec");
                addOutput(msg.content);
                break;
            case "message":
                addAgentMessage(msg.text);
                break;
            case "status":
                handleStatus(msg);
                break;
            case "image":
                showPreviewImage(msg.data);
                break;
            case "cost":
                updateCosts(msg.session, msg.request);
                break;
        }
    } catch (err) {
        console.error("Error handling message:", err, msg);
    }
}

function updateCosts(session, request) {
    // Update top header stat
    $("#total-cost").textContent = `$${session.total.toFixed(3)}`;
    $("#total-tokens").textContent = session.input_tokens + session.output_tokens;

    // Update session table
    $("#cost-audio-usage").textContent = `${session.audio_minutes.toFixed(2)} min`;
    $("#cost-stt").textContent = `$${session.stt_cost.toFixed(6)}`;

    $("#cost-input-tokens").textContent = `${session.input_tokens} tkn`;
    $("#cost-input").textContent = `$${session.agent_cost_in.toFixed(6)}`;

    $("#cost-output-tokens").textContent = `${session.output_tokens} tkn`;
    $("#cost-output").textContent = `$${session.agent_cost_out.toFixed(6)}`;

    $("#cost-exec-count").textContent = `${session.code_executions} runs`;
    $("#cost-exec").textContent = `$${session.exec_cost.toFixed(6)}`;

    $("#cost-session-total").textContent = `$${session.total.toFixed(6)}`;

    // Update progress bars
    if (session.total > 0) {
        $("#bar-stt").style.width    = `${(session.stt_cost / session.total * 100).toFixed(1)}%`;
        $("#bar-input").style.width  = `${(session.agent_cost_in / session.total * 100).toFixed(1)}%`;
        $("#bar-output").style.width = `${(session.agent_cost_out / session.total * 100).toFixed(1)}%`;
        $("#bar-exec").style.width   = `${(session.exec_cost / session.total * 100).toFixed(1)}%`;
    }

    // Last request info
    const lastReqEl = $("#cost-last-req");
    if (lastReqEl && request) {
        lastReqEl.innerHTML = `
            <div class="last-req-title">LAST REQUEST</div>
            <div class="last-req-row">
                <span>Audio: ${request.audio_sec}s</span>
                <span>Tokens: ${request.input_tokens + request.output_tokens}</span>
                <span>Cost: <span class="accent">$${request.total.toFixed(6)}</span></span>
            </div>
        `;
    }
}

function handleStatus(msg) {
    setStatus(msg.status, (msg.message || msg.status).toUpperCase());

    switch (msg.status) {
        case "transcribing": setPipelineStep("stt"); break;
        case "thinking":     setPipelineStep("agent"); break;
        case "executing":    setPipelineStep("exec"); break;
        case "ready":
            clearPipeline();
            // Reset all RUN buttons
            document.querySelectorAll(".run-btn.running").forEach(btn => {
                btn.textContent = "&#9654; RUN";
                btn.innerHTML = "&#9654; RUN";
                btn.disabled = false;
                btn.classList.remove("running");
            });
            break;
    }
}

// ── UI Updates ────────────────────────────────────────────────────────────

function clearBootLines(container) {
    container.querySelectorAll(".boot-line").forEach((el) => el.remove());
}

// Live transcript — shows deltas as they arrive
function createLiveTranscriptEntry() {
    if (firstTranscript) {
        clearBootLines(transcriptBody);
        firstTranscript = false;
    }

    // Reset preview state for new request if needed
    // (Optional: you might want to keep it, but user wants "simple code" to look simple)
    // For now, let's keep it but allow closing.

    requestCount++;
    reqCountEl.textContent = requestCount;

    const entry = document.createElement("div");
    entry.className = "transcript-entry";

    const timestamp = new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    entry.innerHTML = `<div class="label">voice_input <span class="dim">${timestamp}</span></div><div class="transcript-text"><span class="typed-cursor"></span></div>`;
    transcriptBody.appendChild(entry);
    transcriptBody.scrollTop = transcriptBody.scrollHeight;

    liveTranscriptEl = entry.querySelector(".transcript-text");
}

function appendLiveTranscript(delta) {
    if (!liveTranscriptEl) createLiveTranscriptEntry();

    const cursor = liveTranscriptEl.querySelector(".typed-cursor");
    const textNode = document.createTextNode(delta);
    if (cursor) {
        liveTranscriptEl.insertBefore(textNode, cursor);
    } else {
        liveTranscriptEl.appendChild(textNode);
    }
    transcriptBody.scrollTop = transcriptBody.scrollHeight;
}

function finalizeLiveTranscript(fullText) {
    if (liveTranscriptEl) {
        const cursor = liveTranscriptEl.querySelector(".typed-cursor");
        if (cursor) cursor.remove();
        // Replace content with final text
        liveTranscriptEl.textContent = fullText;
    }
    liveTranscriptEl = null;
}

// Legacy: full transcript (fallback if no deltas received)
function addTranscript(text) {
    if (firstTranscript) {
        clearBootLines(transcriptBody);
        firstTranscript = false;
    }

    requestCount++;
    reqCountEl.textContent = requestCount;

    const entry = document.createElement("div");
    entry.className = "transcript-entry";
    const timestamp = new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    entry.innerHTML = `<div class="label">voice_input <span class="dim">${timestamp}</span></div><div class="transcript-text"></div>`;
    transcriptBody.appendChild(entry);
    transcriptBody.scrollTop = transcriptBody.scrollHeight;

    const textEl = entry.querySelector(".transcript-text");
    typeText(textEl, text);
}

function typeText(el, text) {
    let i = 0;
    const cursor = document.createElement("span");
    cursor.className = "typed-cursor";
    el.appendChild(cursor);

    function type() {
        if (i < text.length) {
            el.insertBefore(document.createTextNode(text[i]), cursor);
            i++;
            setTimeout(type, 20 + Math.random() * 20);
        } else {
            setTimeout(() => cursor.remove(), 1000);
        }
    }
    type();
}

// ── Code Streaming ────────────────────────────────────────────────────────

function typeCode(codeEl, code, onDone) {
    const totalLen = code.length;
    const charsPerFrame = Math.max(4, Math.ceil(totalLen / 120));
    let i = 0;

    function tick() {
        if (i < totalLen) {
            codeEl.textContent = code.slice(0, Math.min(i + charsPerFrame, totalLen));
            i += charsPerFrame;
            codeBody.scrollTop = codeBody.scrollHeight;
            requestAnimationFrame(tick);
        } else {
            codeEl.textContent = code;
            if (onDone) onDone();
        }
    }
    tick();
}

// ── Code Tabs ─────────────────────────────────────────────────────────────

function switchTab(tabId) {
    codeTabs.forEach(t => {
        t.blockEl.style.display = t.id === tabId ? "block" : "none";
        t.tabEl.classList.toggle("active", t.id === tabId);
    });
    activeTabId = tabId;
    const active = codeTabs.find(t => t.id === tabId);
    if (active) {
        const span = $("#panel-code .panel-header span:not(.terminal-prompt):not(.panel-tag)");
        if (span) span.textContent = active.filename;
    }
}

function addCode(code, language) {
    if (firstCode) {
        clearBootLines(codeBody);
        firstCode = false;
    }

    updatePreview(code, language);

    const extMap = { python: "py", javascript: "js", html: "html", css: "css", bash: "sh", sql: "sql", typescript: "ts", java: "java", cpp: "cpp", c: "c" };
    const ext = extMap[language.toLowerCase()] || language.toLowerCase();
    const tabId = `tab-${++tabCounter}`;
    const filename = `generated_${tabCounter}.${ext}`;

    // Tab button
    const tabsBar = $("#code-tabs-bar");
    tabsBar.classList.add("visible");
    const tabEl = document.createElement("div");
    tabEl.className = "code-tab";
    tabEl.dataset.tabId = tabId;
    tabEl.textContent = `${language.substring(0, 4).toUpperCase()} #${tabCounter}`;
    tabEl.addEventListener("click", () => switchTab(tabId));
    tabsBar.appendChild(tabEl);

    // Code block (hidden until switchTab shows it)
    const EXEC_LANGS = ["python", "py", "bash", "sh"];
    const isExec = EXEC_LANGS.includes(language.toLowerCase());

    const block = document.createElement("div");
    block.className = "code-block";
    block.dataset.tabId = tabId;
    block.dataset.language = language;
    block.style.display = "none";
    block.innerHTML = `
        <div class="code-block-header">
            <span class="lang-badge">${language}</span>
            <div style="display:flex;gap:0.4rem">
                ${isExec ? `<button class="run-btn" onclick="runCode(this)">&#9654; RUN</button>` : ""}
                <button class="copy-btn" onclick="copyCode(this)">COPY</button>
                <button class="copy-btn" onclick="downloadCode(this,'${filename}')">SAVE</button>
            </div>
        </div>
        <pre><code class="language-${language}"></code></pre>
    `;
    codeBody.appendChild(block);

    codeTabs.push({ id: tabId, language, blockEl: block, tabEl, filename });
    switchTab(tabId);

    // Stream code then apply syntax highlighting
    const codeEl = block.querySelector("code");
    typeCode(codeEl, code, () => {
        if (window.Prism) Prism.highlightElement(codeEl);
    });
}

function updatePreview(code, language) {
    const lang = language.toLowerCase();

    if (lang === "html") {
        previewCode.html = code;
        previewCode.other = null;
    } else if (lang === "css") {
        previewCode.css = code;
        previewCode.other = null;
    } else if (lang === "javascript" || lang === "js") {
        previewCode.js = code;
        previewCode.other = null;
    } else {
        // Non-web: reset web state, store code for code display
        previewCode.html = "";
        previewCode.css = "";
        previewCode.js = "";
        previewCode.other = { code, language };
    }

    // Always show preview panel for any language
    const panels = $(".panels");
    if (panels && !panels.classList.contains("with-preview")) {
        panels.classList.add("with-preview");
    }

    renderPreview();

    const previewPanel = $("#panel-preview");
    if (previewPanel && window.innerWidth <= 768) {
        previewPanel.scrollIntoView({ behavior: "smooth" });
    }
}

function showPreviewImage(dataUri) {
    const panels = $(".panels");
    if (panels && !panels.classList.contains("with-preview")) {
        panels.classList.add("with-preview");
    }

    const iframe       = $("#preview-iframe");
    const codeDisplay  = $("#preview-code-display");
    const imageDisplay = $("#preview-image-display");
    const placeholder  = $("#preview-placeholder");
    const filenameEl   = $("#preview-panel-filename");
    const img          = $("#preview-image");

    iframe.style.display       = "none";
    codeDisplay.style.display  = "none";
    placeholder.style.display  = "none";
    imageDisplay.style.display = "flex";

    img.src = dataUri;
    if (filenameEl) filenameEl.textContent = "exec_output.png";

    // Scroll into view on mobile
    const previewPanel = $("#panel-preview");
    if (previewPanel && window.innerWidth <= 768) {
        previewPanel.scrollIntoView({ behavior: "smooth" });
    }
}

function renderPreview() {
    const iframe        = $("#preview-iframe");
    const codeDisplay   = $("#preview-code-display");
    const imageDisplay  = $("#preview-image-display");
    const codeEl        = $("#preview-code-el");
    const placeholder   = $("#preview-placeholder");
    const filenameEl    = $("#preview-panel-filename");
    const hasWeb        = previewCode.html || previewCode.css || previewCode.js;

    // Nothing to show
    if (!hasWeb && !previewCode.other) {
        iframe.style.display        = "none";
        codeDisplay.style.display   = "none";
        imageDisplay.style.display  = "none";
        placeholder.style.display   = "block";
        return;
    }

    placeholder.style.display = "none";

    if (hasWeb) {
        // ── Web preview (iframe) ────────────────────────────────────────
        iframe.style.display       = "block";
        codeDisplay.style.display  = "none";
        imageDisplay.style.display = "none";

        if (filenameEl) filenameEl.textContent = "live_preview.html";

        let combinedHtml = "";
        if (previewCode.html.toLowerCase().includes("<html") ||
            previewCode.html.toLowerCase().includes("<!doctype")) {
            combinedHtml = previewCode.html;
            if (previewCode.css && !combinedHtml.includes(previewCode.css)) {
                combinedHtml = combinedHtml.replace("</head>", `<style>${previewCode.css}</style></head>`);
            }
            if (previewCode.js && !combinedHtml.includes(previewCode.js)) {
                combinedHtml = combinedHtml.replace("</body>", `<script>${previewCode.js}<\/script></body>`);
            }
        } else {
            combinedHtml = `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>${previewCode.css}</style></head><body>${previewCode.html}<script>${previewCode.js}<\/script></body></html>`;
        }
        iframe.srcdoc = combinedHtml;

    } else if (previewCode.other) {
        // ── Code display for non-web languages ──────────────────────────
        iframe.style.display       = "none";
        codeDisplay.style.display  = "block";
        imageDisplay.style.display = "none";

        const { code, language } = previewCode.other;
        const extMap = { python: "py", javascript: "js", bash: "sh", sql: "sql", typescript: "ts", java: "java", cpp: "cpp", c: "c" };
        const ext = extMap[language.toLowerCase()] || language.toLowerCase();
        if (filenameEl) filenameEl.textContent = `preview.${ext}`;

        codeEl.className   = `language-${language}`;
        codeEl.textContent = code;
        if (window.Prism) Prism.highlightElement(codeEl);
    }
}

// ── ANSI Color Parser ─────────────────────────────────────────────────────

function parseAnsi(text) {
    const colorMap = {
        "1": "ansi-bold",
        "31": "ansi-red",    "32": "ansi-green", "33": "ansi-yellow",
        "34": "ansi-blue",   "35": "ansi-magenta","36": "ansi-cyan",   "37": "ansi-white",
        "91": "ansi-bright-red",    "92": "ansi-bright-green",
        "93": "ansi-bright-yellow", "96": "ansi-bright-cyan",
    };
    let html = "";
    let inSpan = false;
    const regex = /\x1b\[([0-9;]*)m/g;
    let lastIdx = 0;
    let match;
    while ((match = regex.exec(text)) !== null) {
        html += escapeHtml(text.slice(lastIdx, match.index));
        lastIdx = match.index + match[0].length;
        if (inSpan) { html += "</span>"; inSpan = false; }
        const cls = match[1].split(";").map(c => colorMap[c]).filter(Boolean).join(" ");
        if (cls) { html += `<span class="${cls}">`; inSpan = true; }
    }
    html += escapeHtml(text.slice(lastIdx));
    if (inSpan) html += "</span>";
    return html;
}

function addOutput(text) {
    if (firstOutput) {
        clearBootLines(outputBody);
        firstOutput = false;
    }

    const entry = document.createElement("div");
    entry.className = "output-entry";
    entry.innerHTML = parseAnsi(text);
    outputBody.appendChild(entry);
    outputBody.scrollTop = outputBody.scrollHeight;
}

function addAgentMessage(text) {
    if (firstOutput) {
        clearBootLines(outputBody);
        firstOutput = false;
    }

    const entry = document.createElement("div");
    entry.className = "agent-message";
    entry.textContent = text;
    outputBody.appendChild(entry);
    outputBody.scrollTop = outputBody.scrollHeight;
}

function setStatus(status, message) {
    statusDot.className = "status-dot " + status;
    statusText.textContent = message;
    triggerGlitch();
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

// ── Copy Button ───────────────────────────────────────────────────────────

window.copyCode = function (btn) {
    const code = btn.closest(".code-block").querySelector("code").textContent;
    navigator.clipboard.writeText(code).then(() => {
        btn.textContent = "COPIED!";
        btn.classList.add("copied");
        setTimeout(() => {
            btn.textContent = "COPY";
            btn.classList.remove("copied");
        }, 1500);
    });
};

window.downloadCode = function (btn, filename) {
    const code = btn.closest(".code-block").querySelector("code").textContent;
    const blob = new Blob([code], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
    btn.textContent = "SAVED!";
    btn.classList.add("copied");
    setTimeout(() => {
        btn.textContent = "SAVE";
        btn.classList.remove("copied");
    }, 1500);
};

window.runCode = function (btn) {
    const block = btn.closest(".code-block");
    const code = block.querySelector("code").textContent;
    const language = block.dataset.language || "python";
    if (!code.trim() || !ws || ws.readyState !== WebSocket.OPEN) return;

    btn.textContent = "RUNNING…";
    btn.disabled = true;
    btn.classList.add("running");

    wsSend(JSON.stringify({ cmd: "run_code", code, language }));
};

// ── Audio Recording — PCM Streaming (Push-to-Talk) ────────────────────────
//
// We use AudioWorklet (or ScriptProcessor fallback) to capture raw PCM
// 16-bit 16kHz mono and stream it to the server as binary WebSocket frames.

function floatTo16BitPCM(float32Array) {
    const buffer = new ArrayBuffer(float32Array.length * 2);
    const view = new DataView(buffer);
    for (let i = 0; i < float32Array.length; i++) {
        let s = Math.max(-1, Math.min(1, float32Array[i]));
        view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }
    return buffer;
}

async function startRecording() {
    if (isRecording) return;

    try {
        micStream = await navigator.mediaDevices.getUserMedia({
            audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true }
        });

        audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        const source = audioContext.createMediaStreamSource(micStream);

        // Analyser for waveform visualization
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);

        // ScriptProcessor to grab raw PCM and send over WS
        const bufferSize = 4096;
        scriptProcessor = audioContext.createScriptProcessor(bufferSize, 1, 1);
        source.connect(scriptProcessor);
        scriptProcessor.connect(audioContext.destination);

        scriptProcessor.onaudioprocess = (e) => {
            if (!isRecording) return;
            const float32 = e.inputBuffer.getChannelData(0);
            const pcm16 = floatTo16BitPCM(float32);
            wsSend(pcm16);
        };

        // Tell server we started
        wsSend(JSON.stringify({ cmd: "start" }));

        startWaveform();
        setPipelineStep("mic");

        isRecording = true;
        btnMic.classList.add("recording");
        micLabel.textContent = "RECORDING...";
        setStatus("transcribing", "RECORDING");

        // Create the live transcript entry right away
        createLiveTranscriptEntry();

    } catch (err) {
        setStatus("error", "MIC ACCESS DENIED");
        console.error("Mic error:", err);
    }
}

function stopRecording() {
    if (!isRecording) return;
    isRecording = false;

    // Stop the audio processing
    if (scriptProcessor) {
        scriptProcessor.disconnect();
        scriptProcessor = null;
    }
    if (audioContext) {
        audioContext.close();
        audioContext = null;
        analyser = null;
    }
    if (micStream) {
        micStream.getTracks().forEach((t) => t.stop());
        micStream = null;
    }

    stopWaveform();

    // Tell server recording ended
    wsSend(JSON.stringify({ cmd: "end" }));

    btnMic.classList.remove("recording");
    micLabel.textContent = "HOLD TO TALK";
    setStatus("transcribing", "PROCESSING");
    setPipelineStep("stt");
}

// ── Event Listeners ───────────────────────────────────────────────────────

// Mouse
btnMic.addEventListener("mousedown", (e) => { e.preventDefault(); startRecording(); });
btnMic.addEventListener("mouseup", stopRecording);
btnMic.addEventListener("mouseleave", stopRecording);

// Touch
btnMic.addEventListener("touchstart", (e) => { e.preventDefault(); startRecording(); });
btnMic.addEventListener("touchend", stopRecording);
btnMic.addEventListener("touchcancel", stopRecording);

// Keyboard — hold Space
document.addEventListener("keydown", (e) => {
    if (e.code === "Space" && !e.repeat && document.activeElement === document.body) {
        e.preventDefault();
        startRecording();
    }
});
document.addEventListener("keyup", (e) => {
    if (e.code === "Space") stopRecording();
});

// ── Cost Panel Toggle ─────────────────────────────────────────────────────

(function initCostPanel() {
    const toggle = $("#cost-toggle");
    const panel = $("#cost-panel");
    const close = $("#cost-panel-close");

    if (toggle && panel) {
        toggle.addEventListener("click", () => {
            panel.classList.toggle("open");
        });
    }

    if (close && panel) {
        close.addEventListener("click", () => {
            panel.classList.remove("open");
        });
    }

    // Refresh Preview
    const refreshBtn = $("#btn-refresh-preview");
    if (refreshBtn) {
        refreshBtn.addEventListener("click", () => {
            renderPreview();
        });
    }

    // Close Preview Panel
    const closePreviewBtn = $("#preview-panel-close");
    if (closePreviewBtn) {
        closePreviewBtn.addEventListener("click", () => {
            const panels = $(".panels");
            if (panels) {
                panels.classList.remove("with-preview");
            }
        });
    }
})();

// ── Boot ──────────────────────────────────────────────────────────────────

connectWS();
