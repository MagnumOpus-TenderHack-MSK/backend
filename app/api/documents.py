import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin_user
from app.db.session import get_db
from app.db.models import DocumentReference
from app.schemas.document import DocumentReferenceCreate, DocumentReferenceResponse

router = APIRouter(prefix="/documents", tags=["Documents"])
logger = logging.getLogger(__name__)

@router.get("", response_model=List[DocumentReferenceResponse])
def get_documents(
    db: Session = Depends(get_db)
):
    """
    Get all document references.
    """
    try:
        documents = db.query(DocumentReference).all()
        return documents
    except Exception as e:
        logger.error(f"Error getting documents: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get documents"
        )

@router.get("/{document_id}", response_model=DocumentReferenceResponse)
def get_document(
    document_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Get a specific document by ID.
    """
    document = db.query(DocumentReference).filter(DocumentReference.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    return document

@router.post("", response_model=DocumentReferenceResponse, status_code=status.HTTP_201_CREATED)
def create_document(
    document_data: DocumentReferenceCreate,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin_user)
):
    """
    Create a new document reference. Only admins can create documents.
    """
    try:
        document = DocumentReference(
            name=document_data.name,
            num=document_data.num,
            path=document_data.path,
            description=document_data.description
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        return document
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating document: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create document"
        )

@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_admin = Depends(get_current_admin_user)
):
    """
    Delete a document reference. Only admins can delete documents.
    """
    document = db.query(DocumentReference).filter(DocumentReference.id == document_id).first()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )

    try:
        db.delete(document)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting document: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete document"
        )