import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Document } from "../../types";
import { DocumentViewer } from "../DocumentViewer";

// react-pdf drives an actual pdf.js worker, which isn't meaningful inside
// jsdom. The accordion shell only needs to know that *something* renders
// once a section is expanded, not that a real PDF decodes, so this stub
// captures the file it was asked to render without touching pdf.js at all.
// It fires `onLoadSuccess` on mount (with a fixed 3-page count) so tests can
// exercise the real page-nav UI (which lives in DocumentViewer itself, not
// in react-pdf) without needing an actual PDF to decode.
vi.mock("react-pdf", () => ({
	Document: ({
		children,
		onLoadSuccess,
	}: {
		children?: React.ReactNode;
		onLoadSuccess?: (result: { numPages: number }) => void;
	}) => {
		// biome-ignore lint/correctness/useExhaustiveDependencies: onLoadSuccess should fire once per mount, matching a real PDF load, not on every prop identity change.
		useEffect(() => {
			onLoadSuccess?.({ numPages: 3 });
		}, []);
		return <div data-testid="pdf-document">{children}</div>;
	},
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

	it("allows two sections to be expanded simultaneously (multi-expand, Set-based)", () => {
		const documents = [
			makeDocument({ id: "doc-1", display_name: "Lease Agreement" }),
			makeDocument({ id: "doc-2", display_name: "Title Report" }),
			makeDocument({ id: "doc-3", display_name: "Environmental Report" }),
		];

		render(<DocumentViewer documents={documents} />);

		fireEvent.click(screen.getByRole("button", { name: /lease agreement/i }));
		fireEvent.click(screen.getByRole("button", { name: /title report/i }));

		// Both expanded sections render their own PDF viewer at once; the
		// third, never-expanded section stays unmounted.
		expect(screen.getAllByTestId("pdf-document")).toHaveLength(2);
	});

	it("keeps page-nav state consistent across a collapse/re-expand cycle instead of resetting mid-transition", () => {
		const documents = [makeDocument({ id: "doc-1", page_count: 3 })];

		render(<DocumentViewer documents={documents} />);

		const header = screen.getByRole("button", {
			name: /lease agreement/i,
		});

		// Expand: the mocked react-pdf Document fires onLoadSuccess with 3
		// pages, so the real page-nav UI (owned by DocumentViewer, not
		// react-pdf) shows "Page 1 of 3".
		fireEvent.click(header);
		expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();

		// Move to page 2.
		fireEvent.click(screen.getByRole("button", { name: /next page/i }));
		expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();

		// Collapse the section, then re-expand it. Because the section was
		// already opened once, it must stay force-mounted underneath rather
		// than being unmounted by Radix and rebuilt from scratch. If it were
		// unmounted/remounted, numPages would momentarily reset to 0 while
		// currentPage stayed at 2, producing "Page 2 of 0" — and a fresh
		// mount would also reset currentPage back to 1, losing the
		// navigation the user did. Neither should happen: the page-nav must
		// read exactly "Page 2 of 3" immediately on re-expand, with no
		// intermediate "of 0" state and no reset back to page 1.
		fireEvent.click(header);
		fireEvent.click(header);

		expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
		expect(screen.queryByText(/page \d+ of 0/i)).not.toBeInTheDocument();
		expect(screen.getAllByTestId("pdf-document")).toHaveLength(1);
	});
});
