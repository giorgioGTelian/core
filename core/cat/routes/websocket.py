import traceback
import asyncio
from typing import Dict
from fastapi import APIRouter, WebSocketDisconnect, WebSocket
from cat.log import log
from fastapi.concurrency import run_in_threadpool

router = APIRouter()

# This constant sets the interval (in seconds) at which the system checks for notifications.
QUEUE_CHECK_INTERVAL = 1  # seconds


class ConnectionManager:
    """
    Manages active WebSocket connections.
    """

    def __init__(self):
        # List to store all active WebSocket connections.
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, user_id: str = "user"):
        """
        Accept the incoming WebSocket connection and add it to the active connections list.
        """
        await websocket.accept()
        self.active_connections[user_id].append(websocket)

    def disconnect(self, ccat: object, user_id: str = "user"):
        """
        Remove the given WebSocket from the active connections list.
        """
        del self.active_connections[user_id]
        del ccat.ws_messages[user_id]

    async def send_personal_message(self, message: str, user_id: str = "user"):
        """
        Send a personal message (in JSON format) to the specified WebSocket.
        """
        await self.active_connections[user_id].send_json(message)

    async def broadcast(self, message: str):
        """
        Send a message to all active WebSocket connections.
        """
        for connection in self.active_connections.values():
            await connection.send_json(message)


manager = ConnectionManager()


async def receive_message(ccat: object, user_id: str = "user"):
    """
    Continuously receive messages from the WebSocket and forward them to the `ccat` object for processing.
    """
    ws = manager.active_connections[user_id]
    while True:
        user_message = await ws.receive_json()

        # Run the `ccat` object's method in a threadpool since it might be a CPU-bound operation.
        cat_message = await run_in_threadpool(ccat, user_message)

        # Send the response message back to the user.
        await manager.send_personal_message(cat_message, ws)


async def check_messages(ccat, user_id: str = "user"):
    """
    Periodically check if there are any new notifications from the `ccat` instance and send them to the user.
    """
    while True:

        # extract from FIFO list websocket notification
        notification = await ccat.ws_messages[user_id].get()
        await manager.send_personal_message(notification, manager.active_connections[user_id])


@router.websocket_route("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Endpoint to handle incoming WebSocket connections, process messages, and check for messages.
    """

    # Retrieve the `ccat` instance from the application's state.
    ccat = websocket.app.state.ccat

    # Add the new WebSocket connection to the manager.
    await manager.connect(websocket)

    try:
        # Process messages and check for notifications concurrently.
        await asyncio.gather(
            receive_message(ccat),
            check_messages(ccat)
        )
    except WebSocketDisconnect:
        # Handle the event where the user disconnects their WebSocket.
        log.info("WebSocket connection closed")
    except Exception as e:
        # Log any unexpected errors and send an error message back to the user.
        log.error(e)
        traceback.print_exc()
        await manager.send_personal_message({
            "type": "error",
            "name": type(e).__name__,
            "description": str(e),
        }, websocket)
    finally:
        # Always ensure the WebSocket is removed from the manager, regardless of how the above block exits.
        manager.disconnect(ccat, websocket)


@router.websocket_route("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """
    Endpoint to handle incoming WebSocket connections by user id.
    """

    # Retrieve the `ccat` instance from the application's state.
    ccat = websocket.app.state.ccat

    # Add the new WebSocket connection to the manager.
    await manager.connect(websocket, user_id)

    try:
        # Process messages and check for notifications concurrently.
        await asyncio.gather(
            receive_message(ccat, user_id),
            check_messages(ccat, user_id)
        )
    except WebSocketDisconnect:
        # Handle the event where the user disconnects their WebSocket.
        log.info("WebSocket connection closed")
    except Exception as e:
        # Log any unexpected errors and send an error message back to the user.
        log.error(e)
        traceback.print_exc()
        await manager.send_personal_message({
            "type": "error",
            "name": type(e).__name__,
            "description": str(e),
        }, websocket)
    finally:
        # Always ensure the WebSocket is removed from the manager, regardless of how the above block exits.
        manager.disconnect(ccat, websocket)
