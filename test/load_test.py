# tests/load_test.py
"""
Load testing for SmartBag API
Run: locust -f tests/load_test.py --host=http://localhost:8000
"""
from locust import HttpUser, task, between, events
import random
import json
import logging

logger = logging.getLogger(__name__)

class SmartBagUser(HttpUser):
    """
    Simulates a typical SmartBag user behavior
    """
    wait_time = between(1, 3)  # Wait 1-3 seconds between requests
    
    def on_start(self):
        """
        Called when a simulated user starts
        Login and get auth token
        """
        # Register or login
        self.email = f"loadtest_{random.randint(1000, 9999)}@example.com"
        self.password = "testpassword123"
        self.token = None
        
        # Try to login (will fail for new users)
        response = self.client.post("/api/auth/login", json={
            "email": self.email,
            "password": self.password
        }, catch_response=True)
        
        if response.status_code == 401:
            # Register new user
            register_response = self.client.post("/api/auth/register", json={
                "name": f"Load Test User {random.randint(1000, 9999)}",
                "email": self.email,
                "password": self.password
            })
            
            if register_response.status_code == 200:
                logger.info(f"✅ Registered user: {self.email}")
        
        elif response.status_code == 200:
            data = response.json()
            self.token = data.get("access_token")
            logger.info(f"✅ Logged in user: {self.email}")
    
    def get_headers(self):
        """Get authorization headers"""
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}
    
    @task(10)  # Weight: 10 (most common action)
    def browse_products(self):
        """Browse products - most common user action"""
        page = random.randint(1, 3)
        
        with self.client.get(
            f"/api/products/?page={page}&limit=20",
            name="/api/products (browse)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Failed: {response.status_code}")
    
    @task(5)
    def search_products(self):
        """Search for products"""
        search_terms = ["snacks", "drinks", "chips", "cola", "chocolate"]
        search = random.choice(search_terms)
        
        with self.client.get(
            f"/api/products/?search={search}",
            name="/api/products (search)",
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Search failed: {response.status_code}")
    
    @task(3)
    def view_categories(self):
        """View categories"""
        self.client.get("/api/categories/", name="/api/categories")
    
    @task(3)
    def view_brands(self):
        """View brands"""
        self.client.get("/api/brands/", name="/api/brands")
    
    @task(5)
    def view_product_detail(self):
        """View single product detail"""
        # First get products to get a valid ID
        response = self.client.get("/api/products/?limit=20")
        
        if response.status_code == 200:
            products = response.json().get("products", [])
            if products:
                product = random.choice(products)
                product_id = product.get("id")
                
                self.client.get(
                    f"/api/products/{product_id}",
                    name="/api/products/:id",
                    headers=self.get_headers()
                )
    
    @task(4)
    def view_cart(self):
        """View shopping cart"""
        if self.token:
            self.client.get(
                "/api/cart/",
                name="/api/cart (view)",
                headers=self.get_headers()
            )
    
    @task(2)
    def add_to_cart(self):
        """Add item to cart"""
        if not self.token:
            return
        
        # Get a product first
        response = self.client.get("/api/products/?limit=20")
        
        if response.status_code == 200:
            products = response.json().get("products", [])
            if products:
                product = random.choice(products)
                product_id = product.get("id")
                
                with self.client.post(
                    "/api/cart/add",
                    json={
                        "productId": product_id,
                        "quantity": random.randint(1, 3)
                    },
                    headers=self.get_headers(),
                    name="/api/cart/add",
                    catch_response=True
                ) as cart_response:
                    if cart_response.status_code == 200:
                        cart_response.success()
                    else:
                        cart_response.failure(f"Add to cart failed: {cart_response.status_code}")
    
    @task(1)
    def view_orders(self):
        """View order history"""
        if self.token:
            self.client.get(
                "/api/orders/my?page=1&limit=10",
                name="/api/orders/my",
                headers=self.get_headers()
            )
    
    @task(2)
    def check_active_order(self):
        """Check active order status"""
        if self.token:
            self.client.get(
                "/api/orders/active",
                name="/api/orders/active",
                headers=self.get_headers()
            )
    
    @task(1)
    def view_shop_status(self):
        """Check if shop is open"""
        self.client.get("/api/shop/status", name="/api/shop/status")


class AdminUser(HttpUser):
    """
    Simulates admin user behavior
    Less frequent but heavier operations
    """
    wait_time = between(5, 10)
    
    def on_start(self):
        """Login as admin"""
        # You'll need to create an admin user first
        self.token = None
        
        response = self.client.post("/api/auth/login", json={
            "email": "admin@smartbag.com",  # Change to your admin email
            "password": "adminpassword"     # Change to your admin password
        })
        
        if response.status_code == 200:
            self.token = response.json().get("access_token")
    
    @task
    def view_metrics(self):
        """View application metrics"""
        if self.token:
            self.client.get(
                "/api/metrics/",
                headers={"Authorization": f"Bearer {self.token}"},
                name="/api/metrics (admin)"
            )


class DeliveryPartnerUser(HttpUser):
    """
    Simulates delivery partner behavior
    """
    wait_time = between(3, 8)
    
    def on_start(self):
        """Login as delivery partner"""
        self.token = None
        
        # Login (you'll need a delivery partner account)
        response = self.client.post("/api/auth/login", json={
            "email": "delivery@smartbag.com",
            "password": "deliverypassword"
        })
        
        if response.status_code == 200:
            self.token = response.json().get("access_token")
    
    @task(5)
    def view_available_orders(self):
        """Check available orders"""
        if self.token:
            self.client.get(
                "/api/delivery/available",
                headers={"Authorization": f"Bearer {self.token}"},
                name="/api/delivery/available"
            )
    
    @task(3)
    def view_assigned_orders(self):
        """Check assigned orders"""
        if self.token:
            self.client.get(
                "/api/delivery/assigned",
                headers={"Authorization": f"Bearer {self.token}"},
                name="/api/delivery/assigned"
            )


# Event listeners for detailed reporting
@events.request.add_listener
def on_request(request_type, name, response_time, response_length, exception, **kwargs):
    """Log slow requests"""
    if response_time > 2000:  # Slower than 2 seconds
        logger.warning(f"🐌 SLOW: {name} took {response_time}ms")

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Called when test starts"""
    logger.info("🚀 Load test starting...")

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Called when test stops"""
    logger.info("✅ Load test completed!")