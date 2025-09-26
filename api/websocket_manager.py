import asyncio
import logging
import re
from typing import List
from fastapi import WebSocket

class ConnectionManager:
    """Manages active WebSocket connections for broadcasting messages."""
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """Disconnect a WebSocket."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        """Broadcast a message to all active connections."""
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                # The connection might have closed, remove it.
                self.disconnect(connection)

# Create a single instance of the manager to be used across the application
manager = ConnectionManager()

class WebSocketLogHandler(logging.Handler):
    """A custom logging handler that broadcasts log records to WebSockets."""

    def __init__(self, manager_instance: ConnectionManager, loop: asyncio.AbstractEventLoop | None = None):
        super().__init__()
        self.manager = manager_instance
        self.loop = loop
        # Regex to strip ANSI escape codes
        self.ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

    def emit(self, record):
        """Emit a log record."""
        try:
            msg = self.format(record)

            loop = self.loop
            if loop is None:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

            if loop and loop.is_running():
                try:
                    # If we're in the same event loop thread, use create_task
                    if asyncio.get_running_loop() is loop:
                        asyncio.create_task(self.manager.broadcast(msg))
                    else:
                        asyncio.run_coroutine_threadsafe(self.manager.broadcast(msg), loop)
                except RuntimeError:
                    # No running loop in this thread; fall back to thread-safe scheduling
                    asyncio.run_coroutine_threadsafe(self.manager.broadcast(msg), loop)
            else:
                # As a last resort, run the coroutine synchronously
                asyncio.run(self.manager.broadcast(msg))
        except Exception:
            self.handleError(record)
