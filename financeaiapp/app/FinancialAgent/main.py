"""Financial Agent — AgentCore Runtime entrypoint.

Top-level orchestrator invocation with SSE streaming. Each yielded dict
is wrapped as `data: {json}\n\n` by AgentCore's _convert_to_sse.
"""
import uuid

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langchain_core.messages import HumanMessage

from agents.orchestrator import get_orchestrator
from handlers.briefing import generate_briefing
from infra.logging_config import correlation_id_var, get_logger, setup_logging
from tools.sessions import upsert_session

setup_logging()
log = get_logger("main")

app = BedrockAgentCoreApp()

# Custom route: POST /briefing — called by Lambda proxy from EventBridge cron
app.add_route("/briefing", generate_briefing, methods=["POST"])


@app.entrypoint
async def invoke(payload, context):
    """Primary chat entrypoint — streams orchestrator events as SSE."""
    action = payload.get("action", "chat")
    correlation_id = payload.get("correlation_id") or str(uuid.uuid4())
    correlation_id_var.set(correlation_id)

    log.info("invoke.start", action=action)

    if action != "chat":
        yield {"event": "error", "message": f"Unknown action: {action}"}
        return

    session_id = payload.get("session_id") or f"sess-{uuid.uuid4().hex[:12]}"
    message = payload.get("message") or ""

    if not message.strip():
        yield {"event": "error", "message": "Empty message"}
        return

    orchestrator = get_orchestrator()

    yield {
        "event": "session_start",
        "session_id": session_id,
        "correlation_id": correlation_id,
    }

    thread_config = {"configurable": {"thread_id": session_id}}
    input_payload = {"messages": [HumanMessage(content=message)]}

    try:
        # Stream updates mode: emits per-node deltas as the graph runs
        async for chunk in orchestrator.astream(
            input_payload, config=thread_config, stream_mode="updates"
        ):
            for node_name, node_output in chunk.items():
                if not isinstance(node_output, dict) or "messages" not in node_output:
                    continue
                for msg in node_output["messages"]:
                    msg_type = getattr(msg, "type", None)
                    # Tool call events (AI message with tool_calls)
                    if msg_type == "ai" and getattr(msg, "tool_calls", None):
                        for tc in msg.tool_calls:
                            yield {
                                "event": "tool_call",
                                "tool": tc.get("name"),
                                "args": tc.get("args", {}),
                            }
                    # Tool result events
                    elif msg_type == "tool":
                        content = getattr(msg, "content", "")
                        if not isinstance(content, str):
                            content = str(content)
                        yield {
                            "event": "tool_result",
                            "tool": getattr(msg, "name", ""),
                            "content": content[:1000],
                        }
                    # Assistant message (final or streaming segment)
                    elif msg_type == "ai":
                        content = getattr(msg, "content", "")
                        if isinstance(content, str) and content:
                            yield {"event": "assistant", "content": content}

        # Update session metadata (DDB) — truncate title
        title = message[:50]
        try:
            upsert_session(session_id, title=title, increment_message=True)
        except Exception as e:
            log.warning("session.upsert.failed", error=str(e))

        yield {"event": "complete", "session_id": session_id}
        log.info("invoke.complete", session_id=session_id)
    except Exception as e:
        log.exception("invoke.failed")
        yield {"event": "error", "message": str(e)}


if __name__ == "__main__":
    app.run()
