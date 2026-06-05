"""Disposable / throwaway email-domain blocklist used at registration.

This is a curated short list of the most common disposable providers — not a
comprehensive blocklist. The goal is to stop drive-by spam signups, not to
chase every new tempmail clone.
"""

from __future__ import annotations

DISPOSABLE_DOMAINS: frozenset[str] = frozenset(
    {
        "0815.ru",
        "10minutemail.com",
        "10minutemail.net",
        "20minutemail.com",
        "30minutemail.com",
        "anonbox.net",
        "anonymbox.com",
        "boximail.com",
        "burnermail.io",
        "deadaddress.com",
        "discard.email",
        "dispostable.com",
        "dropmail.me",
        "emailondeck.com",
        "fakeinbox.com",
        "fakemail.net",
        "getairmail.com",
        "getnada.com",
        "guerrillamail.com",
        "guerrillamail.net",
        "guerrillamail.org",
        "harakirimail.com",
        "inboxbear.com",
        "incognitomail.com",
        "instant-mail.de",
        "jetable.org",
        "mail-temporaire.fr",
        "mail.tm",
        "mailcatch.com",
        "maildrop.cc",
        "mailinator.com",
        "mailinator.net",
        "mailnesia.com",
        "mailtemp.uk",
        "mintemail.com",
        "moakt.com",
        "mohmal.com",
        "muellmail.com",
        "mytemp.email",
        "nada.email",
        "no-spam.ws",
        "onetimemail.com",
        "sharklasers.com",
        "spam4.me",
        "spamgourmet.com",
        "spamherelots.com",
        "tempail.com",
        "temp-mail.io",
        "temp-mail.org",
        "tempemail.com",
        "tempinbox.com",
        "tempmail.com",
        "tempmail.net",
        "tempmailo.com",
        "throwaway.email",
        "throwawaymail.com",
        "trashmail.com",
        "trashmail.net",
        "trashmail.ws",
        "yopmail.com",
        "yopmail.fr",
        "yopmail.net",
    }
)


def is_disposable(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].strip().lower()
    return domain in DISPOSABLE_DOMAINS
