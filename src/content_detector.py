"""
ClipKeeper — Content Detector.
Auto-detects content type from text: URLs, emails, phone numbers, code, colors.
"""

import re
from typing import Optional

from .i18n import tr


# --- Patterns ---

URL_PATTERN = re.compile(
    r"https?://[^\s<>\"'\)\]]+", re.IGNORECASE
)

EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", re.IGNORECASE
)

PHONE_PATTERN = re.compile(
    r"(?:\+?\d{1,3}[\s\-.]?)?\(?\d{2,4}\)?[\s\-.]?\d{3,4}[\s\-.]?\d{2,4}"
)

HEX_COLOR_PATTERN = re.compile(
    r"^#(?:[0-9a-fA-F]{3}){1,2}$"
)

RGB_COLOR_PATTERN = re.compile(
    r"(?:rgb|hsl)a?\(\s*\d+", re.IGNORECASE
)

# Code detection markers — presence of multiple of these suggests code
CODE_MARKERS = [
    # Python
    r"\bdef\s+\w+\s*\(", r"\bclass\s+\w+", r"\bimport\s+\w+", r"\bfrom\s+\w+\s+import\b",
    r"\bif\s+__name__\s*==", r"\bself\.\w+",
    # JavaScript/TypeScript
    r"\bfunction\s+\w+\s*\(", r"\bconst\s+\w+\s*=", r"\blet\s+\w+\s*=", r"\bvar\s+\w+\s*=",
    r"\b=>\s*[{(]", r"\bconsole\.log\b", r"\bexport\s+(?:default\s+)?(?:function|class|const)\b",
    # General
    r"\breturn\s+", r"\bfor\s*\(", r"\bwhile\s*\(", r"\bif\s*\(.+\)\s*[{:]",
    r"\btry\s*[{:]", r"\bcatch\s*\(", r"\bswitch\s*\(",
    # C/C++/Java/Go/Rust
    r"\b(?:int|void|char|float|double|bool)\s+\w+", r"#include\s*<",
    r"\bfn\s+\w+", r"\bfunc\s+\w+", r"\bpub\s+fn\b",
    # Shell
    r"^#!/", r"\becho\s+", r"\bsudo\s+",
    # SQL
    r"\bSELECT\s+.+\bFROM\b", r"\bINSERT\s+INTO\b", r"\bCREATE\s+TABLE\b",
    # Brackets and syntax
    r"[{}\[\]];$", r"^\s*//\s", r"^\s*#\s(?![\!])",
]

CODE_COMPILED = [re.compile(p, re.MULTILINE | re.IGNORECASE) for p in CODE_MARKERS]

# Language detection (for syntax highlighting hints)
LANG_HINTS = {
    "python": [r"\bdef\s+\w+\(", r"\bimport\s+\w+", r"\bself\.", r":\s*$"],
    "javascript": [r"\bconst\s+\w+", r"\blet\s+\w+", r"\b=>\s*", r"\bconsole\."],
    "bash": [r"^#!/bin/(?:ba)?sh", r"\becho\s+", r"\bsudo\s+", r"\|\s*grep\b"],
    "sql": [r"\bSELECT\b", r"\bFROM\b", r"\bWHERE\b", r"\bINSERT\b"],
    "html": [r"</?(?:div|span|p|a|h[1-6]|ul|li|table|body|html)\b", r"</\w+>"],
    "css": [r"\{[^}]*:\s*[^}]+\}", r"@media\b", r"\.[\w-]+\s*\{"],
    "json": [r'^\s*\{[\s\S]*"[\w]+"\s*:', r'^\s*\['],
    "rust": [r"\bfn\s+\w+", r"\blet\s+mut\b", r"\bimpl\b", r"\bpub\s+fn\b"],
    "go": [r"\bfunc\s+\w+", r"\bpackage\s+\w+", r"\bfmt\.\w+"],
}

LANG_COMPILED = {
    lang: [re.compile(p, re.MULTILINE | re.IGNORECASE) for p in patterns]
    for lang, patterns in LANG_HINTS.items()
}


