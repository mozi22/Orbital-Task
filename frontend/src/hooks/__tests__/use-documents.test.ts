import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../../lib/api";
import type { ConversationDetail, Document } from "../../types";
import { useDocuments } from "../use-documents";

function makeDocument(overrides: Partial<Document> = {}): Document {
	return {
		id: "doc-1",
		conversation_id: "conv-1",
		filename: "lease.pdf",
		display_name: "lease.pdf",
		page_count: 3,
		uploaded_at: "2026-01-01T00:00:00Z",
		...overrides,
	};
}

function makeConversationDetail(documents: Document[]): ConversationDetail {
	return {
		id: "conv-1",
		title: "Conversation",
		created_at: "2026-01-01T00:00:00Z",
		updated_at: "2026-01-01T00:00:00Z",
		has_document: documents.length > 0,
		documents,
	};
}

describe("useDocuments", () => {
	afterEach(() => {
		vi.restoreAllMocks();
		cleanup();
	});

	it("starts with an empty documents array when there is no conversation selected", () => {
		const { result } = renderHook(() => useDocuments(null));
		expect(result.current.documents).toEqual([]);
	});

	it("holds the full documents array returned by the conversation detail endpoint", async () => {
		const docs = [
			makeDocument({ id: "doc-1", filename: "lease.pdf" }),
			makeDocument({ id: "doc-2", filename: "title-report.pdf" }),
		];
		vi.spyOn(api, "fetchConversation").mockResolvedValue(
			makeConversationDetail(docs),
		);

		const { result } = renderHook(() => useDocuments("conv-1"));

		await waitFor(() => expect(result.current.documents).toHaveLength(2));
		expect(result.current.documents).toEqual(docs);
	});

	it("clears the documents array when the conversation id becomes null", async () => {
		const docs = [makeDocument()];
		vi.spyOn(api, "fetchConversation").mockResolvedValue(
			makeConversationDetail(docs),
		);

		const { result, rerender } = renderHook(
			({ conversationId }: { conversationId: string | null }) =>
				useDocuments(conversationId),
			{ initialProps: { conversationId: "conv-1" as string | null } },
		);

		await waitFor(() => expect(result.current.documents).toHaveLength(1));

		rerender({ conversationId: null });

		await waitFor(() => expect(result.current.documents).toEqual([]));
	});

	it("surfaces an error message when fetching the conversation fails", async () => {
		vi.spyOn(api, "fetchConversation").mockRejectedValue(new Error("boom"));

		const { result } = renderHook(() => useDocuments("conv-1"));

		await waitFor(() => expect(result.current.error).toBe("boom"));
		expect(result.current.documents).toEqual([]);
	});

	it("appends the newly uploaded document to the documents array", async () => {
		vi.spyOn(api, "fetchConversation").mockResolvedValue(
			makeConversationDetail([]),
		);
		const uploaded = makeDocument({ id: "doc-new", filename: "new.pdf" });
		vi.spyOn(api, "uploadDocument").mockResolvedValue(uploaded);

		const { result } = renderHook(() => useDocuments("conv-1"));
		await waitFor(() => expect(result.current.documents).toEqual([]));

		const file = new File(["%PDF-1.4"], "new.pdf", {
			type: "application/pdf",
		});
		await result.current.upload(file);

		await waitFor(() => expect(result.current.documents).toEqual([uploaded]));
	});

	it("re-throws upload errors so batch callers can tell success from failure per file", async () => {
		vi.spyOn(api, "fetchConversation").mockResolvedValue(
			makeConversationDetail([]),
		);
		vi.spyOn(api, "uploadDocument").mockRejectedValue(
			new Error("409: document limit exceeded"),
		);

		const { result } = renderHook(() => useDocuments("conv-1"));
		await waitFor(() => expect(result.current.documents).toEqual([]));

		const file = new File(["%PDF-1.4"], "new.pdf", {
			type: "application/pdf",
		});

		await expect(result.current.upload(file)).rejects.toThrow(
			"409: document limit exceeded",
		);
		await waitFor(() =>
			expect(result.current.error).toBe("409: document limit exceeded"),
		);
	});
});
