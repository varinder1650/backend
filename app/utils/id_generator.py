import time
import random
import string
from datetime import datetime
from typing import Optional
import hashlib
from app.cache.redis_manager import get_redis
import logging

logger = logging.getLogger(__name__)

class IDGenerator:
    """
    Custom ID Generator for SmartBag entities
    
    ID Format Examples:
    - Orders: ORD-20250102-ABC123 (ORD-YYYYMMDD-RANDOM)
    - Products: PRD-ELECT-001234 (PRD-CATEGORY-SEQUENCE)
    - Users: USR-20250102-XYZ789
    - Delivery Partners: DLP-20250102-PQR456
    - Support Tickets: TKT-20250102-001
    """
    
    # Entity prefixes
    PREFIXES = {
        'order': 'ORD',
        'product': 'BNL',
        'user': 'USR',
        'delivery_partner': 'DLP',
        'support_ticket': 'TKT',
        'address': 'ADDR',
        'cart': 'CRT',
        'coupon': 'CPN',
        'category': 'CAT',
        'brand': 'BRD',
        'review': 'REV',
        'payment': 'PAY',
        'refund': 'RFD',
        'invoice': 'INV'
    }
    
    # Category codes for products
    CATEGORY_CODES = {
        'gifts': 'GIFT',
        'fashion': 'FASH',
        'home': 'HOME',
        'groceries': 'GROC'
    }
    
    def __init__(self):
        self.redis = get_redis()
    
    def _generate_date_component(self) -> str:
        """Generate date component YYYYMMDD"""
        return datetime.utcnow().strftime('%Y%m%d')
    
    def _generate_random_suffix(self, length: int = 6) -> str:
        """Generate random alphanumeric suffix"""
        chars = string.ascii_uppercase + string.digits
        # Exclude confusing characters
        chars = chars.replace('O', '').replace('0', '').replace('I', '').replace('1', '')
        return ''.join(random.choices(chars, k=length))
    
    async def _get_next_sequence(self, entity_type: str, date: str) -> int:
        """Get next sequence number for entity type and date"""
        key = f"sequence:{entity_type}:{date}"
        
        try:
            sequence = await self.redis.increment(key, 1)
            # Set expiry to 2 days to clean up old sequences
            await self.redis.redis.expire(key, 172800)
            return sequence
        except Exception as e:
            logger.error(f"Error getting sequence for {entity_type}: {e}")
            # Fallback to timestamp-based sequence
            return int(time.time() * 1000) % 100000
    
    async def generate_order_id(self, user_id: str = None) -> str:
        """
        Generate order ID: ORD-20250102-ABC123
        
        Format: PREFIX-DATE-RANDOM
        Example: ORD-20250102-A7C9X2
        """
        prefix = self.PREFIXES['order']
        date_part = self._generate_date_component()
        random_part = self._generate_random_suffix(6)
        
        order_id = f"{prefix}{date_part}{random_part}"
        
        # Ensure uniqueness
        retry_count = 0
        while await self._id_exists('orders', order_id) and retry_count < 5:
            random_part = self._generate_random_suffix(6)
            order_id = f"{prefix}{date_part}{random_part}"
            retry_count += 1
        
        return order_id
    
    async def generate_product_id(self, category_name: str = None) -> str:
        """
        Generate product ID: PRD-ELECT-001234
        
        Format: PREFIX-CATEGORY-SEQUENCE
        Example: PRD-ELECT-001234
        """
        prefix = self.PREFIXES['product']
        
        # Get category code
        if category_name:
            category_code = self.CATEGORY_CODES.get(
                category_name.lower(), 
                category_name[:4].upper()
            )
        else:
            category_code = 'MISC'
        
        # Get sequence number
        date_part = self._generate_date_component()
        sequence = await self._get_next_sequence('product', date_part)
        sequence_str = str(sequence).zfill(6)
        
        product_id = f"{prefix}{category_code}{sequence_str}"
        
        return product_id
    
    async def generate_user_id(self, email: str = None, role:str = 'customer') -> str:
        """
        Generate user ID: USR-20250102-XYZ789
        
        Format: PREFIX-DATE-HASH
        Example: USR-20250102-A7C9X2
        """
        prefix = self.PREFIXES['user']
        date_part = self._generate_date_component()
        if role == 'customer':
            role_part = "CUST"
        else:
            role_part = "DEL"
        # Use email hash for consistency if provided
        if email:
            hash_input = f"{email}{time.time()}"
            hash_suffix = hashlib.md5(hash_input.encode()).hexdigest()[:6].upper()
        else:
            hash_suffix = self._generate_random_suffix(6)
        
        user_id = f"{role_part}{date_part}{hash_suffix}"
        
        # Ensure uniqueness
        retry_count = 0
        while await self._id_exists('users', user_id) and retry_count < 5:
            hash_suffix = self._generate_random_suffix(6)
            user_id = f"{prefix}{date_part}{hash_suffix}"
            retry_count += 1
        
        return user_id
    
    async def generate_delivery_partner_id(self, name: str = None) -> str:
        """
        Generate delivery partner ID: DLP-20250102-PQR456
        
        Format: PREFIX-DATE-RANDOM
        Example: DLP-20250102-P7Q9R2
        """
        prefix = self.PREFIXES['delivery_partner']
        date_part = self._generate_date_component()
        random_part = self._generate_random_suffix(6)
        
        partner_id = f"{prefix}{date_part}{random_part}"
        
        # Ensure uniqueness
        retry_count = 0
        while await self._id_exists('users', partner_id) and retry_count < 5:
            random_part = self._generate_random_suffix(6)
            partner_id = f"{prefix}-{date_part}-{random_part}"
            retry_count += 1
        
        return partner_id
    
    async def generate_support_ticket_id(self) -> str:
        """
        Generate support ticket ID: TKT-20250102-0001
        
        Format: PREFIX-DATE-SEQUENCE
        Example: TKT-20250102-0001
        """
        prefix = self.PREFIXES['support_ticket']
        date_part = self._generate_date_component()
        
        # Get daily sequence
        sequence = await self._get_next_sequence('support_ticket', date_part)
        sequence_str = str(sequence).zfill(4)
        
        ticket_id = f"{prefix}{date_part}{sequence_str}"
        
        return ticket_id
    
    async def generate_payment_id(self, order_id: str = None) -> str:
        """
        Generate payment ID: PAY-ORD20250102ABC123-T001
        
        Format: PREFIX-ORDERREF-TRANSACTION
        Example: PAY-ORD20250102ABC123-T001
        """
        prefix = self.PREFIXES['payment']
        
        if order_id:
            # Remove hyphens from order ID for compactness
            order_ref = order_id.replace('-', '')
        else:
            order_ref = self._generate_date_component() + self._generate_random_suffix(6)
        
        # Get transaction sequence
        sequence = await self._get_next_sequence('payment', order_ref)
        transaction_num = f"T{str(sequence).zfill(3)}"
        
        payment_id = f"{prefix}{order_ref}{transaction_num}"
        
        return payment_id
    
    async def generate_coupon_code(self, prefix: str = None, length: int = 8) -> str:
        """
        Generate coupon code: WINTER2025-ABC123XY
        
        Format: CUSTOMPREFIX-RANDOM or CPN-RANDOM
        Example: NEWYEAR25-A7C9X2Y4
        """
        if prefix:
            code_prefix = prefix.upper()
        else:
            code_prefix = self.PREFIXES['coupon']
        
        random_part = self._generate_random_suffix(length)
        coupon_code = f"{code_prefix}{random_part}"
        
        # Ensure uniqueness
        retry_count = 0
        while await self._id_exists('discount_coupons', coupon_code) and retry_count < 5:
            random_part = self._generate_random_suffix(length)
            coupon_code = f"{code_prefix}{random_part}"
            retry_count += 1
        
        return coupon_code
    
    async def generate_invoice_id(self, order_id: str) -> str:
        """
        Generate invoice ID: INV-ORD20250102ABC123
        
        Format: PREFIX-ORDERREF
        Example: INV-ORD20250102ABC123
        """
        prefix = self.PREFIXES['invoice']
        order_ref = order_id.replace('-', '')
        
        invoice_id = f"{prefix}{order_ref}"
        
        return invoice_id
    
    async def generate_category_id(self, category_name: str) -> str:
        """
        Generate category ID: CAT-ELECTRONICS
        
        Format: PREFIX-NAME
        Example: CAT-ELECTRONICS
        """
        prefix = self.PREFIXES['category']
        name_part = category_name.upper().replace(' ', '')[:12]
        
        category_id = f"{prefix}{name_part}"
        
        return category_id
    
    async def generate_brand_id(self, brand_name: str) -> str:
        """
        Generate brand ID: BRD-SAMSUNG
        
        Format: PREFIX-NAME
        Example: BRD-SAMSUNG
        """
        prefix = self.PREFIXES['brand']
        name_part = brand_name.upper().replace(' ', '')[:10]
        
        brand_id = f"{prefix}{name_part}"
        
        return brand_id
    
    async def _id_exists(self, collection: str, id_value: str) -> bool:
        """Check if ID already exists in database"""
        try:
            # Check Redis cache first for recent IDs
            cache_key = f"id_check:{collection}:{id_value}"
            cached = await self.redis.get(cache_key)
            
            if cached:
                return True
            
            # Check database (you'll need to implement this based on your DB manager)
            from db.db_manager import get_database
            db = get_database()
            
            # Try with both _id and custom id field
            existing = await db.find_one(collection, {
                "$or": [
                    {"_id": id_value},
                    {"id": id_value},
                    {"custom_id": id_value}
                ]
            })
            
            if existing:
                # Cache the existence check
                await self.redis.set(cache_key, True, 3600)
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking ID existence: {e}")
            return False
    
    async def validate_id_format(self, id_value: str, entity_type: str) -> bool:
        """Validate ID format for given entity type"""
        if not id_value not in id_value:
            return False
        
        parts = id_value.split('-')
        expected_prefix = self.PREFIXES.get(entity_type)
        
        if not expected_prefix or parts[0] != expected_prefix:
            return False
        
        # Additional format validation based on entity type
        if entity_type == 'order':
            return len(parts) == 3 and len(parts[1]) == 8 and len(parts[2]) == 6
        elif entity_type == 'product':
            return len(parts) == 3 and len(parts[2]) == 6
        elif entity_type == 'support_ticket':
            return len(parts) == 3 and len(parts[2]) == 4
        
        return True
    
    def parse_order_id(self, order_id: str) -> dict:
        """Extract information from order ID"""
        try:
            parts = order_id.split('-')
            
            if len(parts) != 3 or parts[0] != self.PREFIXES['order']:
                return None
            
            date_str = parts[1]
            year = date_str[:4]
            month = date_str[4:6]
            day = date_str[6:8]
            
            return {
                'prefix': parts[0],
                'date': f"{year}-{month}-{day}",
                'random_suffix': parts[2],
                'is_valid': True
            }
        except Exception as e:
            logger.error(f"Error parsing order ID: {e}")
            return None
    
    def get_short_id(self, full_id: str) -> str:
        """Get shortened version of ID for display"""
        try:
            parts = full_id.split('-')
            if len(parts) >= 3:
                return f"{parts[0]}-{parts[-1]}"
            return full_id
        except:
            return full_id

