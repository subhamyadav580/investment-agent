import smtplib
from email.message import EmailMessage


class EmailClient:
    def __init__(self, host: str, port: int, username: str, password: str, sender: str, recipient: str):
        self.host, self.port = host, port
        self.username, self.password = username, password
        self.sender, self.recipient = sender, recipient

    def send(self, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, self.sender, self.recipient
        msg.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=20) as smtp:
            smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(msg)
