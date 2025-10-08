# import motor.motor_asyncio
# from dotenv import load_dotenv
# import os

# load_dotenv()

# client = motor.motor_asyncio.AsyncIOMotorClient(os.getenv('MONGO_URI'))

# def get_connection():
#     if client:
#         return client

# db/db_connection.py
import motor.motor_asyncio
from dotenv import load_dotenv
import os

load_dotenv()

# Only create global client if NOT in test environment
if os.getenv('ENVIRONMENT') != 'Testing':
    client = motor.motor_asyncio.AsyncIOMotorClient(os.getenv('MONGO_URI'))
else:
    client = None  # Will be created per-test

def get_connection():
    # In testing, create a fresh connection
    if os.getenv('ENVIRONMENT') == 'Testing':
        return motor.motor_asyncio.AsyncIOMotorClient(os.getenv('MONGO_URI'))
    
    return client