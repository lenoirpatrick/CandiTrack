"""Conversion d'un CV HTML en fichier PDF téléchargeable (issue #66).

Le code HTML est produit par l'IA (voir :func:`tracking.coaching.cv_html`) ;
on le convertit en PDF avec **xhtml2pdf** (dépendance pip pure, sans toolchain
système). Le PDF obtenu conserve un texte sélectionnable.
"""

import io

from xhtml2pdf import pisa


class PdfRenderError(Exception):
    """Échec de conversion HTML → PDF, message présentable à l'utilisateur."""


def render_pdf(html):
    """Convertit le document ``html`` en PDF et renvoie ses octets.

    Lève :class:`PdfRenderError` si la conversion échoue.
    """
    buffer = io.BytesIO()
    try:
        status = pisa.CreatePDF(html, dest=buffer, encoding="utf-8")
    except Exception as exc:  # xhtml2pdf remonte des exceptions variées
        raise PdfRenderError(f"Conversion HTML → PDF impossible : {exc}") from exc
    if status.err:
        raise PdfRenderError("Le document HTML n'a pas pu être converti en PDF.")
    return buffer.getvalue()
