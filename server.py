import os
import argparse
from typing import Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Load .env only for local development, relative to this script's directory
if os.getenv("K_SERVICE") is None:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    dotenv_path = os.path.join(current_dir, ".env")
    load_dotenv(dotenv_path)

# Cloud Run injects PORT and expects the app to listen on 0.0.0.0:$PORT.
# For local stdio development, host/port are unused and safely ignored.
mcp = FastMCP(
    "Slack MCP",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", 8080)),
)


def _bot_client() -> WebClient:
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN is not set.")
    return WebClient(token=token, timeout=30)


def _user_client() -> WebClient:
    token = os.environ.get("SLACK_USER_TOKEN")
    if not token:
        raise RuntimeError("SLACK_USER_TOKEN is not set.")
    return WebClient(token=token, timeout=30)


@mcp.tool()
def send_message(
    channel: str,
    text: str,
    thread_ts: Optional[str] = None,
) -> dict:
    """
    Send a Slack message.

    Args:
        channel: Slack channel ID (e.g. C0123456789)
        text: Message to send
        thread_ts: Optional thread timestamp
    """

    client = _user_client()

    try:
        resp = client.chat_postMessage(
            channel=channel,
            text=text,
            thread_ts=thread_ts,
        )

        return {
            "success": True,
            "channel": resp["channel"],
            "timestamp": resp["ts"],
            "message": "Message sent successfully",
        }

    except SlackApiError as e:
        return {
            "success": False,
            "error": e.response["error"],
        }
@mcp.tool()
def read_channel_history(channel: str, limit: int = 20) -> dict:
    """
    Read recent messages from a Slack channel.

    Args:
        channel: Slack channel ID
        limit: Number of messages to return
    """

    client = _user_client()

    try:
        resp = client.conversations_history(
            channel=channel,
            limit=min(limit, 100),
        )

        messages = resp.get("messages", [])

        return {
            "success": True,
            "count": len(messages),
            "messages": [
                {
                    "timestamp": m.get("ts"),
                    "user": m.get("user"),
                    "text": m.get("text"),
                    "thread_ts": m.get("thread_ts"),
                }
                for m in messages
            ],
        }

    except SlackApiError as e:
        return {
            "success": False,
            "error": e.response["error"],
        }


@mcp.tool()
def list_channels(
    limit: int = 100,
    exclude_archived: bool = True,
) -> dict:
    """
    List channels visible to the workspace.

    Args:
        limit: Maximum number of channels
        exclude_archived: Ignore archived channels
    """

    client = _bot_client()

    try:
        resp = client.conversations_list(
            limit=limit,
            exclude_archived=exclude_archived,
            types="public_channel,private_channel",
        )

        channels = resp.get("channels", [])

        return {
            "success": True,
            "count": len(channels),
            "channels": [
                {
                    "id": c["id"],
                    "name": c["name"],
                    "private": c.get("is_private", False),
                    "is_member": c.get("is_member", False),
                }
                for c in channels
            ],
        }

    except SlackApiError as e:
        return {
            "success": False,
            "error": e.response["error"],
        }    
@mcp.tool()
def list_users(limit: int = 100) -> dict:
    """
    List active users in the workspace.

    Args:
        limit: Maximum number of users to return
    """

    client = _user_client()

    try:
        resp = client.users_list(limit=limit)

        members = [
            u for u in resp.get("members", [])
            if not u.get("deleted")
        ]

        return {
            "success": True,
            "count": len(members),
            "users": [
                {
                    "id": u["id"],
                    "username": u.get("name"),
                    "real_name": u.get("real_name"),
                    "display_name": u.get("profile", {}).get("display_name"),
                    "is_bot": u.get("is_bot", False),
                }
                for u in members
            ],
        }

    except SlackApiError as e:
        return {
            "success": False,
            "error": e.response["error"],
        }


@mcp.tool()
def search_messages(query: str, count: int = 20) -> dict:
    """
    Search Slack messages.

    Requires a User OAuth Token with search:read.

    Args:
        query: Slack search query
        count: Maximum results
    """

    client = _user_client()

    try:
        resp = client.search_messages(
            query=query,
            count=min(count, 100),
        )

        matches = resp.get("messages", {}).get("matches", [])

        return {
            "success": True,
            "count": len(matches),
            "results": [
                {
                    "timestamp": m.get("ts"),
                    "channel": m.get("channel", {}).get("name"),
                    "username": m.get("username"),
                    "text": m.get("text"),
                    "permalink": m.get("permalink"),
                }
                for m in matches
            ],
        }

    except SlackApiError as e:
        return {
            "success": False,
            "error": e.response["error"],
        }


def _selftest() -> None:
    tool_names = sorted(
        t.name for t in mcp._tool_manager.list_tools()
    )

    expected = {
        "send_message",
        "read_channel_history",
        "search_messages",
        "list_channels",
        "list_users",
    }

    missing = expected - set(tool_names)

    print(f"Registered tools: {tool_names}")

    if missing:
        print(f"FAIL: Missing tools: {missing}")
        raise SystemExit(1)

    print("OK: All expected tools registered.")


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Verify tool registration",
    )
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "sse", "streamable-http"],
        help="Transport type (stdio, sse, streamable-http)",
    )

    args = parser.parse_args()

    if args.selftest:
        _selftest()
    else:
        # Default to streamable-http if running in Cloud Run (K_SERVICE is set)
        transport_type = args.transport
        if os.getenv("K_SERVICE") is not None:
            transport_type = "streamable-http"

        mcp.run(
            transport=transport_type
        )