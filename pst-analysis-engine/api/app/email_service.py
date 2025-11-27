"""
Email service for authentication and notifications
"""
from __future__ import annotations

import logging
import os
import smtplib
from collections.abc import Mapping
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import jinja2

logger = logging.getLogger(__name__)

# Email configuration
SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USER = os.getenv('SMTP_USER', '')
SMTP_PASS = os.getenv('SMTP_PASS', '')
EMAIL_FROM = os.getenv('EMAIL_FROM', 'VeriCase <noreply@vericase.com>')
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:8010')

# Set up Jinja2 for email templates
templates_path = Path(__file__).parent / "templates" / "emails"
if not templates_path.exists():
    templates_path.mkdir(parents=True, exist_ok=True)

template_loader = jinja2.FileSystemLoader(searchpath=templates_path)
template_env = jinja2.Environment(loader=template_loader, autoescape=True)


class EmailService:
    """Email service for sending transactional emails"""
    
    def __init__(self):
        self.smtp_host = SMTP_HOST
        self.smtp_port = SMTP_PORT
        self.smtp_user = SMTP_USER
        self.smtp_pass = SMTP_PASS
        self.from_email = EMAIL_FROM
        self.frontend_url = FRONTEND_URL
    
    def _get_smtp_connection(self):
        """Get SMTP connection"""
        try:
            server = smtplib.SMTP(self.smtp_host, self.smtp_port)
            _ = server.starttls()
            if self.smtp_user and self.smtp_pass:
                _ = server.login(self.smtp_user, self.smtp_pass)
            return server
        except Exception as e:
            logger.error(f"Failed to connect to SMTP server: {e}")
            raise
    
    def _send_email(self, to_email: str, subject: str, html_content: str, text_content: str | None = None):
        """Send email using SMTP"""
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.from_email
        msg['To'] = to_email
        
        # Add text part
        if text_content:
            text_part = MIMEText(text_content, 'plain')
            msg.attach(text_part)
        
        # Add HTML part
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)
        
        # Send email
        try:
            if self.smtp_user and self.smtp_pass:
                server = self._get_smtp_connection()
                _ = server.send_message(msg)
                _ = server.quit()
                logger.info(f"Email sent successfully to {to_email}")
            else:
                # In development, just log the email
                logger.info(f"DEV MODE - Would send email to {to_email}")
                logger.info(f"Subject: {subject}")
                logger.debug(f"Content: {html_content[:200]}...")
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            # Don't raise exception - email failure shouldn't break the app
    
    def send_verification_email(self, to_email: str, user_name: str, verification_token: str):
        """Send email verification email"""
        verification_link = f"{self.frontend_url}/ui/verify-email.html?token={verification_token}"
        
        # Try to load template, fall back to simple HTML
        try:
            template = template_env.get_template('verification.html')
            html_content = template.render(
                user_name=user_name,
                verification_link=verification_link,
                frontend_url=self.frontend_url
            )
        except Exception as e:
            logger.warning(f"Failed to load email template: {e}")
            # Fallback HTML
            html_content = f"""
            <html>
                <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #667eea;">Welcome to VeriCase!</h2>
                    <p>Hi {user_name},</p>
                    <p>Please verify your email address to complete your registration:</p>
                    <p style="margin: 30px 0;">
                        <a href="{verification_link}" 
                           style="background: #667eea; color: white; padding: 12px 30px; 
                                  text-decoration: none; border-radius: 5px; display: inline-block;">
                            Verify Email
                        </a>
                    </p>
                    <p>Or copy this link: {verification_link}</p>
                    <p>This link will expire in 7 days.</p>
                    <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 30px 0;">
                    <p style="color: #666; font-size: 12px;">
                        If you didn't create an account, please ignore this email.
                    </p>
                </body>
            </html>
            """
        
        text_content = f"""
Welcome to VeriCase!

Hi {user_name},

Please verify your email address by clicking the link below:
{verification_link}

This link will expire in 7 days.

If you didn't create an account, please ignore this email.
"""
        
        self._send_email(to_email, "Verify your VeriCase account", html_content, text_content)
    
    def send_password_reset(self, to_email: str, user_name: str, reset_token: str):
        """Send password reset email"""
        reset_link = f"{self.frontend_url}/ui/password-reset.html?token={reset_token}"
        
        # Try to load template, fall back to simple HTML
        try:
            template = template_env.get_template('password-reset.html')
            html_content = template.render(
                user_name=user_name,
                reset_link=reset_link,
                frontend_url=self.frontend_url
            )
        except Exception:
            # Fallback HTML
            html_content = f"""
            <html>
                <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #667eea;">Password Reset Request</h2>
                    <p>Hi {user_name},</p>
                    <p>We received a request to reset your password. Click the button below to set a new password:</p>
                    <p style="margin: 30px 0;">
                        <a href="{reset_link}" 
                           style="background: #667eea; color: white; padding: 12px 30px; 
                                  text-decoration: none; border-radius: 5px; display: inline-block;">
                            Reset Password
                        </a>
                    </p>
                    <p>Or copy this link: {reset_link}</p>
                    <p>This link will expire in 24 hours.</p>
                    <p style="color: #e53e3e;">If you didn't request this, please ignore this email. 
                       Your password won't be changed.</p>
                    <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 30px 0;">
                    <p style="color: #666; font-size: 12px;">
                        For security, this link will expire in 24 hours.
                    </p>
                </body>
            </html>
            """
        
        text_content = f"""
Password Reset Request

Hi {user_name},

We received a request to reset your password. Visit the link below to set a new password:
{reset_link}

This link will expire in 24 hours.

If you didn't request this, please ignore this email. Your password won't be changed.
"""
        
        self._send_email(to_email, "Reset your VeriCase password", html_content, text_content)
    
    def send_approval_email(
        self,
        to_email: str,
        user_name: str,
        approved: bool,
        reason: str | None = None
    ) -> None:
        """Notify a user about approval or rejection results."""
        status_text = "approved" if approved else "rejected"
        subject = f"Your VeriCase account was {status_text}"
        if approved:
            body_text = (
                f"Hi {user_name},\n\n"
                "Great news! Your VeriCase account has been approved. "
                "You can now sign in and start working with your cases.\n\n"
                "— VeriCase Team"
            )
            html_body = f"""
            <html>
                <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #38a169;">Account Approved</h2>
                    <p>Hi {user_name},</p>
                    <p>Your VeriCase account has been approved. You can sign in immediately.</p>
                    <p style="margin-top: 24px;">Welcome aboard!</p>
                </body>
            </html>
            """
        else:
            reason_text = reason or "We were unable to verify your details at this time."
            body_text = (
                f"Hi {user_name},\n\n"
                "We reviewed your VeriCase account request but couldn't approve it.\n"
                f"Reason: {reason_text}\n\n"
                "If you believe this is an error, please contact support.\n\n"
                "— VeriCase Team"
            )
            html_body = f"""
            <html>
                <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #e53e3e;">Account Not Approved</h2>
                    <p>Hi {user_name},</p>
                    <p>We reviewed your VeriCase account request but couldn't approve it.</p>
                    <p><strong>Reason:</strong> {reason_text}</p>
                    <p>If you feel this was a mistake, please reach out to support.</p>
                </body>
            </html>
            """

        self._send_email(to_email, subject, html_body, body_text)

    def send_security_alert(
        self,
        to_email: str,
        user_name: str,
        alert_type: str,
        details: Mapping[str, str | None]
    ):
        """Send security alert email"""
        alert_messages = {
            'new_login': 'New Login Detected',
            'password_changed': 'Password Changed',
            'account_locked': 'Account Locked',
            'suspicious_activity': 'Suspicious Activity Detected'
        }
        
        subject = f"Security Alert: {alert_messages.get(alert_type, 'Security Notice')}"
        
        # Try to load template, fall back to simple HTML
        try:
            template = template_env.get_template('security-alert.html')
            html_content = template.render(
                user_name=user_name,
                alert_type=alert_type,
                alert_title=alert_messages.get(alert_type),
                details=details,
                frontend_url=self.frontend_url,
                timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            )
        except Exception:
            # Fallback HTML
            html_content = f"""
            <html>
                <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #e53e3e;">Security Alert</h2>
                    <p>Hi {user_name},</p>
                    <p>We detected the following activity on your account:</p>
                    <div style="background: #f7fafc; border: 1px solid #e2e8f0; 
                                border-radius: 5px; padding: 20px; margin: 20px 0;">
                        <h3 style="margin-top: 0;">{alert_messages.get(alert_type)}</h3>
                        <p>Time: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>
                        {f"<p>IP Address: {details.get('ip_address', 'Unknown')}</p>" if details.get('ip_address') else ""}
                        {f"<p>Device: {details.get('user_agent', 'Unknown')}</p>" if details.get('user_agent') else ""}
                    </div>
                    <p>If this was you, no action is needed.</p>
                    <p>If you don't recognize this activity, please secure your account immediately.</p>
                    <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 30px 0;">
                    <p style="color: #666; font-size: 12px;">
                        This is an automated security notification.
                    </p>
                </body>
            </html>
            """
        
        self._send_email(to_email, subject, html_content)
    
    def send_account_locked(self, to_email: str, user_name: str, locked_until: datetime, attempts: int):
        """Send account locked notification"""
        minutes_locked = int((locked_until - datetime.now(timezone.utc)).total_seconds() / 60)
        
        html_content = f"""
        <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #e53e3e;">Account Locked</h2>
                <p>Hi {user_name},</p>
                <p>Your account has been temporarily locked due to {attempts} failed login attempts.</p>
                <div style="background: #fff5f5; border: 1px solid #feb2b2; 
                            border-radius: 5px; padding: 20px; margin: 20px 0;">
                    <p style="margin: 0;"><strong>Locked for:</strong> {minutes_locked} minutes</p>
                    <p style="margin: 10px 0 0;"><strong>Unlock time:</strong> {locked_until.strftime("%Y-%m-%d %H:%M UTC")}</p>
                </div>
                <p>This is a security measure to protect your account from unauthorized access.</p>
                <p>If this wasn't you trying to login, please:</p>
                <ol>
                    <li>Wait for the lockout period to end</li>
                    <li>Reset your password immediately</li>
                    <li>Review your account for any suspicious activity</li>
                </ol>
                <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 30px 0;">
                <p style="color: #666; font-size: 12px;">
                    This is an automated security notification.
                </p>
            </body>
        </html>
        """
        
        self._send_email(to_email, "Account Locked - Too Many Failed Login Attempts", html_content)


# Global email service instance
email_service = EmailService()