class ContentDetector:
    """Detects the category and subtype of clipboard text content."""

    @staticmethod
    def detect(text: str) -> tuple[str, Optional[str], dict, bool]:
        """
        Analyze text and return (category, subtype, metadata, is_sensitive).

        Categories: 'url', 'email', 'phone', 'code', 'color', 'text'
        Subtype: language for code, domain for urls, etc.
        Metadata: additional info (url, domain, title, language, etc.)
        is_sensitive: True if content looks like a secret
        """
        stripped = text.strip()
        is_sensitive = ContentDetector.detect_sensitive(text)

        # Check for color (short, specific patterns)
        if len(stripped) < 30:
            if HEX_COLOR_PATTERN.match(stripped):
                return "color", "hex", {"color_value": stripped}, is_sensitive
            if RGB_COLOR_PATTERN.match(stripped):
                return "color", "rgb", {"color_value": stripped}, is_sensitive

        # Check for URL (if entire text is basically a URL)
        if ContentDetector._is_url(stripped):
            domain = ContentDetector._extract_domain(stripped)
            # URLs usually aren't sensitive unless they have tokens, but let's trust detect_sensitive
            return "url", domain, {"url": stripped, "domain": domain}, is_sensitive

        # Check for email
        if ContentDetector._is_email(stripped):
            return "email", None, {"email": stripped}, False # Emails usually public id

        # Check for phone number (short text that matches phone pattern)
        if len(stripped) < 25 and ContentDetector._is_phone(stripped):
            return "phone", None, {"phone": stripped}, False

        # Check for code
        if ContentDetector._is_code(stripped):
            language = ContentDetector._detect_language(stripped)
            return "code", language, {"language": language}, is_sensitive

        # Check if text contains URLs (mixed content)
        urls = URL_PATTERN.findall(stripped)
        if urls:
            return "text", "with_urls", {"urls": urls[:5]}, is_sensitive

        return "text", None, {}, is_sensitive

    @staticmethod
    def _is_url(text: str) -> bool:
        """Check if the text is primarily a URL."""
        lines = text.strip().split("\n")
        if len(lines) > 3:
            return False
        # Single URL or URL with minimal surrounding text
        stripped = lines[0].strip()
        return bool(URL_PATTERN.match(stripped)) and len(stripped) < 2048

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract domain from URL."""
        try:
            # Remove protocol
            domain = url.split("//", 1)[-1].split("/", 1)[0]
            # Remove port
            domain = domain.split(":")[0]
            # Remove www
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return ""

    @staticmethod
    def _is_email(text: str) -> bool:
        """Check if text is primarily an email address."""
        stripped = text.strip()
        if "\n" in stripped or len(stripped) > 254:
            return False
        return bool(EMAIL_PATTERN.fullmatch(stripped))

    @staticmethod
    def _is_phone(text: str) -> bool:
        """Check if text is a phone number."""
        stripped = text.strip()
        # Remove common phone formatting chars
        digits_only = re.sub(r"[\s\-\(\)\.\+]", "", stripped)
        if not digits_only.isdigit():
            return False
        if len(digits_only) < 7 or len(digits_only) > 15:
            return False
        return bool(PHONE_PATTERN.match(stripped))

    @staticmethod
    def _is_code(text: str) -> bool:
        """Check if text looks like source code."""
        if len(text) < 10:
            return False

        score = 0
        for pattern in CODE_COMPILED:
            if pattern.search(text):
                score += 1
                if score >= 2:
                    return True

        # High ratio of special chars also suggests code
        special = sum(1 for c in text if c in "{}[]();=<>|&!@#$%^*~`")
        if len(text) > 0 and special / len(text) > 0.08:
            score += 1

        # Multiple lines with consistent indentation suggests code
        lines = text.split("\n")
        if len(lines) >= 3:
            indented = sum(1 for line in lines if line.startswith(("  ", "\t")))
            if indented / len(lines) > 0.4:
                score += 1

        return score >= 2

    @staticmethod
    def _detect_language(text: str) -> Optional[str]:
        """Try to detect the programming language of code."""
        scores = {}
        for lang, patterns in LANG_COMPILED.items():
            score = sum(1 for p in patterns if p.search(text))
            if score > 0:
                scores[lang] = score

        if not scores:
            return None
        return max(scores, key=scores.get)

    @staticmethod
    def get_category_icon(category: str) -> str:
        """Get display icon for a category."""
        icons = {
            "text": "edit-paste-symbolic",
            "url": "web-browser-symbolic",
            "email": "mail-unread-symbolic",
            "phone": "call-start-symbolic",
            "code": "utilities-terminal-symbolic",
            "color": "color-select-symbolic",
            "image": "image-x-generic-symbolic",
        }
        return icons.get(category, "edit-paste-symbolic")

    @staticmethod
    def get_category_label(category: str) -> str:
        """Get display label for a category."""
        labels = {
            "all": tr("detector.all"),
            "text": tr("detector.text"),
            "url": tr("detector.url"),
            "email": tr("detector.email"),
            "phone": tr("detector.phone"),
            "code": tr("detector.code"),
            "color": tr("detector.color"),
            "image": tr("detector.image"),
        }
        return labels.get(category, category.title())

    @staticmethod
    def detect_sensitive(text: str) -> bool:
        """Check if text contains sensitive data (keys, tokens, passwords)."""
        if not text:
            return False
            
        # 1. Private Keys
        if "PRIVATE KEY-----" in text:
            return True
            
        # 2. Common API Key Patterns
        # AWS Access Key ID
        if re.search(r"AKIA[0-9A-Z]{16}", text):
            return True
        # Stripe
        if re.search(r"(?:sk|pk)_(?:test|live)_[0-9a-zA-Z]{24}", text):
            return True
        # Google API Key (loose)
        if re.search(r"AIza[0-9A-Za-z-_]{35}", text):
            return True
        
        # 3. High Entropy Strings (Potential Passwords/Tokens)
        # No spaces, mixed case, numbers, symbols, length > 12
        stripped = text.strip()
        if " " not in stripped and len(stripped) > 12 and len(stripped) < 128:
            has_upper = bool(re.search(r"[A-Z]", stripped))
            has_lower = bool(re.search(r"[a-z]", stripped))
            has_digit = bool(re.search(r"\d", stripped))
            has_symbol = bool(re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?]", stripped))
            
            # Strong password criteria
            if has_upper and has_lower and has_digit and has_symbol:
                return True
                
        return False
