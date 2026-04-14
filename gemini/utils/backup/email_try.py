from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os
from pathlib import Path
import logging
import json
import smtplib

def _setup_logger():
    """Configure logger for tools module."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    logger = logging.getLogger("multitools")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(log_dir / "tools.log", encoding="utf-8")
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    return logger

logger = _setup_logger()


def email_tool(to_email: str, subject: str, body: str, attachment_path: str | None = None) -> str:
    """
    Send email with optional PDF attachment.
    
    Sends an email message via SMTP using credentials from environment variables.
    Supports optional file attachment for generated PDFs.
    
    Environment variables required:
    - EMAIL_USERNAME: Sender email address
    - EMAIL_PASSWORD: SMTP password or app-specific password
    - EMAIL_SMTP_SERVER: SMTP server host (default: smtp.gmail.com)
    - EMAIL_SMTP_PORT: SMTP port (default: 587)
    
    Args:
        to_email: Recipient email address
        subject: Email subject line
        body: Email body text
        attachment_path: Optional path to file to attach
        
    Returns:
        JSON string with status and result, or error message
    """
    try:
        # Validate inputs
        if not to_email or not subject or not body:
            error_msg = "Email address, subject, and body are required."
            logger.warning(f"email_tool: {error_msg}")
            return json.dumps({
                "status": "error",
                "message": error_msg
            })
        
        # Get SMTP configuration from environment
        smtp_server = os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.getenv("EMAIL_SMTP_PORT", "587"))
        sender_email = os.getenv("EMAIL_USERNAME", "periodictablesme@gmail.com")
        sender_password = os.getenv("EMAIL_PASSWORD", "rjxl wmay mmuk yxav")
        
        if not sender_email or not sender_password:
            error_msg = "EMAIL_USERNAME and EMAIL_PASSWORD environment variables not set."
            logger.error(f"email_tool: {error_msg}")
            return json.dumps({
                "status": "error",
                "message": "Error: Email credentials not configured. Check logs for details."
            })
        
        # Create email message
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        
        attachment_info = ""
        
        # Add attachment if provided
        if attachment_path:
            attachment_path = Path(attachment_path)
            if not attachment_path.exists():
                error_msg = f"Attachment file not found: {attachment_path}"
                logger.warning(f"email_tool: {error_msg}")
                return json.dumps({
                    "status": "error",
                    "message": error_msg
                })
            
            try:
                with open(attachment_path, "rb") as attachment:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(attachment.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename= {attachment_path.name}"
                )
                msg.attach(part)
                attachment_info = f" with attachment: {attachment_path.name}"
            except Exception as e:
                logger.error(f"email_tool attachment error: {e}", exc_info=True)
                return json.dumps({
                    "status": "error",
                    "message": "Error: Failed to attach file. Check logs for details."
                })
        
        # Send email
        try:
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, to_email, msg.as_string())
            server.quit()
            
            success_msg = f"Email sent to {to_email}{attachment_info}"
            logger.info(f"email_tool: {success_msg}")
            
            return json.dumps({
                "status": "success",
                "result": success_msg,
                "recipient": to_email
            })
            
        except smtplib.SMTPAuthenticationError:
            error_msg = "SMTP authentication failed."
            logger.error(f"email_tool: {error_msg}")
            return json.dumps({
                "status": "error",
                "message": "Error: SMTP authentication failed. Check EMAIL_USERNAME and EMAIL_PASSWORD."
            })
        except smtplib.SMTPException as e:
            logger.error(f"email_tool SMTP error: {e}", exc_info=True)
            return json.dumps({
                "status": "error",
                "message": "Error: SMTP error occurred. Check logs for details."
            })
        
    except Exception as e:
        logger.error(f"email_tool exception: {e}", exc_info=True)
        return json.dumps({
            "status": "error",
            "message": "Error: Email sending failed. Check logs for details."
        })

if __name__ == "__main__":
    e_mail = input("Enter recipient email address: ")
    subject = input("Enter email subject: ")
    body = input("Enter email body: ")
    attachment_path = input("Enter attachment file path (or leave blank for none): ")
    attachment_path = attachment_path if attachment_path.strip() else None
    print(email_tool(e_mail, subject, body, attachment_path))