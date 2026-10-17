"""How Cyphward's scanner identifies itself on every HTTP request it makes.

Site owners who see this User-Agent in their logs can read what the scanner
does, and how to reach us, at SCANNER_INFO_URL.
"""

SCANNER_INFO_URL = "https://cyphward.com/scanner"
SCANNER_USER_AGENT = f"Cyphward-Security-Scanner/1.0 (+{SCANNER_INFO_URL})"
