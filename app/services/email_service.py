# app/services/email_service.py
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import logging

logger = logging.getLogger(__name__)

class EmailService:
    def __init__(self):
        self.smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', 587))
        self.smtp_user = os.getenv('SMTP_USER')  # e.g., noreply@smartbag.com
        self.smtp_password = os.getenv('SMTP_PASSWORD')  # App password
        self.from_email = os.getenv('FROM_EMAIL', self.smtp_user)
    
    async def send_order_confirmation(self, to_email: str, order_data: dict):
        """Send order confirmation email"""
        try:
            subject = f"Order Confirmation - {order_data['order_id']}"
            
            html_body = f"""
            <html>
                <body>
                    <h2>Thank you for your order!</h2>
                    <p>Hi {order_data['customer_name']},</p>
                    <p>Your order <strong>{order_data['order_id']}</strong> has been confirmed.</p>
                    <h3>Order Details:</h3>
                    <ul>
                        {''.join([f"<li>{item['name']} x {item['quantity']}</li>" for item in order_data['items']])}
                    </ul>
                    <p>Total: ${order_data['total_amount']}</p>
                    <p>Estimated delivery: {order_data['estimated_delivery']}</p>
                </body>
            </html>
            """
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.from_email
            msg['To'] = to_email
            
            html_part = MIMEText(html_body, 'html')
            msg.attach(html_part)
            
            # Send email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            
            logger.info(f"Order confirmation sent to {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"Email send error: {e}")
            return False

email_service = EmailService()