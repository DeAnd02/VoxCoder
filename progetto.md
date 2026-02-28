# 🏆 VoxCoder — Voice-Powered Code Agent

## Hackathon: Mistral Worldwide Hackathon 2026 (Online Edition)
## Track: "Tutto è concesso" — Best demo using Mistral models via API/OSS
## Prize target: 🎤 Best Voice Use Case (special prize)

---

## 🎯 Concept (One-liner)

**Parli al microfono, un agente AI scrive codice per te in tempo reale.** Un pair-programmer vocale hands-free che combina Voxtral (speech-to-text), Mistral Agents API (orchestrazione + code execution), e una UI web live.

---

## 🏗️ Architecture Overview

```
┌──────────────┐     audio stream      ┌─────────────────────┐
│   Browser     │ ──────────────────►   │  Voxtral Transcribe │
│   (Mic input) │                       │  (mistral API)      │
│   + UI        │ ◄──── transcript ──── └─────────────────────┘
│               │                                │
│  ┌──────────┐ │                                │ transcript text
│  │Code Panel│ │                                ▼
│  │(live)    │ │                       ┌─────────────────────┐
│  │          │ │ ◄── code + output ─── │  Mistral Agents API │
│  │Terminal  │ │                       │  (code_interpreter)  │
│  │Output    │ │                       │  model: mistral-     │
│  └──────────┘ │                       │  large-latest        │
└──────────────┘                        └─────────────────────┘
```

### Flusso:
1. L'utente parla nel microfono del browser
2. L'audio viene registrato in chunk e inviato a **Voxtral Mini Transcribe** via API
3. La trascrizione viene passata come messaggio a un **Mistral Agent** con `code_interpreter` attivo
4. L'Agent scrive codice Python, lo esegue nel sandbox, e restituisce risultato + codice
5. La UI mostra in tempo reale: trascrizione, codice generato, output dell'esecuzione

---

## 🔧 Tech Stack

| Componente | Tecnologia | Motivo |
|---|---|---|
| **Frontend** | HTML/CSS/JS vanilla + WebSocket | Leggero, veloce da buildare. Usa `MediaRecorder` API per catturare audio dal mic |
| **Backend** | Python (FastAPI + WebSockets) | Gestisce il flusso audio→trascrizione→agent→risposta |
| **Speech-to-Text** | Mistral Voxtral API (`voxtral-mini-latest`) | Transcription endpoint, $0.003/min |
| **Agent + Code Exec** | Mistral Agents API (`mistral-large-latest`) con `code_interpreter` | Genera ed esegue codice Python in sandbox |
| **Deploy** | Hugging Face Spaces (Gradio/Docker) oppure locale | Per la demo hackathon |

---

## 📦 Dependencies

```
# requirements.txt
mistralai>=1.0.0
fastapi>=0.100.0
uvicorn>=0.20.0
websockets>=12.0
python-dotenv>=1.0.0
```

---

## 🔑 Environment Variables

```bash
MISTRAL_API_KEY=your_mistral_api_key_here
```

---

## 📋 Implementation Plan (Step-by-step)

### Step 1: Backend — FastAPI server con WebSocket

Crea `server.py`:

- Un endpoint WebSocket `/ws` che:
  - Riceve chunk audio (binary) dal browser
  - Li accumula in un buffer
  - Quando rileva silenzio (o riceve un segnale "end") invia l'audio a Voxtral per trascrizione
  - Invia la trascrizione come messaggio all'Agent
  - Streama indietro al client: trascrizione, codice generato, output esecuzione

### Step 2: Integrazione Voxtral Transcription API

Usa l'endpoint `/v1/audio/transcriptions` di Mistral:

```python
from mistralai import Mistral
import os

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

# Trascrizione da file audio
transcription = client.audio.transcriptions.create(
    model="voxtral-mini-latest",
    file={
        "file_name": "recording.wav",
        "content": audio_bytes,  # bytes dell'audio registrato
    }
)
print(transcription.text)
```

**Parametri importanti:**
- `model`: `"voxtral-mini-latest"` (usa Voxtral Mini Transcribe, ottimizzato per trascrizione)
- Formati audio supportati: `.mp3`, `.wav`, `.m4a`, `.flac`, `.ogg`
- Max file size: 1GB
- Prezzo: $0.003/minuto
- Supporta `language` param per forzare la lingua (es. `"en"`, `"it"`)

### Step 3: Integrazione Mistral Agents API con Code Interpreter

Crea un agent con code execution:

```python
from mistralai import Mistral

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

# Crea l'agent (una volta sola, salva l'agent_id)
code_agent = client.beta.agents.create(
    model="mistral-large-latest",
    name="VoxCoder",
    description="A voice-controlled coding assistant that writes and executes Python code.",
    instructions="""You are VoxCoder, a voice-controlled pair programmer. 
The user speaks commands to you via voice (transcribed to text).

Rules:
- When the user asks to write code, write clean Python code and execute it using the code interpreter.
- Always show the code you wrote AND the execution output.
- Keep responses concise — the user is speaking, not typing.
- If the user says something ambiguous, ask a SHORT clarifying question.
- Support iterative development: the user can say "fix that", "add error handling", "make it faster" etc.
- When the user says "save" or "export", output the final complete code.
- Respond in the same language the user speaks (Italian or English).
""",
    tools=[{"type": "code_interpreter"}],
    completion_args={
        "temperature": 0.3,
        "top_p": 0.9
    }
)

print(f"Agent ID: {code_agent.id}")
```

