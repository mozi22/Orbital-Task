import type {
	Conversation,
	ConversationDetail,
	Document,
	Message,
} from "../types";

const BASE = "/api";

/**
 * Thrown for any non-OK API response. Carries the HTTP `status` plus, when
 * the backend returned its structured `{"detail": {"code", "message"}}`
 * error shape (as `services/document.py`'s upload errors do), a `code` that
 * lets callers tell failure reasons apart programmatically (e.g.
 * "document_limit_exceeded" vs. any other upload failure) instead of
 * pattern-matching on message text.
 */
export class ApiError extends Error {
	readonly status: number;
	readonly code: string | undefined;

	constructor(status: number, message: string, code?: string) {
		super(message);
		this.name = "ApiError";
		this.status = status;
		this.code = code;
	}
}

async function parseErrorBody(
	response: Response,
): Promise<{ message: string; code?: string }> {
	const text = await response.text().catch(() => "");
	if (!text) {
		return { message: `API error ${response.status}` };
	}

	try {
		const body = JSON.parse(text) as { detail?: unknown };
		const detail = body.detail;
		if (
			detail &&
			typeof detail === "object" &&
			"message" in detail &&
			typeof (detail as { message: unknown }).message === "string"
		) {
			const code = (detail as { code?: unknown }).code;
			return {
				message: (detail as { message: string }).message,
				code: typeof code === "string" ? code : undefined,
			};
		}
		if (typeof detail === "string") {
			return { message: detail };
		}
	} catch {
		// Not JSON (or not the expected shape) — fall back to the raw text
		// below rather than losing the error entirely.
	}

	return { message: text };
}

async function throwApiError(response: Response): Promise<never> {
	const { message, code } = await parseErrorBody(response);
	throw new ApiError(response.status, message, code);
}

async function handleResponse<T>(response: Response): Promise<T> {
	if (!response.ok) {
		await throwApiError(response);
	}
	return response.json() as Promise<T>;
}

export async function fetchConversations(): Promise<Conversation[]> {
	const res = await fetch(`${BASE}/conversations`);
	return handleResponse<Conversation[]>(res);
}

export async function createConversation(): Promise<Conversation> {
	const res = await fetch(`${BASE}/conversations`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ title: "New conversation" }),
	});
	return handleResponse<Conversation>(res);
}

export async function deleteConversation(id: string): Promise<void> {
	const res = await fetch(`${BASE}/conversations/${id}`, {
		method: "DELETE",
	});
	if (!res.ok) {
		await throwApiError(res);
	}
}

export async function fetchConversation(
	id: string,
): Promise<ConversationDetail> {
	const res = await fetch(`${BASE}/conversations/${id}`);
	return handleResponse<ConversationDetail>(res);
}

export async function fetchMessages(
	conversationId: string,
): Promise<Message[]> {
	const res = await fetch(`${BASE}/conversations/${conversationId}/messages`);
	return handleResponse<Message[]>(res);
}

export async function sendMessage(
	conversationId: string,
	content: string,
): Promise<Response> {
	const res = await fetch(`${BASE}/conversations/${conversationId}/messages`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ content }),
	});
	if (!res.ok) {
		await throwApiError(res);
	}
	return res;
}

export async function uploadDocument(
	conversationId: string,
	file: File,
): Promise<Document> {
	const formData = new FormData();
	formData.append("file", file);
	const res = await fetch(`${BASE}/conversations/${conversationId}/documents`, {
		method: "POST",
		body: formData,
	});
	return handleResponse<Document>(res);
}

export function getDocumentUrl(documentId: string): string {
	return `${BASE}/documents/${documentId}/content`;
}
