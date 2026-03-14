"""Manual SMTP smoke test.

Set environment variables before running:
- EMAIL_HOST_USER
- EMAIL_HOST_PASSWORD
"""

import os
import smtplib
from email.mime.text import MIMEText


EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USER = os.environ.get('EMAIL_HOST_USER', '').strip()
EMAIL_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '').strip()


def main():
    if not EMAIL_USER or not EMAIL_PASSWORD:
        print('EMAIL_HOST_USER and EMAIL_HOST_PASSWORD must be set in environment variables.')
        return

    msg = MIMEText('Your Marvel Safari email configuration is working.')
    msg['Subject'] = 'Test from Marvel Safari'
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_USER

    print(f"Connecting to {EMAIL_HOST}:{EMAIL_PORT} via TLS...")
    try:
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            server.starttls()
            print("Connected. Logging in...")
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            print("Logged in. Sending email...")
            server.sendmail(EMAIL_USER, [EMAIL_USER], msg.as_string())
            print(f"SUCCESS: Email sent to {EMAIL_USER}")
    except smtplib.SMTPAuthenticationError as exc:
        print(f"AUTHENTICATION FAILED: {exc}")
        print("Generate a new app password at https://myaccount.google.com/apppasswords")
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}")


if __name__ == '__main__':
    main()