# Global ID generator instance
id_generator = IDGenerator()

def get_id_generator() -> IDGenerator:
    return id_generator


# Migration helper functions
async def migrate_existing_ids(collection_name: str, entity_type: str):
    """
    Helper function to migrate existing ObjectId-based documents to custom IDs
    
    Usage:
        await migrate_existing_ids('orders', 'order')
        await migrate_existing_ids('products', 'product')
    """
    from db.db_manager import get_database
    
    db = get_database()
    generator = get_id_generator()
    
    logger.info(f"Starting ID migration for {collection_name}...")
    
    # Get all documents
    documents = await db.find_many(collection_name, {})
    
    migrated_count = 0
    error_count = 0
    
    for doc in documents:
        try:
            # Skip if already has custom_id
            if 'custom_id' in doc:
                continue
            
            # Generate new custom ID
            if entity_type == 'order':
                custom_id = await generator.generate_order_id()
            elif entity_type == 'product':
                category_name = doc.get('category', {}).get('name', 'misc')
                custom_id = await generator.generate_product_id(category_name)
            elif entity_type == 'user':
                custom_id = await generator.generate_user_id(doc.get('email'))
            elif entity_type == 'support_ticket':
                custom_id = await generator.generate_support_ticket_id()
            else:
                logger.warning(f"Unknown entity type: {entity_type}")
                continue
            
            # Update document with custom_id
            await db.update_one(
                collection_name,
                {"_id": doc["_id"]},
                {
                    "$set": {
                        "custom_id": custom_id,
                        "legacy_id": str(doc["_id"]),
                        "migrated_at": datetime.utcnow()
                    }
                }
            )
            
            migrated_count += 1
            
            if migrated_count % 100 == 0:
                logger.info(f"Migrated {migrated_count} documents...")
        
        except Exception as e:
            logger.error(f"Error migrating document {doc.get('_id')}: {e}")
            error_count += 1
    
    logger.info(f"Migration complete: {migrated_count} migrated, {error_count} errors")
    
    return {
        "collection": collection_name,
        "migrated": migrated_count,
        "errors": error_count
    }


