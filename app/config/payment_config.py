import os
from dotenv import load_dotenv

load_dotenv()

class PaymentConfig:
    PHONEPE_MERCHANT_ID = os.getenv("PHONEPE_MERCHANT_ID")
    PHONEPE_SALT_KEY = os.getenv("PHONEPE_SALT_KEY")
    PHONEPE_SALT_INDEX = os.getenv("PHONEPE_SALT_INDEX", "1")
    PHONEPE_API_URL = os.getenv(
        "PHONEPE_API_URL", 
        "https://api.phonepe.com/apis/hermes"
    )
    APP_CALLBACK_URL = os.getenv("APP_CALLBACK_URL")
    API_CALLBACK_URL = os.getenv("API_CALLBACK_URL")

payment_config = PaymentConfig()