import uuid

from langchain_core.tools import tool

from app.schemas.rag import OpenDocumentsResult, OpenedDocument, SourceReference
from app.tools.documents import open_documents

OPEN_DOCUMENTS_DESCRIPTION = (
    "Open whole MewFlow knowledge-base documents by id, using the ids in the "
    "document map. Call this when a policy, terms or procedure document listed "
    "there covers the question and you need its exact wording. Open at most a "
    "few documents per call."
)


def _format_opened(document: OpenedDocument) -> str:
    if document.text is not None:
        return (
            f'<document id="{document.document_id}" title="{document.title}" '
            f'version="{document.version}">\n{document.text}\n</document>'
        )
    sections = ", ".join(document.section_titles) or "no sections"
    return (
        f'Document "{document.title}" ({document.document_id}) was not included: '
        f"{document.omitted_reason}. Its sections: {sections}. Search the knowledge "
        "base for the part you need."
    )


def _format_result(result: OpenDocumentsResult) -> str:
    parts = [_format_opened(document) for document in result.documents]
    if result.not_found:
        ids = ", ".join(str(document_id) for document_id in result.not_found)
        parts.append(f"No document available with these ids: {ids}.")
    return "\n\n".join(parts) or "No document ids were given."


def _sources_of(result: OpenDocumentsResult) -> list[SourceReference]:
    return [
        SourceReference(
            title=document.title, doc_type=document.doc_type, source=document.source, version=document.version
        )
        for document in result.documents
        if document.text is not None
    ]


def make_open_documents_tool(tenant_id: uuid.UUID, plan_slug: str | None):
    @tool(response_format="content_and_artifact", description=OPEN_DOCUMENTS_DESCRIPTION)
    def open_documents_tool(document_ids: list[uuid.UUID]) -> tuple[str, list[SourceReference]]:
        result = open_documents(tenant_id, plan_slug, document_ids)
        return _format_result(result), _sources_of(result)

    return open_documents_tool
