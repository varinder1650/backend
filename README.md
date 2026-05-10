# Smart Bag Backend

FastAPI backend for Smart Bag e-commerce platform.

## Tech Stack

- **Framework**: FastAPI
- **Database**: PostgreSQL with asyncpg
- **Cache**: Redis
- **Auth**: JWT with refresh tokens
- **Real-time**: WebSocket

## Project Structure

```
backend/
├── app/
│   ├── routes/          # API endpoints
│   ├── services/        # Business logic
│   ├── middleware/      # Request/response middleware
│   ├── cache/           # Caching utilities
│   ├── config/          # Configuration
│   ├── tasks/           # Background tasks
│   └── utils/           # Helpers
├── db/                  # Database schemas
├── schema/              # SQLAlchemy models
├── test/                # Tests
├── main.py              # Entry point
└── requirements.txt     # Dependencies
```

## API Routes

| Route | Description |
|-------|-------------|
| `/auth` | Authentication, login, register, OTP |
| `/products` | Product catalog, search |
| `/cart` | Shopping cart |
| `/orders` | Order management |
| `/payment` | Payment processing |
| `/address` | User addresses |
| `/delivery` | Delivery tracking |
| `/notifications` | Push notifications |
| `/coupons` | Discount codes |
| `/brands` | Brand listing |
| `/categories` | Product categories |
| `/marketing` | Banners, promotions |
| `/support` | Customer support |
| `/chat-ws` | WebSocket chat |
| `/porter` | Delivery partner portal |

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server
python main.py
```

## Environment

Copy `.env.example` to `.env` and configure:
- Database connection
- Redis cache
- JWT secrets
- Email/SMTP settings
