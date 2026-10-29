import httpx


class TelegramClient:
    def __init__(self, bot_token: str, chat_id: str, timeout: float = 15.0):
        self.url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.chat_id = chat_id
        self.timeout = timeout

    def send(self, text: str) -> None:
        resp = httpx.post(
            self.url,
            json={"chat_id": self.chat_id, "text": text[:4000], "disable_web_page_preview": True},
            timeout=self.timeout,
        )
        resp.raise_for_status()
