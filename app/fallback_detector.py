import json
import logging
import os
from typing import Optional

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    OpenAI,
    RateLimitError,
)


DEFAULT_FALLBACK_MODEL = "gpt-4o-mini-2024-07-18"


def _get_client() -> Optional[OpenAI]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logging.warning("OPENAI_API_KEY not set; fallback detection disabled.")
        return None
    return OpenAI(api_key=api_key)


def detect_fallback(prompt_text: str, answer_text: str) -> bool:
    """
    Return True if the answer looks like a fallback (generic refusal, unclear/ask to rephrase,
    off-topic boilerplate, or inability to comply with the prompt).
    """
    if not answer_text.strip():
        return True

    client = _get_client()
    if client is None:
        return False

    model = os.getenv("FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL)

    system_msg = (
        "You are a strict classifier. Determine whether the assistant answer is a fallback response. "
        "A fallback is a generic refusal, an apology + ask to rephrase, a request to ask another way, "
        "a statement of inability to help, or boilerplate that does not address the user's prompt. "
        "Return only JSON with a single boolean field named 'fallback'."
    )
    user_msg = f"USER PROMPT:\n{prompt_text}\n\nASSISTANT ANSWER:\n{answer_text}"

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "fallback_check",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"fallback": {"type": "boolean"}},
                        "required": ["fallback"],
                        "additionalProperties": False,
                    },
                },
            },
            temperature=0,
            timeout=60,
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        return bool(data.get("fallback", False))
    except AuthenticationError as e:
        logging.error("Fallback detection auth error: %s: %s", type(e).__name__, e)
        return False
    except RateLimitError as e:
        logging.warning("Fallback detection rate limited: %s: %s", type(e).__name__, e)
        return False
    except (APIConnectionError, APITimeoutError) as e:
        logging.warning("Fallback detection network/timeout error: %s: %s", type(e).__name__, e)
        return False
    except BadRequestError as e:
        logging.error("Fallback detection bad request (model/config): %s: %s", type(e).__name__, e)
        return False
    except Exception as e:
        logging.exception("Fallback detection failed: %s: %s", type(e).__name__, e)
        return False
