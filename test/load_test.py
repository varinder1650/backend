"""
Load testing script for SmartBag API
Install: pip install locust
Run: locust -f tests/load_test.py --host=http://localhost:8000
"""

from locust import HttpUser, task, between
import random
import json

class SmartBagUser(HttpUser):
    wait_time = between(1, 3)
    
    def on_start(self):
        """Login user at start"""
        response = self.client.post("/api/auth/login", json={
            "email": f"test{random.randint(1, 1000)}@example.com",
            "password": "testpassword123"
        })
        
        if response.status_code == 200:
            self.token = response.json().get("access_token")
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.headers = {}
    
    @task(3)
    def browse_products(self):
        """Browse products - most common action"""
        params = {
            "page": random.randint(1, 5),
            "limit": random.randint(10, 20)
        }
        
        # Add random filters sometimes
        if random.random() > 0.7:
            params["search"] = random.choice(["phone", "laptop", "headphones", "watch"])
        
        self.client.get("/api/products", params=params)
    
    @task(2)
    def view_product(self):
        """View product details"""
        # Use a known product ID or generate random one
        product_id = "60f1b2b5c8d4a5001f123456"  # Replace with actual ID
        self.client.get(f"/api/products/{product_id}")
    
    @task(1)
    def view_cart(self):
        """View cart"""
        if self.headers:
            self.client.get("/api/cart", headers=self.headers)
    
    @task(1)
    def get_recommendations(self):
        """Get product recommendations"""
        if self.headers:
            params = {
                "type": random.choice(["trending", "personalized", "collaborative"]),
                "limit": 10
            }
            self.client.get("/api/products/recommendations", 
                           params=params, headers=self.headers)
    
    @task(1)
    def search_products(self):
        """Search products"""
        params = {
            "search": random.choice([
                "maggie", "noodles", "thanda", "cool", "coke", 
                "camera", "speaker", "keyboard", "mouse", "monitor"
            ]),
            "limit": 20
        }
        self.client.get("/api/products", params=params)
    
    def health_check(self):
        """Health check endpoint"""
        self.client.get("/health")