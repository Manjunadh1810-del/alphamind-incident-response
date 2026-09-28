"""Groq LLM wrapper with basic retry and clear errors. Key comes from the environment only."""
import os
import time

from dotenv import load_dotenv

load_dotenv()
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


class LLMError(RuntimeError):
    pass


def chat(system: str, user: str, temperature: float = 0.2, attempts: int = 3) -> str:
    if not os.getenv("GROQ_API_KEY"):
        raise LLMError("GROQ_API_KEY is not set. Add it to your .env file.")
    from groq import Groq
    client = Groq()  # reads GROQ_API_KEY from the environment
    last = None
    for i in range(attempts):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=temperature,
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return text
            last = "empty response"
        except Exception as e:  # network, rate limit, model errors
            last = f"{type(e).__name__}: {e}"
        time.sleep(1.5 * (i + 1))
    raise LLMError(f"LLM call failed after {attempts} attempts: {last}")