**Avviare una conversazione:**

```python
# Prima interazione
response = client.beta.conversations.start(
    agent_id=code_agent.id,
    inputs="Write a function to calculate fibonacci numbers and test it with n=10"
)

# Estrarre il risultato
for entry in response.outputs:
    if hasattr(entry, 'content'):
        print(entry.content)
```

**Continuare la conversazione (multi-turn):**

```python
# Turni successivi nella stessa conversazione
response = client.beta.conversations.append(
    conversation_id=response.conversation_id,
    inputs="Now make it use memoization for better performance"
)
```

**Costi:**
- `mistral-large-latest`: $2/M input tokens, $6/M output tokens
- `code_interpreter`: $0.03 per esecuzione
- `web_search` (opzionale): $0.03 per chiamata

### Step 4: Frontend — Browser UI

Crea `index.html` con:

**Layout a 3 pannelli:**
```
┌─────────────────────────────────────────────────┐
│                   VoxCoder 🎤                    │
├────────────────┬────────────────┬────────────────┤
│  TRANSCRIPT    │   CODE         │   OUTPUT       │
│                │                │                │
│  "Write a      │  def fib(n):   │  >>> fib(10)   │
│   fibonacci    │    if n <= 1:  │  55            │
│   function..." │      return n  │                │
│                │    return ...  │  [Executed ✓]  │
│                │                │                │
├────────────────┴────────────────┴────────────────┤
│  [🎤 Hold to Talk]  [⏹ Stop]  Status: Listening │
└─────────────────────────────────────────────────┘
```

**Funzionalità JS del frontend:**

