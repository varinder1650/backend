# from typing import Dict,Any,List
# from db.db_connection import get_connection
# from motor.motor_asyncio import AsyncIOMotorClient
# from dotenv import load_dotenv
# import os
# import logging

# load_dotenv()

# logger = logging.getLogger(__name__)

# class DatabaseManager:
#     def __init__(self,client: AsyncIOMotorClient, db_name: str):
#         self.client = client
#         self.db = client[db_name]
        
#     async def find_one(self, collection:str, filter_dict:Dict[str,Any]):
#         try:
#             result = await self.db[collection].find_one(filter_dict)
#             return result
#         except Exception as e:
#             logger.error(f'Error finding data in {collection}: {e}')
#             raise 

#     async def find_many(self, collection:str, filter_dict: Dict[str,Any] = None, skip: int = 0, limit:int = 0, sort:List = None):
#         try:
#             cursor = self.db[collection].find(filter_dict or {})
#             if sort:
#                 cursor = cursor.sort(sort)
#             if skip:
#                 cursor = cursor.skip(skip)
#             if limit:
#                 cursor = cursor.limit(limit)
            
#             result = await cursor.to_list(length = None)
#             return result
#         except Exception as e:
#             raise e

#     async def insert_one(self, collection:str, document: Dict[str,Any]):
#         try:
#             result = await self.db[collection].insert_one(document)
#             return str(result.inserted_id)
#         except Exception as e:
#             raise e
    
#     async def update_one(self, collection: str, filter_dict: Dict[str, Any], update_dict: Dict[str, Any]):
#         try:
#             if any(key.startswith('$') for key in update_dict.keys()):
#                 result = await self.db[collection].update_one(filter_dict, update_dict)
#             else:
#                 result = await self.db[collection].update_one(filter_dict, {"$set": update_dict})
#             return result
#         except Exception as e:
#             raise e
    
#     async def update_many(self, collection: str, filter_dict: Dict[str, Any], update_dict: Dict[str, Any]):
#         try:
#             if any(key.startswith('$') for key in update_dict.keys()):
#                 result = await self.db[collection].update_many(filter_dict, update_dict)
#             else:
#                 result = await self.db[collection].update_many(filter_dict, {"$set": update_dict})
#             return result.modified_count > 0
#         except Exception as e:
#             raise e

#     async def count_documents(self,collection:str,filter_dict:Dict[str,Any] = None):
#         try:
#             return await self.db[collection].count_documents(filter_dict or {})
#         except Exception as e:
#             raise e
    
#     async def delete_one(self, collection:str, filter_dict:Dict[str,Any]):
#         try:
#             result = await self.db[collection].delete_one(filter_dict)
#             return result.deleted_count
#         except Exception as e:
#             raise e

#     async def delete_many(self, collection_name: str, filter_dict: dict):
#         """Delete multiple documents matching filter"""
#         try:
#             collection = self.db[collection_name]
#             result = await collection.delete_many(filter_dict)
#             logger.info(f"Deleted {result.deleted_count} documents from {collection_name}")
#             return result.deleted_count
#         except Exception as e:
#             logger.error(f"Error deleting many in {collection_name}: {e}")
#             raise

#     async def aggregate(self,collection:str, pipeline:List[Dict[str,Any]]):
#         try:
#             cursor = self.db[collection].aggregate(pipeline)
#             return await cursor.to_list(length=None)
#         except Exception as e:
#             logger.error(f"Error performing aggregation: {e}")
#             raise

# def get_database():
#     client = get_connection()
#     return DatabaseManager(client,os.getenv('DB_NAME'))

from typing import Dict, Any, List, Optional
from db.db_connection import get_connection
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import os
import logging

