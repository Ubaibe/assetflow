from __future__ import annotations

from typing import TYPE_CHECKING

from database.enums import DocumentStatus

if TYPE_CHECKING:
    from database.models import InvoiceDocument
    from sqlalchemy.orm import Session


def set_document_status(
    session: Session,
    document: InvoiceDocument,
    status: DocumentStatus,
) -> None:
    document.processing_status = status
    session.add(document)
