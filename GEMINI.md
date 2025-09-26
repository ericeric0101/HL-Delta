# GEMINI.md: HyperVault Delta Bot

This document provides a comprehensive overview of the HyperVault Delta Bot project, its structure, and how to build, run, and interact with it.

## Project Overview

This is a full-stack application for a delta-neutral trading bot designed for the HyperLiquid exchange. The project consists of:

*   **Backend:** A Python application that implements the core trading logic. It uses the `hyperliquid-python-sdk` to interact with the exchange and FastAPI to expose a RESTful API for control and monitoring.
*   **Frontend:** A React-based user interface built with TypeScript and Material-UI for monitoring the bot's status and performance.
*   **Deployment:** The application is containerized using Docker for easy deployment.

The bot's primary strategy is to create delta-neutral positions by taking long positions in the spot market and short positions in the perpetual futures market to earn funding rates. It automatically identifies the best opportunities and can rebalance positions.

## Key Files

*   `Delta.py`: The main entry point and core logic for the trading bot.
*   `api/app.py`: The FastAPI server that provides endpoints for interacting with the bot.
*   `frontend/src/App.tsx`: The main component of the React frontend.
*   `config.json`: The primary configuration file for the bot's trading parameters.
*   `requirements.txt`: Python dependencies for the backend.
*   `frontend/package.json`: Node.js dependencies for the frontend.
*   `Dockerfile`: Defines the Docker image for the application.
*   `build.sh`: A script for building the Docker image.
*   `README.md`: The main project documentation.

## Building and Running

### Backend

1.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
2.  **Set up environment variables:**
    Create a `.env` file with the following:
    ```
    HYPERLIQUID_PRIVATE_KEY=your_private_key
    HYPERLIQUID_ADDRESS=your_eth_address
    API_SECRET_KEY=your_api_secret
    ```
3.  **Run the bot:**
    ```bash
    python entrypoint.py
    ```
    This will start the bot and the API server.

### Frontend

1.  **Navigate to the frontend directory:**
    ```bash
    cd frontend
    ```
2.  **Install dependencies:**
    ```bash
    npm install
    ```
3.  **Set up environment variables:**
    Create a `.env` file in the `frontend` directory:
    ```
    REACT_APP_API_KEY=your_api_secret
    ```
4.  **Start the development server:**
    ```bash
    npm start
    ```
    The frontend will be available at `http://localhost:3000`.

### Docker

1.  **Build the Docker image:**
    ```bash
    ./build.sh
    ```
2.  **Run the container:**
    ```bash
    docker run -d \
      --name delta-bot \
      -p 8080:8080 \
      --env-file .env \
      hypervault-tradingbot:delta-1.0.0
    ```

## Development Conventions

*   **Configuration:** The bot is configured primarily through `config.json`. Sensitive information like API keys and private keys are managed through environment variables.
*   **API:** The backend provides a RESTful API for controlling and monitoring the bot. The API is secured with a secret key.
*   **Code Style:** The Python code is structured into modules for the API, routes, and utilities. The frontend follows the standard Create React App structure.
*   **Versioning:** The project version is managed in the `VERSION` file and can be updated using the `update_version.sh` script.
*   **Logging:** The bot uses the `logging` module for comprehensive logging to both the console and a `delta.log` file.
