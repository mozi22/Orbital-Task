export interface Conversation {
	id: string;
	title: string;
	created_at: string;
	updated_at: string;
	has_document: boolean;
}

export interface Message {
	id: string;
	conversation_id: string;
	role: "user" | "assistant" | "system";
	content: string;
	sources_cited: number;
	created_at: string;
}

/**
 * Mirrors the backend's `DocumentType` enum
 * (backend/src/takehome/db/models.py). `null` until auto-classification
 * runs (Milestone 2's #32, not yet built) or the user corrects it via the
 * dropdown next to the rename pencil (see #33).
 */
export type DocumentType = "title" | "lease" | "environmental" | "other";

export interface Document {
	id: string;
	conversation_id: string;
	filename: string;
	display_name: string;
	page_count: number;
	uploaded_at: string;
	document_type: DocumentType | null;
}

export interface ConversationDetail extends Conversation {
	documents: Document[];
}

/**
 * Mirrors the backend's `RiskReviewTriggerResponse`
 * (backend/src/takehome/web/routers/risk_review.py). `run_id` is currently
 * backed 1:1 by the conversation's `Matter` id, but kept as its own field
 * name so the client-facing contract doesn't have to change if a future
 * ticket adds a distinct per-run record.
 */
export interface RiskReviewTrigger {
	run_id: string;
	status: "running";
}
