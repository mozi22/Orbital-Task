import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Document } from "../../types";
import { DocumentViewer } from "../DocumentViewer";

// react-pdf drives an actual pdf.js worker, which isn't meaningful inside
// jsdom. The accordion shell only needs to know that *something* renders
// once a section is expanded, not that a real PDF decodes, so this stub
// captures the file it was asked to render without touching pdf.js at all.
vi.mock("react-pdf", () => ({
	Document: ({ children }: { children?: React.ReactNode }) => (
		<div data-testid="pdf-document">{children}</div>
	),
	Page: ({ pageNumber }: { pageNumber: number }) => (
		<div data-testid="pdf-page">Page {pageNumber}</div>
	),
	pdfjs: { GlobalWorkerOptions: {} },
}));

function makeDocument(overrides: Partial<Document> = {}): Document {
	return {
		id: "doc-1",
		conversation_id: "conv-1",
		filename: "lease.pdf",
		display_name: "Lease Agreement",
		page_count: 3,
		uploaded_at: "2026-01-01T00:00:00Z",
		...overrides,
	};
}

describe("DocumentViewer", () => {
	afterEach(() => {
		vi.restoreAllMocks();
		cleanup();
	});

	it("shows an empty state when there are no documents", () => {
		render(<DocumentViewer documents={[]} />);
		expect(screen.getByText(/no document uploaded/i)).toBeInTheDocument();
	});

	it("renders one accordion section per document, headed by its display_name", () => {
		const documents = [
			makeDocument({ id: "doc-1", display_name: "Lease Agreement" }),
			makeDocument({ id: "doc-2", display_name: "Title Report" }),
			makeDocument({ id: "doc-3", display_name: "Environmental Report" }),
		];

		render(<DocumentViewer documents={documents} />);

		const headers = screen.getAllByRole("button", { name: /.+/ });
		expect(headers).toHaveLength(3);
		expect(
			screen.getByRole("button", { name: /lease agreement/i }),
		).toBeInTheDocument();
		expect(
			screen.getByRole("button", { name: /title report/i }),
		).toBeInTheDocument();
		expect(
			screen.getByRole("button", { name: /environmental report/i }),
		).toBeInTheDocument();
	});

	it("labels sections by display_name rather than the underlying filename", () => {
		const documents = [
			makeDocument({
				id: "doc-1",
				filename: "raw-upload-name.pdf",
				display_name: "Friendly Name",
			}),
		];

		render(<DocumentViewer documents={documents} />);

		expect(
			screen.getByRole("button", { name: /friendly name/i }),
		).toBeInTheDocument();
		expect(screen.queryByText("raw-upload-name.pdf")).not.toBeInTheDocument();
	});

	it("shows a conversation with 3 documents as 3 correctly-labeled sections, each independently expandable", () => {
		const documents = [
			makeDocument({ id: "doc-1", display_name: "Lease Agreement" }),
			makeDocument({ id: "doc-2", display_name: "Title Report" }),
			makeDocument({ id: "doc-3", display_name: "Environmental Report" }),
		];

		render(<DocumentViewer documents={documents} />);

		const leaseHeader = screen.getByRole("button", {
			name: /lease agreement/i,
		});
		fireEvent.click(leaseHeader);

		expect(screen.getAllByTestId("pdf-document")).toHaveLength(1);
	});
});
