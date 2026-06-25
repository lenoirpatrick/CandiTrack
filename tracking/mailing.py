"""Envoi d'emails de relance via Gmail (issue #67).

Utilise SMTP (``smtplib``, bibliothèque standard) avec un mot de passe
d'application Google. Les identifiants proviennent de
:class:`tracking.models.ReminderConfig`.
"""

import smtplib
import ssl
from email.message import EmailMessage

# Serveur SMTP de Gmail (authentification par mot de passe d'application).
GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587
SMTP_TIMEOUT = 20


class MailError(Exception):
    """Échec de l'envoi d'un email de relance (issue #67)."""


def send_email(config, to, subject, body):
    """Envoie un email texte via le compte Gmail configuré (issue #67).

    ``config`` est une :class:`~tracking.models.ReminderConfig`. Lève
    :class:`MailError` si la connexion n'est pas configurée, si le destinataire
    est absent ou si l'envoi SMTP échoue.
    """
    if not config.email_configured:
        raise MailError(
            "Connexion Gmail non configurée. Renseignez l'adresse et le mot de "
            "passe d'application dans Options → Relances."
        )
    to = (to or "").strip()
    if not to:
        raise MailError("Adresse du destinataire manquante.")

    message = EmailMessage()
    message["From"] = config.gmail_email
    message["To"] = to
    message["Subject"] = subject or "(sans objet)"
    message.set_content(body or "")

    try:
        with smtplib.SMTP(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(config.gmail_email, config.gmail_app_password)
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"Échec de l'envoi de l'email : {exc}") from exc
