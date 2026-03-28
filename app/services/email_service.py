import smtplib
import asyncio
import html
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import logging

logger = logging.getLogger(__name__)


def _escape(value) -> str:
    """HTML-escape user-supplied data to prevent injection."""
    return html.escape(str(value))


class EmailService:
    def __init__(self):
        self.smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', 587))
        self.smtp_user = os.getenv('SMTP_USER')
        self.smtp_password = os.getenv('SMTP_PASSWORD')
        self.from_email = os.getenv('FROM_EMAIL', self.smtp_user)
        self.from_name = os.getenv('FROM_NAME', 'SmartBag')

    async def send_email_verification_otp(self, to_email: str, name: str, otp: str):
        """Send email verification OTP"""
        try:
            subject = "Verify Your SmartBag Account"
            safe_name = _escape(name)
            safe_otp = _escape(otp)

            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background-color: #4CAF50; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
                    .content {{ background-color: #f9f9f9; padding: 30px; border-radius: 0 0 8px 8px; }}
                    .otp-box {{ background-color: white; padding: 20px; border-radius: 8px; margin: 20px 0; text-align: center; }}
                    .otp-code {{ font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #4CAF50; }}
                    .footer {{ text-align: center; margin-top: 30px; color: #777; font-size: 12px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>Welcome to SmartBag!</h1>
                    </div>
                    <div class="content">
                        <p>Hi {safe_name},</p>
                        <p>Thank you for signing up! Please verify your email address using the code below:</p>

                        <div class="otp-box">
                            <p style="margin: 0; font-size: 14px; color: #666;">Your Verification Code</p>
                            <div class="otp-code">{safe_otp}</div>
                            <p style="margin: 10px 0 0 0; font-size: 12px; color: #999;">This code expires in 10 minutes</p>
                        </div>

                        <p>If you didn't create an account, please ignore this email.</p>
                    </div>
                    <div class="footer">
                        <p>&copy; 2025 SmartBag. All rights reserved.</p>
                    </div>
                </div>
            </body>
            </html>
            """

            return await self._send_email(to_email, subject, html_body)
        except Exception as e:
            logger.error(f"Error sending verification OTP: {e}")
            return False

    async def send_password_reset_otp(self, to_email: str, name: str, otp: str):
        """Send password reset OTP"""
        try:
            subject = "Reset Your SmartBag Password"
            safe_name = _escape(name)
            safe_otp = _escape(otp)

            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background-color: #FF9500; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
                    .content {{ background-color: #f9f9f9; padding: 30px; border-radius: 0 0 8px 8px; }}
                    .otp-box {{ background-color: white; padding: 20px; border-radius: 8px; margin: 20px 0; text-align: center; }}
                    .otp-code {{ font-size: 32px; font-weight: bold; letter-spacing: 8px; color: #FF9500; }}
                    .footer {{ text-align: center; margin-top: 30px; color: #777; font-size: 12px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>Password Reset Request</h1>
                    </div>
                    <div class="content">
                        <p>Hi {safe_name},</p>
                        <p>We received a request to reset your password. Use the code below to reset it:</p>

                        <div class="otp-box">
                            <p style="margin: 0; font-size: 14px; color: #666;">Your Reset Code</p>
                            <div class="otp-code">{safe_otp}</div>
                            <p style="margin: 10px 0 0 0; font-size: 12px; color: #999;">This code expires in 10 minutes</p>
                        </div>

                        <p><strong>If you didn't request this, please ignore this email.</strong></p>
                    </div>
                    <div class="footer">
                        <p>&copy; 2025 SmartBag. All rights reserved.</p>
                    </div>
                </div>
            </body>
            </html>
            """

            return await self._send_email(to_email, subject, html_body)
        except Exception as e:
            logger.error(f"Error sending password reset OTP: {e}")
            return False

    async def send_order_confirmation(self, to_email: str, order_data: dict):
        """Send order confirmation email"""
        try:
            safe_order_id = _escape(order_data['order_id'])
            safe_customer = _escape(order_data['customer_name'])
            safe_address = _escape(order_data.get('delivery_address', 'N/A'))
            safe_delivery = _escape(order_data['estimated_delivery'])
            safe_total = _escape(f"{order_data['total_amount']:.2f}")

            subject = f"Order Confirmed - #{safe_order_id}"

            items_html = ''.join([f'''
                            <div class="item">
                                <span>{_escape(item['name'])} x{_escape(item['quantity'])}</span>
                                <span>&#8377;{_escape(f"{(item['price'] * item['quantity']):.2f}")}</span>
                            </div>
                            ''' for item in order_data['items']])

            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background-color: #4CAF50; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
                    .content {{ background-color: #f9f9f9; padding: 30px; border-radius: 0 0 8px 8px; }}
                    .order-details {{ background-color: white; padding: 20px; border-radius: 8px; margin: 20px 0; }}
                    .item {{ display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #eee; }}
                    .total {{ font-size: 18px; font-weight: bold; color: #4CAF50; margin-top: 15px; padding-top: 15px; border-top: 2px solid #4CAF50; }}
                    .footer {{ text-align: center; margin-top: 30px; color: #777; font-size: 12px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>Thank You for Your Order!</h1>
                        <p>Order #{safe_order_id}</p>
                    </div>
                    <div class="content">
                        <p>Hi {safe_customer},</p>
                        <p>We've received your order and it's being prepared.</p>

                        <div class="order-details">
                            <h3>Order Details</h3>
                            <p><strong>Delivery Address:</strong> {safe_address}</p>
                            <p><strong>Estimated Delivery:</strong> {safe_delivery}</p>

                            <h4 style="margin-top: 20px;">Items:</h4>
                            {items_html}

                            <div class="total">
                                <div style="display: flex; justify-content: space-between;">
                                    <span>Total Amount:</span>
                                    <span>&#8377;{safe_total}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="footer">
                        <p>&copy; 2025 SmartBag. All rights reserved.</p>
                    </div>
                </div>
            </body>
            </html>
            """

            return await self._send_email(to_email, subject, html_body)
        except Exception as e:
            logger.error(f"Error sending order confirmation: {e}")
            return False

    async def send_order_status_update(self, to_email: str, order_id: str, status: str, customer_name: str):
        """Send order status update email"""
        try:
            status_messages = {
                'confirmed': {
                    'subject': 'Order Confirmed',
                    'message': 'Your order has been confirmed and is being prepared.'
                },
                'preparing': {
                    'subject': 'Order is Being Prepared',
                    'message': 'The restaurant is now preparing your order.'
                },
                'assigned': {
                    'subject': 'Delivery Partner Assigned',
                    'message': 'A delivery partner has been assigned to your order.'
                },
                'out_for_delivery': {
                    'subject': 'Order On The Way',
                    'message': 'Your order is on the way to you!'
                },
                'delivered': {
                    'subject': 'Order Delivered',
                    'message': 'Your order has been delivered. Enjoy your meal!'
                }
            }

            status_info = status_messages.get(status, {
                'subject': 'Order Update',
                'message': 'Your order status has been updated.'
            })

            safe_customer = _escape(customer_name)
            safe_order_id = _escape(order_id)
            subject = f"{status_info['subject']} - Order #{safe_order_id}"

            html_body = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background-color: #4CAF50; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
                    .content {{ background-color: #f9f9f9; padding: 30px; border-radius: 0 0 8px 8px; }}
                    .status-box {{ background-color: white; padding: 20px; border-radius: 8px; margin: 20px 0; text-align: center; }}
                    .footer {{ text-align: center; margin-top: 30px; color: #777; font-size: 12px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>{status_info['subject']}</h1>
                    </div>
                    <div class="content">
                        <p>Hi {safe_customer},</p>
                        <div class="status-box">
                            <h2>Order #{safe_order_id}</h2>
                            <p style="font-size: 18px; margin: 20px 0;">{status_info['message']}</p>
                        </div>
                        <p>Track your order in real-time through the SmartBag app.</p>
                    </div>
                    <div class="footer">
                        <p>&copy; 2025 SmartBag. All rights reserved.</p>
                    </div>
                </div>
            </body>
            </html>
            """

            return await self._send_email(to_email, subject, html_body)
        except Exception as e:
            logger.error(f"Email send error: {e}")
            return False

    def _send_email_sync(self, to_email: str, subject: str, html_body: str) -> bool:
        """Synchronous email send — runs in a thread pool to avoid blocking."""
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{self.from_name} <{self.from_email}>"
        msg['To'] = to_email

        html_part = MIMEText(html_body, 'html')
        msg.attach(html_part)

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.starttls()
            server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)

        return True

    async def _send_email(self, to_email: str, subject: str, html_body: str) -> bool:
        """Send email without blocking the event loop."""
        try:
            await asyncio.to_thread(self._send_email_sync, to_email, subject, html_body)
            logger.info(f"Email sent successfully to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Email send error: {e}")
            return False


email_service = EmailService()
