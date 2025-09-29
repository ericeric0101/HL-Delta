#!/usr/bin/env python3
"""
Delta Bot Entrypoint

This script initializes and runs a Delta trading bot with an API server
for remote control and monitoring.
"""

import os
import logging
import asyncio
import signal
import sys
import json
from contextlib import suppress
from dotenv import load_dotenv

# Load environment variables first to get version info
load_dotenv()

# Bot version information
__version__ = os.getenv("BOT_VERSION", "1.0.0")
BOT_NAME = "Delta"

# Import the Delta bot
from Delta import Delta

# Import API module (will be created later)
from api import start_api, stop_api
from api.websocket_manager import WebSocketLogHandler, manager

# Global reference to the bot instance
delta_bot = None
shutdown_event: asyncio.Event | None = None
_shutdown_in_progress = False


async def graceful_shutdown(bot_instance: Delta, event: asyncio.Event) -> None:
    """Graceful shutdown of the Delta bot and API server."""
    logger = logging.getLogger("DeltaBot")

    global _shutdown_in_progress
    if _shutdown_in_progress:
        logger.debug("Shutdown already in progress; ignoring duplicate signal")
        return
    _shutdown_in_progress = True

    logger.info("Shutting down gracefully...")

    # Stop the API server
    await stop_api()

    # Close all positions
    if bot_instance:
        await bot_instance.exit_program(close_positions=True)

    event.set()


async def main():
    """Main entry point for running the Delta bot."""
    global delta_bot
    global shutdown_event
    
    # Set up logging
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    log_datefmt = '%Y-%m-%d %H:%M:%S'
    
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=log_datefmt,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("delta.log")
        ]
    )

    loop = asyncio.get_running_loop()

    # Add the WebSocket handler to the root logger
    ws_handler = WebSocketLogHandler(manager, loop=loop)
    ws_handler.setFormatter(logging.Formatter(log_format, datefmt=log_datefmt))
    logging.getLogger().addHandler(ws_handler)

    logger = logging.getLogger("DeltaBot")
    
    logger.info(f"Initializing {BOT_NAME} bot v{__version__}...")
    
    # Create the Delta bot instance
    delta_bot = Delta()
    await delta_bot.initialize()
    
    # Prepare shutdown coordination primitives
    shutdown_event = asyncio.Event()

    # Register signal handlers for graceful shutdown
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(
            sig, lambda s=sig: asyncio.create_task(graceful_shutdown(delta_bot, shutdown_event))
        )

    # Load API configuration from environment
    api_host = os.getenv("API_HOST", "0.0.0.0")
    api_port = int(os.getenv("API_PORT", "8080"))
    api_enabled = os.getenv("API_ENABLED", "true").lower() in ("true", "1", "yes")
    
    # Start API server if enabled
    if api_enabled and os.environ.get('API_SECRET_KEY'):
        logger.info(f"Starting API server on {api_host}:{api_port}")
        await start_api(delta_bot, host=api_host, port=api_port)
        logger.info("API server started")
    else:
        logger.warning("API server is disabled (either API_SECRET_KEY not set or API_ENABLED=false)")
    
    # Check the autostart setting from the configuration loaded by the bot
    autostart_from_config = delta_bot.config.get("general", {}).get("autostart", True)

    bot_task = None
    if autostart_from_config:
        logger.info(f"Autostarting {BOT_NAME} based on config.json...")
        bot_task = asyncio.create_task(delta_bot.start(), name="delta-bot-loop")
    else:
        logger.info(f"{BOT_NAME} initialized in standby mode (autostart is false in config.json).")
        logger.info("API server is running. Use the frontend or API to start the bot manually.")

    try:
        await shutdown_event.wait()
    finally:
        if bot_task:
            bot_task.cancel()
            with suppress(asyncio.CancelledError):
                await bot_task


if __name__ == "__main__":
    try:
        print(f"\n{BOT_NAME} Bot v{__version__} - HyperVault Trading Bots")
        print("=" * 50)
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.getLogger("DeltaBot").info("Application terminated by user")
    except Exception as e:
        logging.getLogger("DeltaBot").error(f"Application error: {e}") 
