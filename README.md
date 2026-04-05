# 📞 German Call Center AI Agent (Gemini Live)

A high-performance, real-time AI Call Center Agent built with the **Gemini 3.1 Flash Live API** and **FastAPI**. This system is designed to handle customer service interactions in German, utilizing a RAG-based knowledge base for accurate, company-specific responses.

---

## ✨ Features

- 🎧 **Real-Time Audio**: Low-latency, full-duplex voice interaction using WebSockets and the Gemini Live API.
- 🇩🇪 **German Proficiency**: Optimized for natural, professional German conversations.
- 📚 **RAG Integration**: Dynamic knowledge base management (JSON-based) with keyword-based retrieval.
- 🛠️ **Function Calling**: Automated tool usage for knowledge search and escalation management.
- 👤 **Company Profiles**: Support for multiple company profiles (e.g., Otto.de) with specific greetings and rules.
- 🚀 **Modern Web UI**: A sleek, responsive browser-based interface for live call sessions.

---

## 🛠️ Installation

### 1. Prerequisites
- **Python 3.10+** (Recommended)
- **Gemini API Key**: Obtain one from the [Google AI Studio](https://aistudio.google.com/app/apikey).

### 2. Clone & Setup
Clone the repository and create a virtual environment:
```bash
git clone https://github.com/drin23/asd.git
cd "callcenter agent"
python -m venv venv
source venv/Scripts/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

---

## ⚙️ Configuration

Create a `.env` file in the root directory (already added to `.gitignore`) and add your API key:

```env
GEMINI_API_KEY=your_gemini_api_key_here
```

---

## 🚀 Usage

### 1. Start the Server
Run the FastAPI application:
```bash
python server.py
```
*Note: The server will start on `http://0.0.0.0:8000` by default.*

### 2. Open the UI
1. Open your browser and navigate to `http://localhost:8000`.
2. Select a company (e.g., **Otto.de**).
3. Click "Start Call" and grant microphone permissions.
4. Speak normally in German!

---

## 📂 Project Structure

- `server.py`: The FastAPI backend orchestrating WebSocket connections and Gemini Live sessions.
- `knowledge_base.py`: Handles RAG logic, tool declarations, and system prompts.
- `knowledge/`: Directory containing company-specific JSON knowledge bases.
- `static/`: Frontend assets (HTML, CSS, JS).
- `requirements.txt`: Python package dependencies.
- `.env`: Environment variables (API Keys).

---

## 🔍 How it Works

1. **Audio Flow**: The browser captures PCM audio (16kHz), encodes it to Base64, and sends it via WebSocket to the server.
2. **Gemini Live**: The server pipes this audio directly to the Gemini 3.1 Flash Live API.
3. **Reasoning**: Gemini processes the audio, uses functions/tools if needed, and returns audio & transcriptions.
4. **Output**: The server forwards the AI's audio response back to the browser for real-time playback.

---

## 🤝 Contributing
Feel free to open issues or submit pull requests for improvements.

## 📄 License
This project is licensed under the MIT License.