1. **Cattura audio dal microfono** usando `navigator.mediaDevices.getUserMedia()` e `MediaRecorder` API
2. **Push-to-talk** o **Voice Activity Detection (VAD)**: il modo più semplice è push-to-talk (tieni premuto per parlare)
3. **Invio audio via WebSocket** al backend come binary blob
4. **Ricezione risposte** via WebSocket: trascrizione, codice, output — ciascuno renderizzato nel pannello corretto
5. **Syntax highlighting** per il codice: usa [Prism.js](https://prismjs.com/) o [highlight.js](https://highlightjs.org/) inline (CDN)

**Audio recording in JS:**
```javascript
let mediaRecorder;
let audioChunks = [];

async function startRecording() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
    
    mediaRecorder.ondataavailable = (event) => {
        audioChunks.push(event.data);
    };
    
    mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
        audioChunks = [];
        // Invia al backend via WebSocket
        ws.send(audioBlob);
    };
    
    mediaRecorder.start();
}

function stopRecording() {
    mediaRecorder.stop();
}
```

### Step 5: WebSocket Protocol

Definisci un protocollo JSON semplice per i messaggi WebSocket:

**Client → Server:**
```json
// Binary message: raw audio bytes (WAV/WebM)
```

**Server → Client:**
```json
{
    "type": "transcript",
    "text": "Write a fibonacci function and test it"
}
```
```json
{
    "type": "code",
    "language": "python",
    "content": "def fibonacci(n):\n    if n <= 1:\n        return n\n    return fibonacci(n-1) + fibonacci(n-2)\n\nprint(fibonacci(10))"
}
```
```json
{
    "type": "output",
    "content": "55"
}
```
```json
{
    "type": "status",
    "status": "transcribing" | "thinking" | "executing" | "ready" | "error",
    "message": "optional error message"
}
```

### Step 6: Conversione audio (importante!)

Il browser registra in WebM/Opus. L'API Voxtral accetta WAV, MP3, FLAC, OGG, M4A.

Opzione più semplice: converti server-side con `ffmpeg`:

```python
import subprocess
import tempfile

def convert_webm_to_wav(webm_bytes: bytes) -> bytes:
    with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as f_in:
        f_in.write(webm_bytes)
        f_in_path = f_in.name
    
    f_out_path = f_in_path.replace('.webm', '.wav')
    
    subprocess.run([
        'ffmpeg', '-i', f_in_path,
        '-ar', '16000',  # 16kHz sample rate
        '-ac', '1',       # mono
        '-f', 'wav',
        f_out_path
    ], capture_output=True)
    
    with open(f_out_path, 'rb') as f_out:
        return f_out.read()
```

**NOTA:** Assicurati che `ffmpeg` sia installato nell'ambiente. Su HF Spaces Docker è disponibile.

---

## 🎨 UI Design Guidelines

- **Tema scuro** (stile terminale/IDE) — più "developer"
- **Font monospace** per codice (Fira Code, JetBrains Mono via Google Fonts)
- **Animazioni minime** ma impattanti:
  - Pulsing glow sul bottone mic quando attivo
  - Typing effect per la trascrizione
  - Codice che appare riga per riga
- **Colori**: sfondo `#0d1117` (GitHub dark), accent `#f97316` (arancio Mistral), codice `#22c55e` (verde terminale)
- **Logo/brand**: "VoxCoder" con icona microfono + code brackets `{🎤}`

---

## 🚀 MVP Features (must-have per la demo)

1. ✅ Push-to-talk: tieni premuto il bottone, parla, rilascia
2. ✅ Trascrizione live mostrata nella UI
3. ✅ Codice Python generato e mostrato con syntax highlighting
4. ✅ Esecuzione del codice nel sandbox e output mostrato
5. ✅ Multi-turn: puoi dire "ora aggiungi error handling" e il contesto è mantenuto
6. ✅ Indicatori di stato (transcribing → thinking → executing → ready)

## ✨ Nice-to-have (se c'è tempo)

- 🔊 Text-to-Speech per le risposte dell'agent (ElevenLabs API — c'è un premio speciale ElevenLabs!)
- 📋 Bottone "Copy Code" e "Download .py"  
- 🌐 Web search integration per domande tipo "trova la libreria migliore per X"
- 📊 Visualizzazione inline di grafici matplotlib (l'agent può generare immagini)
- 🗂️ Cronologia dei comandi vocali con possibilità di replay

---

## 📁 Project Structure

```
voxcoder/
├── server.py              # FastAPI backend + WebSocket handler
├── agent.py               # Mistral Agent creation & conversation logic
├── transcriber.py         # Voxtral transcription wrapper
├── audio_utils.py         # Audio conversion (webm→wav via ffmpeg)
├── static/
│   ├── index.html         # Main UI page
│   ├── style.css          # Dark theme styling
│   ├── app.js             # Frontend logic (mic, websocket, rendering)
│   └── prism.js           # Syntax highlighting (bundle from CDN)
├── requirements.txt
├── Dockerfile             # Per HF Spaces deploy
├── README.md              # Project description per hackathon submission
└── .env.example
```

---

## 🐳 Dockerfile (per HF Spaces)

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "7860"]
```

---

## 📊 API Cost Estimate (per la demo)

| Servizio | Uso stimato | Costo |
|---|---|---|
| Voxtral Transcribe | ~30 min totali di audio | ~$0.09 |
| Mistral Large (agent) | ~50 interazioni | ~$0.50 |
| Code Interpreter | ~50 esecuzioni | ~$1.50 |
| **Totale demo** | | **~$2.10** |

I crediti dell'hackathon coprono ampiamente.

---

## 🏁 Demo Script (2 minuti per il video)

1. **[0:00-0:15]** "Hi, I'm presenting VoxCoder — a voice-controlled coding assistant powered entirely by Mistral AI."
2. **[0:15-0:45]** Primo comando: "Create a function that takes a list of numbers and returns the mean, median, and standard deviation" → mostra codice generato + esecuzione
3. **[0:45-1:15]** Follow-up vocale: "Now add a visualization — plot a histogram of a random sample using matplotlib" → mostra il grafico inline
4. **[1:15-1:40]** "Add error handling for empty lists and non-numeric values" → mostra il codice aggiornato
5. **[1:40-2:00]** "VoxCoder combines Voxtral for voice, the Agents API for orchestration, and Code Interpreter for execution — all Mistral. Thanks!"

---

## ⚠️ Gotchas & Tips

1. **CORS**: FastAPI deve servire i file statici E il WebSocket dallo stesso server per evitare problemi CORS con il microfono
2. **HTTPS**: `getUserMedia()` richiede HTTPS (o localhost). HF Spaces fornisce HTTPS automaticamente.
3. **Audio format**: Il browser registra in WebM/Opus. DEVI convertire a WAV prima di inviare a Voxtral.
4. **Agent persistence**: Crea l'agent UNA volta all'avvio del server e riusa l'`agent_id`. Crea una nuova `conversation_id` per ogni sessione utente.
5. **Rate limits**: L'API Voxtral ha limiti. Non inviare chunk troppo piccoli — accumula almeno 2-3 secondi di audio prima di trascrivere.
6. **Timeout**: Il code_interpreter può impiegare qualche secondo. Mostra un indicatore di loading nella UI.
7. **Modelli supportati per Agents API**: attualmente `mistral-medium-latest` e `mistral-large-latest`. DevStral NON è ancora supportato direttamente nell'Agents API (ma il code_interpreter è built-in e funziona con Large/Medium).

---

## 📚 Reference Links

- Mistral Python SDK: https://github.com/mistralai/client-python
- Voxtral Transcription Docs: https://docs.mistral.ai/capabilities/audio_transcription
- Voxtral API Endpoint: https://docs.mistral.ai/api/endpoint/audio/transcriptions
- Agents API Introduction: https://docs.mistral.ai/agents/introduction
- Agents & Conversations: https://docs.mistral.ai/agents/agents
- Agents API Blog: https://mistral.ai/news/agents-api
- Code Interpreter Tool: type `code_interpreter` nel tools array dell'agent
- Hackathon Page: https://huggingface.co/mistral-hackaton-2026
- Hackathon Platform: https://hackiterate.com
- Discord: https://discord.gg/zdSEmdfkSQ