# Example usage in your routes
"""
# In your auth.py for user registration:

from app.utils.id_generator import get_id_generator

@router.post("/register")
async def register_user(user_data: UserCreate, db: DatabaseManager = Depends(get_database)):
    try:
        id_generator = get_id_generator()
        
        # Generate custom user ID
        custom_user_id = await id_generator.generate_user_id(user_data.email)
        
        user_doc = {
            "custom_id": custom_user_id,  # Primary custom ID
            "name": user_data.name,
            "email": user_data.email,
            # ... rest of user data
        }
        
        # Still use MongoDB ObjectId as _id for database operations
        user_id = await db.insert_one("users", user_doc)
        
        # Use custom_id for all API responses and references
        return {
            "user_id": custom_user_id,  # Return custom ID to client
            "message": "User registered successfully"
        }
        
    except Exception as e:
        logger.error(f"Registration error: {e}")
        raise


# In your orders.py:

@router.post("/")
async def create_order(order_data: dict, current_user: UserinDB = Depends(current_active_user)):
    try:
        id_generator = get_id_generator()
        
        # Generate custom order ID
        custom_order_id = await id_generator.generate_order_id(current_user.id)
        
        order_doc = {
            "custom_id": custom_order_id,
            "user_custom_id": current_user.custom_id,  # Reference by custom ID
            "items": order_data['items'],
            # ... rest of order data
        }
        
        await db.insert_one("orders", order_doc)
        
        # Generate related IDs
        payment_id = await id_generator.generate_payment_id(custom_order_id)
        invoice_id = await id_generator.generate_invoice_id(custom_order_id)
        
        return {
            "order_id": custom_order_id,
            "payment_id": payment_id,
            "invoice_id": invoice_id,
            "message": "Order created successfully"
        }
        
    except Exception as e:
        logger.error(f"Order creation error: {e}")
        raise
"""