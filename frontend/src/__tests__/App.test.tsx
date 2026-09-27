import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { Document } from "../types";

const useConversationsMock = vi.fn();
const useMessagesMock = vi.fn();
const useDocumentsMock = vi.fn();

vi.mock("../hooks/use-conversations", () => ({
	useConversations: () => useConversationsMock(),
}));
vi.mock("../hooks/use-messages", () => ({
	useMessages: () => useMessagesMock(),
}));
vi.mock("../hooks/use-documents", () => ({
	useDocuments: () => useDocumentsMock(),
}));

// DocumentViewer renders a real PDF via react-pdf/pdfjs, which isn't
// meaningful in jsdom and isn't what this test is about (App's wiring of
// documents.length through to the cap messaging is); stub it out.
vi.mock("../components/DocumentViewer", () => ({
	DocumentViewer: () => null,
}));

function makeDocuments(count: number): Document[] {
	return Array.from({ length: count }, (_, i) => ({
		id: `doc-${i}`,
		conversation_id: "conv-1",
		filename: `doc-${i}.pdf`,
		display_name: `doc-${i}.pdf`,
		page_count: 1,
		uploaded_at: "2026-01-01T00:00:00Z",
		document_type: null,
	}));
}

function setupHooks(documentCount: number) {
	useConversationsMock.mockReturnValue({
		conversations: [],
		selectedId: "conv-1",
		loading: false,
		create: vi.fn(),
		select: vi.fn(),
		remove: vi.fn(),
		refresh: vi.fn(),
	});
	useMessagesMock.mockReturnValue({
		messages: [],
		loading: false,
		error: null,
		streaming: false,
		streamingContent: "",
		send: vi.fn(),
	});
	useDocumentsMock.mockReturnValue({
		documents: makeDocuments(documentCount),
		upload: vi.fn(),
		error: null,
		refresh: vi.fn(),
	});
}

describe("App", () => {
	afterEach(() => {
		vi.restoreAllMocks();
		cleanup();
	});

	it("reads documents.length (not a singular hasDocument/document) to drive the cap UI, showing the correct count below the cap", () => {
		setupHooks(3);
		render(<App />);

		expect(
			screen.getAllByText("3/5 documents attached").length,
		).toBeGreaterThan(0);
	});

	it('shows "5/5 documents attached" and disables the upload control once the conversation holds 5 documents', () => {
		setupHooks(5);
		render(<App />);

		expect(
			screen.getAllByText("5/5 documents attached").length,
		).toBeGreaterThan(0);
		expect(screen.getByRole("button", { name: /attach/i })).toBeDisabled();
	});
});
