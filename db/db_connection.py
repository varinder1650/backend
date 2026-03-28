# db/db_connection.py
import motor.motor_asyncio
from dotenv import load_dotenv
import os

load_dotenv()

def _create_client():
    """Create a Motor client with proper connection pool settings."""
    pool_size = int(os.getenv('DB_CONNECTION_POOL_SIZE', 10))
    return motor.motor_asyncio.AsyncIOMotorClient(
        os.getenv('MONGO_URI'),
        maxPoolSize=pool_size,
        minPoolSize=1,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=10000,
        socketTimeoutMS=20000,
        retryWrites=True,
        retryReads=True,
    )

# Only create global client if NOT in test environment
if os.getenv('ENVIRONMENT') != 'Testing':
    client = _create_client()
else:
    client = None  # Will be created per-test

def get_connection():
    # In testing, create a fresh connection
    if os.getenv('ENVIRONMENT') == 'Testing':
        return _create_client()

    return client