load_dotenv()

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, client: AsyncIOMotorClient, db_name: str):
        self.client = client
        self.db = client[db_name]
        
    async def find_one(
        self, 
        collection: str, 
        filter_dict: Dict[str, Any],
        projection: Optional[Dict[str, Any]] = None
    ):
        """
        Find one document with optional field projection
        
        Args:
            collection: Collection name
            filter_dict: Query filter
            projection: Fields to include/exclude (e.g., {"_id": 0, "name": 1})
        """
        try:
            if projection:
                result = await self.db[collection].find_one(filter_dict, projection)
            else:
                result = await self.db[collection].find_one(filter_dict)
            return result
        except Exception as e:
            logger.error(f'Error finding data in {collection}: {e}')
            raise 

    async def find_many(
        self, 
        collection: str, 
        filter_dict: Dict[str, Any] = None, 
        skip: int = 0, 
        limit: int = 0, 
        sort: List = None,
        projection: Optional[Dict[str, Any]] = None
    ):
        """
        Find multiple documents with optional field projection
        
        Args:
            collection: Collection name
            filter_dict: Query filter
            skip: Number of documents to skip
            limit: Maximum number of documents to return
            sort: Sort order [(field, direction), ...]
            projection: Fields to include/exclude
        """
        try:
            # Apply projection if provided
            if projection:
                cursor = self.db[collection].find(filter_dict or {}, projection)
            else:
                cursor = self.db[collection].find(filter_dict or {})
            
            if sort:
                cursor = cursor.sort(sort)
            if skip:
                cursor = cursor.skip(skip)
            if limit:
                cursor = cursor.limit(limit)
            
            result = await cursor.to_list(length=None)
            return result
        except Exception as e:
            logger.error(f'Error finding many in {collection}: {e}')
            raise e

    async def insert_one(self, collection: str, document: Dict[str, Any]):
        """Insert a single document"""
        try:
            result = await self.db[collection].insert_one(document)
            return str(result.inserted_id)
        except Exception as e:
            logger.error(f'Error inserting into {collection}: {e}')
            raise e
    
    async def update_one(
        self, 
        collection: str, 
        filter_dict: Dict[str, Any], 
        update_dict: Dict[str, Any]
    ):
        """Update a single document"""
        try:
            # Check if update_dict already has operators like $set, $push, etc.
            if any(key.startswith('$') for key in update_dict.keys()):
                result = await self.db[collection].update_one(filter_dict, update_dict)
            else:
                result = await self.db[collection].update_one(filter_dict, {"$set": update_dict})
            return result
        except Exception as e:
            logger.error(f'Error updating in {collection}: {e}')
            raise e
    
    async def update_many(
        self, 
        collection: str, 
        filter_dict: Dict[str, Any], 
        update_dict: Dict[str, Any]
    ):
        """Update multiple documents"""
        try:
            if any(key.startswith('$') for key in update_dict.keys()):
                result = await self.db[collection].update_many(filter_dict, update_dict)
            else:
                result = await self.db[collection].update_many(filter_dict, {"$set": update_dict})
            return result.modified_count > 0
        except Exception as e:
            logger.error(f'Error updating many in {collection}: {e}')
            raise e

    async def count_documents(self, collection: str, filter_dict: Dict[str, Any] = None):
        """Count documents matching filter"""
        try:
            return await self.db[collection].count_documents(filter_dict or {})
        except Exception as e:
            logger.error(f'Error counting in {collection}: {e}')
            raise e
    
    async def delete_one(self, collection: str, filter_dict: Dict[str, Any]):
        """Delete a single document"""
        try:
            result = await self.db[collection].delete_one(filter_dict)
            return result.deleted_count
        except Exception as e:
            logger.error(f'Error deleting from {collection}: {e}')
            raise e

    async def delete_many(self, collection_name: str, filter_dict: dict):
        """Delete multiple documents matching filter"""
        try:
            collection = self.db[collection_name]
            result = await collection.delete_many(filter_dict)
            logger.info(f"Deleted {result.deleted_count} documents from {collection_name}")
            return result.deleted_count
        except Exception as e:
            logger.error(f"Error deleting many in {collection_name}: {e}")
            raise

    async def aggregate(self, collection: str, pipeline: List[Dict[str, Any]]):
        """Execute an aggregation pipeline"""
        try:
            cursor = self.db[collection].aggregate(pipeline)
            return await cursor.to_list(length=None)
        except Exception as e:
            logger.error(f"Error performing aggregation on {collection}: {e}")
            raise

def get_database():
    """Get database instance"""
    client = get_connection()
    return DatabaseManager(client, os.getenv('DB_NAME'))
