## Getting Started

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for local development)

### Environment Variables

Create a `.env` file in the project root with the following variables:

```env
# Application settings
APP_NAME="Chat Application"
APP_VERSION="1.0"
APP_HOST="0.0.0.0"
APP_PORT=8000
DEBUG=true

# Database settings
DB_DRIVER=postgresql
DB_HOST=postgres
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=postgres
DB_NAME=chat_db

# JWT settings
JWT_SECRET=your_super_secret_key_change_in_production
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60

# Redis settings
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0

# Celery settings
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2

# File upload settings
UPLOAD_DIR=static/uploads
MAX_UPLOAD_SIZE=10485760  # 10 MB

# External services
AI_SERVICE_URL=http://ai-service:8080/process
AI_SERVICE_API_KEY=your_ai_service_api_key

PREVIEW_SERVICE_URL=https://preview.akarpov.ru
PREVIEW_SERVICE_API_KEY=your_preview_service_api_key

# Cors settings (for development)
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000
```

### Running with Docker Compose

1. Build and start the services:

```bash
docker-compose up -d
```

2. The API will be available at http://localhost:8000

3. API documentation is available at http://localhost:8000/docs

### Running Locally for Development

1. Create and activate a virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install uv:

```bash
pip install uv
```

3. Install dependencies:

```bash
uv pip install -r requirements.txt
```

4. Create the database:

```bash
# Using PostgreSQL CLI
createdb chat_db

# Or in PostgreSQL shell
# psql -U postgres
# CREATE DATABASE chat_db;
```

5. Run database migrations:

```bash
alembic upgrade head
```

6. Start the FastAPI server:

```bash
uvicorn app.main:app --reload
```

7. In a separate terminal, start a Celery worker:

```bash
celery -A celery_app worker --loglevel=info
```

8. Optionally, start Celery beat for scheduled tasks:

```bash
celery -A celery_app beat --loglevel=info
```

## API Documentation

When the application is running, you can access the interactive API documentation at:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## WebSocket Protocol

The WebSocket endpoint is available at:

```
ws://localhost:8000/ws/chat/{chat_id}?token={jwt_token}
```

### Client to Server Messages

```json
// Ping message
{
  "type": "ping",
  "timestamp": 1635000000000
}

// Request message content
{
  "type": "stream_request",
  "message_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Server to Client Messages

```json
// Pong response
{
  "type": "pong",
  "timestamp": 1635000000000
}

// Stream content
{
  "type": "stream_content",
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "content": "Hello, how can I help you?"
}

// Message chunk during streaming
{
  "type": "chunk",
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "content": " world"
}

// Message complete
{
  "type": "complete",
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "sources": [
    {
      "title": "Document Title",
      "url": "https://example.com",
      "content": "Relevant content snippet"
    }
  ]
}

// Error
{
  "error": "Error message"
}
```

## AI Service Integration

The application integrates with an external AI service for processing messages. The service is expected to:

1. Receive a POST request with:
   - `message`: The user's message
   - `conversation_history`: Previous messages in the chat
   - `callback_url`: URL to send responses back to

2. Send responses to the callback URL:
   - Send chunks of the response as they are generated
   - Send a final complete message when done

## File Processing

Files are processed using the external preview service:

1. Files are uploaded and stored locally
2. A background task sends the file to the preview service
3. The service extracts text content and generates a preview
4. The content and preview are stored in the database

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Commit your changes: `git commit -m 'Add feature'`
4. Push to the branch: `git push origin feature-name`
5. Submit a pull request

## License

This project is licensed under the MIT License.