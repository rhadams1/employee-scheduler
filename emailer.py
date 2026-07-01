"""SMTP email sending for the Ice Line scheduler.

Pure of any import from app.py. Transport is implicit-SSL SMTP (megamailservers).
`smtp` is a plain dict so callers pass exactly what they need and this stays testable.
"""
import smtplib
from email.message import EmailMessage
from email.utils import formataddr


def build_message(from_addr, from_name, to_addr, subject, html_body, text_body):
    """Build a multipart/alternative email (text + HTML). Pure — does not send."""
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = formataddr((from_name, from_addr))
    msg['To'] = to_addr
    msg['Reply-To'] = from_addr
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype='html')
    return msg


def send_email(smtp, to_addr, subject, html_body, text_body):
    """Send one email via implicit-SSL SMTP. Raises on any failure."""
    msg = build_message(
        smtp['from_addr'], smtp['from_name'], to_addr, subject, html_body, text_body
    )
    with smtplib.SMTP_SSL(smtp['host'], smtp['port'], timeout=30) as server:
        server.login(smtp['user'], smtp['password'])
        server.send_message(msg)
