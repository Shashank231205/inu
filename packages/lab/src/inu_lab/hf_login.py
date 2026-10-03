"""Hugging Face login that works on networks that intercept HTTPS.

`hf auth login` checks the token over HTTPS with Python's bundled certificate list,
which fails when antivirus or a proxy re-signs traffic, so the token is never saved.
This does the same login through the operating system's trust store.

Run: uv run python -m inu_lab.hf_login
"""

import truststore
from huggingface_hub import login


def main() -> None:
    truststore.inject_into_ssl()
    login(skip_if_logged_in=False)  # prompts for the token in the terminal


if __name__ == "__main__":
    main()
