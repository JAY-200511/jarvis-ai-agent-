# J.A.R.V.I.S. — Local desktop assistant

This Windows prototype combines a Hindi/Hinglish-friendly local Ollama chat, always-on browser voice while the page is running, auto-start camera, laptop health readings, and Windows desktop actions. Hand tracking waits for a voice activation command. The animated neural core and robot eyes react to listening, thinking, and speaking states.

## First-time setup

1. Install [Ollama for Windows](https://ollama.com/download/windows).
2. Double-click `setup.bat`. It downloads `qwen3.5:4b` (roughly 3–4 GB). The model runs on your laptop and has no per-message API fee. JARVIS uses only Python's built-in libraries; there is no `pip install` step. You need internet for the first model download; speed depends on your RAM/GPU.
3. Leave Ollama running, then double-click `start_jarvis.bat`.
4. Use the local dashboard at `http://127.0.0.1:8765`. On first launch, allow microphone and camera access in the browser. JARVIS greets you aloud when the dashboard opens, then starts voice listening; speak a command directly without a wake word. Opening `index.html` directly will not connect to the assistant backend.
5. To start JARVIS automatically whenever you sign in to Windows, double-click `enable_startup.bat` once. Remove `JARVIS.lnk` from your Windows Startup folder to turn this off.

If the 4B model is too slow for your machine, set `JARVIS_MODEL` to a smaller Ollama model such as `qwen3.5:0.8b`, pull that model in Ollama, then restart JARVIS. Smaller models may follow complex commands less reliably.

## What works in this build

- Friendly local chat with Hindi, Hinglish, and English replies.
- Spoken replies use Kokoro TTS with a natural English voice by default; Hindi written in Devanagari uses the selected Hindi system voice. Click **LOAD KOKORO MODEL** in Settings or let JARVIS load it on the first reply. The first setup needs internet and downloads about 90 MB plus runtime files; model files are cached in the browser for local use. The first reply uses the system voice while that download runs; later roman-Hinglish replies use Kokoro. The browser Kokoro package supports English voices, so Devanagari Hindi uses the system voice fallback.
- Always-on mic input while the dashboard is open. Every recognized utterance is treated as a command; there is no wake word. Browser speech recognition may send audio to its speech service; it is not guaranteed to be local.
- Camera starts when JARVIS opens. A single still frame goes to the local Ollama model with each spoken command while the camera is on. JARVIS can describe visible expressions, but it cannot reliably know a person's mood.
- Live CPU, RAM, battery, disk, and uptime readings appear in Overview. Ask JARVIS “laptop health kaisi hai?” for a spoken summary.
- Desktop View is enabled while JARVIS runs. It captures a screenshot only when needed for a spoken desktop command. Clearly requested typing/clicking/scrolling runs without an approval card; JARVIS uses only the requested action and exact user-provided text. Windows screen and input control use built-in Win32 APIs through Python's standard library.
- Hand tracking is idle at startup. Say “hand gesture activate” to turn it on; index finger movement moves the pointer. A quick thumb/index pinch clicks, while holding the pinch and moving up/down scrolls. Say “hand gesture stop” to disable it. MediaPipe and its model require internet the first time they load.
- Allow-listed app/site opening: Notepad, Calculator, File Explorer, browser, WhatsApp Desktop (with WhatsApp Web fallback), and Gmail.
- Ask “Jarvis, make me a website for …” to generate a self-contained responsive `index.html` with the local Ollama model. JARVIS saves each project in `OneDrive\\Desktop\\Jarvis-Websites`, opens it in VS Code when installed, and shows a clickable local preview URL. The preview stays available only while the JARVIS server is running; publishing it publicly is not included.
- Clearly requested typing, key presses, clicks, and scrolling run without an extra approval card. JARVIS only types text supplied in your request and asks a brief question if the target or action is unclear.
- Local task queue saved in this browser.
- Recent chat history is saved in this browser so it survives a page reload. The Memory view can clear it. The assistant sends only the latest 12 text messages to Ollama for context. All sidebar sections have working views: voice assistant, tasks, Windows sign-in automation, local memory, app launching, and speech settings.

## WhatsApp and Gmail

Personal WhatsApp opens the Desktop app when its `whatsapp:` link is registered, with WhatsApp Web as a fallback. For a direct request with a clear recipient and exact message, JARVIS can use desktop controls to send without a JARVIS approval card; ambiguous recipients or incomplete message text are not sent. WhatsApp Desktop/Web must already be signed in. The official WhatsApp Cloud API is for WhatsApp Business accounts, not a personal Desktop account.

Gmail currently opens Gmail in your browser. Reading or sending email through an API is not connected yet; that requires a Google OAuth setup and your explicit account authorization.

## Safety and privacy

- The local server binds to `127.0.0.1` and rejects requests from other web origins.
- The model and chat requests go to Ollama on this laptop. The app does not upload camera frames; the selected frame is sent to local Ollama only when you send a chat message while the camera is on.
- Chat text is kept in this browser's local storage (up to 50 recent messages); camera frames are never saved to chat memory. Use **Memory → CLEAR LOCAL MEMORY** to remove the saved conversation.
- Camera, Desktop View, and hand control remain active while JARVIS is running. Use the JARVIS pause control or close the page to stop them.
- JARVIS has no unrestricted command shell. It can open the listed apps/sites. Typing, clicking, scrolling, and key presses run directly only when clearly requested; JARVIS will ask a short question when the target or action is ambiguous.
- Do not send passwords or authentication codes through JARVIS chat.

Voice recognition is browser-based and may use an online speech service. The mic/camera require browser permission. This is an early local agent, not a Windows service: voice, camera, and gesture control stop when you close the JARVIS page. Model warm-up, a short context, and concise replies reduce local response delay; actual speed still depends on laptop hardware. It does not yet access Gmail through its API.
