"""
German Call Center AI Agent — Server
FastAPI backend that bridges browser audio with Gemini Live API.
"""

import asyncio
import base64
import json
import logging
import os
import traceback

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from google import genai
from google.genai import types

from knowledge_base import kb

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("server")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not set in .env file")

MODEL = "gemini-3.1-flash-live-preview"
INPUT_SAMPLE_RATE = 16000

app = FastAPI(title="German Call Center AI Agent")

# Serve static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/api/companies")
async def get_companies():
    """Return available companies for the dropdown."""
    companies = []
    for cid in kb.get_company_ids():
        companies.append({
            "id": cid,
            "name": kb.get_company_name(cid)
        })
    return {"companies": companies}


@app.websocket("/ws/call/{company_id}")
async def websocket_call(websocket: WebSocket, company_id: str):
    """
    WebSocket endpoint for a live call session.
    Browser sends: base64-encoded PCM audio chunks
    Server sends back: base64-encoded PCM audio response chunks + transcript events
    """
    await websocket.accept()
    logger.info(f"WebSocket connected for company: {company_id}")

    company_data = kb.get_company_info(company_id)
    if not company_data:
        await websocket.send_json({"type": "error", "message": f"Unknown company: {company_id}"})
        await websocket.close()
        return

    # Initialize Gemini client
    client = genai.Client(api_key=GEMINI_API_KEY)

    # Build tool declarations
    tool_declarations = kb.get_tool_declarations()
    tools = [types.Tool(function_declarations=[
        types.FunctionDeclaration(**decl) for decl in tool_declarations
    ])]

    # Build tool mapping
    def handle_search_knowledge(query: str = "") -> str:
        return kb.search_knowledge(company_id, query)

    def handle_check_escalation(customer_message: str = "") -> dict:
        return kb.check_escalation(company_id, customer_message)

    tool_mapping = {
        "search_knowledge": handle_search_knowledge,
        "check_escalation": handle_check_escalation,
    }

    # System prompt
    system_prompt = kb.get_system_prompt(company_id)

    # Configure Gemini Live session
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Aoede"
                )
            )
        ),
        system_instruction=types.Content(
            parts=[types.Part(text=system_prompt)]
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            turn_coverage="TURN_INCLUDES_ONLY_ACTIVITY",
        ),
        tools=tools,
    )

    audio_input_queue = asyncio.Queue()
    session_active = True

    try:
        async with client.aio.live.connect(model=MODEL, config=config) as session:
            logger.info("Gemini Live session opened")
            await websocket.send_json({"type": "status", "message": "connected"})

            # Trigger the AI to greet the customer immediately
            await session.send_client_content(
                turns=[types.Content(
                    role="user",
                    parts=[types.Part(text="Der Kunde hat gerade angerufen. Begrüße ihn.")]
                )],
                turn_complete=True
            )
            logger.info("Sent initial greeting trigger to Gemini")

            # Task: Read audio from browser WebSocket → queue for Gemini
            async def read_from_browser():
                nonlocal session_active
                try:
                    while session_active:
                        raw = await websocket.receive_text()
                        msg = json.loads(raw)
                        if msg.get("type") == "audio":
                            audio_bytes = base64.b64decode(msg["data"])
                            await audio_input_queue.put(audio_bytes)
                        elif msg.get("type") == "stop":
                            session_active = False
                            break
                except WebSocketDisconnect:
                    logger.info("Browser WebSocket disconnected")
                    session_active = False
                except Exception as e:
                    logger.error(f"read_from_browser error: {e}")
                    session_active = False

            # Task: Send audio from queue to Gemini
            async def send_audio_to_gemini():
                try:
                    while session_active:
                        try:
                            chunk = await asyncio.wait_for(audio_input_queue.get(), timeout=0.5)
                            await session.send_realtime_input(
                                audio=types.Blob(
                                    data=chunk,
                                    mime_type=f"audio/pcm;rate={INPUT_SAMPLE_RATE}"
                                )
                            )
                        except asyncio.TimeoutError:
                            continue
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"send_audio_to_gemini error: {e}\n{traceback.format_exc()}")

            # Task: Receive from Gemini → send to browser
            async def receive_from_gemini():
                nonlocal session_active
                try:
                    while session_active:
                        async for response in session.receive():
                            if not session_active:
                                break

                            server_content = response.server_content
                            tool_call = response.tool_call

                            if server_content:
                                # Audio response chunks
                                if server_content.model_turn:
                                    for part in server_content.model_turn.parts:
                                        if part.inline_data:
                                            audio_b64 = base64.b64encode(part.inline_data.data).decode("utf-8")
                                            try:
                                                await websocket.send_json({
                                                    "type": "audio",
                                                    "data": audio_b64
                                                })
                                            except:
                                                session_active = False
                                                return

                                # Input transcription (what the user said)
                                if server_content.input_transcription and server_content.input_transcription.text:
                                    try:
                                        await websocket.send_json({
                                            "type": "transcript_user",
                                            "text": server_content.input_transcription.text
                                        })
                                    except:
                                        session_active = False
                                        return

                                # Output transcription (what the AI said)
                                if server_content.output_transcription and server_content.output_transcription.text:
                                    try:
                                        await websocket.send_json({
                                            "type": "transcript_agent",
                                            "text": server_content.output_transcription.text
                                        })
                                    except:
                                        session_active = False
                                        return

                                # Turn complete
                                if server_content.turn_complete:
                                    try:
                                        await websocket.send_json({"type": "turn_complete"})
                                    except:
                                        session_active = False
                                        return

                                # Interrupted (barge-in)
                                if server_content.interrupted:
                                    try:
                                        await websocket.send_json({"type": "interrupted"})
                                    except:
                                        session_active = False
                                        return

                            # Handle tool calls
                            if tool_call:
                                function_responses = []
                                for fc in tool_call.function_calls:
                                    func_name = fc.name
                                    args = fc.args or {}
                                    logger.info(f"Tool call: {func_name}({args})")

                                    try:
                                        await websocket.send_json({
                                            "type": "tool_call",
                                            "name": func_name,
                                            "args": args
                                        })
                                    except:
                                        pass

                                    if func_name in tool_mapping:
                                        try:
                                            result = tool_mapping[func_name](**args)
                                            if isinstance(result, dict):
                                                result_str = json.dumps(result, ensure_ascii=False)
                                            else:
                                                result_str = str(result)
                                        except Exception as e:
                                            result_str = f"Fehler: {e}"
                                            logger.error(f"Tool execution error: {e}")

                                        function_responses.append(types.FunctionResponse(
                                            name=func_name,
                                            id=fc.id,
                                            response={"result": result_str}
                                        ))
                                    else:
                                        function_responses.append(types.FunctionResponse(
                                            name=func_name,
                                            id=fc.id,
                                            response={"error": f"Unknown function: {func_name}"}
                                        ))

                                if function_responses:
                                    await session.send_tool_response(function_responses=function_responses)

                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"receive_from_gemini error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
                    try:
                        await websocket.send_json({"type": "error", "message": str(e)})
                    except:
                        pass
                    session_active = False

            # Run all tasks concurrently
            tasks = [
                asyncio.create_task(read_from_browser()),
                asyncio.create_task(send_audio_to_gemini()),
                asyncio.create_task(receive_from_gemini()),
            ]

            # Wait until session ends
            await asyncio.gather(*tasks, return_exceptions=True)

    except Exception as e:
        logger.error(f"Session error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        logger.info(f"Session closed for company: {company_id}")
        try:
            await websocket.close()
        except:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
