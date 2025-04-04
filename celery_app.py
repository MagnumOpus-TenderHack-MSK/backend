import os
from celery import Celery
from app.core.config import settings

os.environ.setdefault('CELERY_BROKER_URL', settings.CELERY_BROKER_URL)
os.environ.setdefault('CELERY_RESULT_BACKEND', settings.CELERY_RESULT_BACKEND)

# Create Celery app
app = Celery('chat_backend')

# Configure Celery
app.config_from_object('app.core.config', namespace='CELERY')

# Auto-discover tasks
app.autodiscover_tasks([
    'app.tasks.file_tasks',
    'app.tasks.message_tasks',
])

app.conf.beat_schedule = {
}

if __name__ == '__main__':
    app.start()