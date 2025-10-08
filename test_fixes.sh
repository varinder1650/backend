#!/bin/bash

echo "Applying test fixes..."

# Fix 1: Update support ticket tests to use correct enum values
sed -i '' 's/"category": "order_issue"/"category": "order_inquiry"/' test/test_address_support.py
sed -i '' 's/"category": "general"/"category": "other"/' test/test_address_support.py

# Fix 2: Make ticket messages longer (min 10 chars)
sed -i '' 's/"message": "Test message"/"message": "This is a test message for support"/' test/test_address_support.py
sed -i '' 's/"message": "Initial message"/"message": "This is the initial message for this ticket"/' test/test_address_support.py
sed -i '' 's/"message": "Initial"/"message": "This is the initial ticket message"/' test/test_address_support.py
sed -i '' 's/"message": "Message"/"message": "This is a test support message"/' test/test_address_support.py

# Fix 3: Update support ticket subjects (min 5 chars)
sed -i '' 's/"subject": "Test ticket"/"subject": "Test support ticket"/' test/test_address_support.py

echo "✅ Test fixes applied"
