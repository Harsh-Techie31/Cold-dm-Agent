import os
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.adk.agents import Agent


def extract_email(text: str) -> dict:
    """Extracts an email address from the given text blob.

    Args:
        text (str): The text blob containing a job opening and an email address.

    Returns:
        dict: status and result or error msg.
    """
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    match = re.search(email_pattern, text)

    if match:
        return {
            "status": "success",
            "email": match.group(0),
        }
    else:
        return {
            "status": "error",
            "error_message": "No email address found in the provided text.",
        }


def send_email(to_address: str, subject: str, body: str) -> dict:
    """Sends an email using Gmail SMTP.

    Args:
        to_address (str): The recipient's email address.
        subject (str): The email subject line.
        body (str): The email body content.

    Returns:
        dict: status and result or error msg.
    """
    smtp_email = os.environ.get("SMTP_EMAIL")
    smtp_password = os.environ.get("SMTP_PASSWORD")

    if not smtp_email or not smtp_password:
        return {
            "status": "error",
            "error_message": "SMTP credentials not configured. Set SMTP_EMAIL and SMTP_PASSWORD in .env",
        }

    msg = MIMEMultipart()
    msg["From"] = smtp_email
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, to_address, msg.as_string())
        return {
            "status": "success",
            "message": f"Email sent successfully to {to_address}",
        }
    except smtplib.SMTPAuthenticationError:
        return {
            "status": "error",
            "error_message": "SMTP authentication failed. Check your app password.",
        }
    except Exception as e:
        return {
            "status": "error",
            "error_message": f"Failed to send email: {str(e)}",
        }


root_agent = Agent(
    name="email_agent",
    model="gemini-flash-latest",
    description="Agent that extracts email from job text blobs and sends a greeting email.",
    instruction=(
        "You are an email assistant. When the user provides a job opening text blob, "
        "extract the email address from it using the extract_email tool, then use "
        "send_email to send a message with subject 'Hello from Google ADK Agent' "
        "and body 'Hey, I am sending you this email using Google ADK'."
    ),
    tools=[extract_email, send_email],
)
