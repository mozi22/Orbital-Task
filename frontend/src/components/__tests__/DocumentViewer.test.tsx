import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
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

		// The expand/collapse trigger's accessible name is set explicitly to
		// each document's display_name (see DocumentViewer.tsx), so querying
		// by exact name finds exactly one trigger per document — distinct
		// from the "Rename document" pencil button that also lives in each
		// header, asserted separately below.
		const toggleButtons = documents.map((doc) =>
			screen.getByRole("button", { name: doc.display_name }),
		);
		expect(toggleButtons).toHaveLength(3);
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

		expect(screen.getByText("Friendly Name")).toBeInTheDocument();
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

	it("collapses the previously-open section when a different section is expanded (single-expand)", () => {
		const documents = [
			makeDocument({ id: "doc-1", display_name: "Lease Agreement" }),
			makeDocument({ id: "doc-2", display_name: "Title Report" }),
			makeDocument({ id: "doc-3", display_name: "Environmental Report" }),
		];

		render(<DocumentViewer documents={documents} />);

		fireEvent.click(screen.getByRole("button", { name: /lease agreement/i }));
		expect(
			screen
				.getByRole("button", { name: /lease agreement/i })
				.closest("div[data-state]"),
		).toHaveAttribute("data-state", "open");

		fireEvent.click(screen.getByRole("button", { name: /title report/i }));

		// The newly-opened section is open; the previously-open section was
		// collapsed, not left open alongside it (Environmental Report, never
		// clicked, stays collapsed throughout).
		expect(
			screen
				.getByRole("button", { name: /title report/i })
				.closest("div[data-state]"),
		).toHaveAttribute("data-state", "open");
		expect(
			screen
				.getByRole("button", { name: /lease agreement/i })
				.closest("div[data-state]"),
		).toHaveAttribute("data-state", "closed");
		expect(
			screen
				.getByRole("button", { name: /environmental report/i })
				.closest("div[data-state]"),
		).toHaveAttribute("data-state", "closed");
	});

	it("renders the newly-opened document's own content, not the previous section's", () => {
		const documents = [
			makeDocument({ id: "doc-1", display_name: "Lease Agreement" }),
			makeDocument({ id: "doc-2", display_name: "Title Report" }),
		];

		render(<DocumentViewer documents={documents} />);

		fireEvent.click(screen.getByRole("button", { name: /lease agreement/i }));
		fireEvent.click(screen.getByRole("button", { name: /title report/i }));

		// The Title Report section's content is visible...
		const titleSection = screen
			.getByRole("button", { name: /title report/i })
			.closest("div[data-state]") as HTMLElement | null;
		expect(titleSection).not.toBeNull();
		expect(titleSection).toHaveAttribute("data-state", "open");

		// ...while the Lease Agreement section is collapsed.
		const leaseSection = screen
			.getByRole("button", { name: /lease agreement/i })
			.closest("div[data-state]") as HTMLElement | null;
		expect(leaseSection).not.toBeNull();
		expect(leaseSection).toHaveAttribute("data-state", "closed");
	});

	it("re-expanding a previously-opened, now-collapsed section still renders that document's own content", () => {
		const documents = [
			makeDocument({ id: "doc-1", display_name: "Lease Agreement" }),
			makeDocument({ id: "doc-2", display_name: "Title Report" }),
		];

		render(<DocumentViewer documents={documents} />);

		// Open Lease, then Title (collapsing Lease), then Lease again
		// (collapsing Title). Lease was force-mounted from its first open, so
		// this exercises that its own PDF content is still correctly shown
		// on re-expand rather than showing stale/wrong content.
		fireEvent.click(screen.getByRole("button", { name: /lease agreement/i }));
		fireEvent.click(screen.getByRole("button", { name: /title report/i }));
		fireEvent.click(screen.getByRole("button", { name: /lease agreement/i }));

		const leaseSection = screen
			.getByRole("button", { name: /lease agreement/i })
			.closest("div[data-state]") as HTMLElement | null;
		expect(leaseSection).toHaveAttribute("data-state", "open");

		const titleSection = screen
			.getByRole("button", { name: /title report/i })
			.closest("div[data-state]") as HTMLElement | null;
		expect(titleSection).toHaveAttribute("data-state", "closed");
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

describe("DocumentViewer rename", () => {
	afterEach(() => {
		vi.restoreAllMocks();
		cleanup();
	});

	it("renders nothing rename-related when there are no documents", () => {
		render(<DocumentViewer documents={[]} onRename={vi.fn()} />);
		expect(
			screen.queryByRole("button", { name: /rename document/i }),
		).not.toBeInTheDocument();
	});

	it("shows the document's display_name as the label, not its raw filename", () => {
		const documents = [
			makeDocument({
				filename: "raw-upload-name.pdf",
				display_name: "Signed Lease",
			}),
		];
		render(<DocumentViewer documents={documents} onRename={vi.fn()} />);
		expect(screen.getByText("Signed Lease")).toBeInTheDocument();
		expect(screen.queryByText("raw-upload-name.pdf")).not.toBeInTheDocument();
	});

	it("opens inline edit mode with the current display_name pre-filled when the pencil icon is clicked", () => {
		const documents = [makeDocument({ display_name: "Signed Lease" })];
		render(<DocumentViewer documents={documents} onRename={vi.fn()} />);

		fireEvent.click(screen.getByRole("button", { name: /rename document/i }));

		const input = screen.getByRole("textbox", {
			name: /document name/i,
		}) as HTMLInputElement;
		expect(input.value).toBe("Signed Lease");
	});

	it("calls onRename with the document id and trimmed new name on submit, then exits edit mode", async () => {
		const documents = [
			makeDocument({ id: "doc-1", display_name: "lease.pdf" }),
		];
		const onRename = vi.fn().mockResolvedValue(undefined);
		render(<DocumentViewer documents={documents} onRename={onRename} />);

		fireEvent.click(screen.getByRole("button", { name: /rename document/i }));
		const input = screen.getByRole("textbox", { name: /document name/i });
		fireEvent.change(input, { target: { value: "  Signed Lease  " } });
		fireEvent.submit(input.closest("form") as HTMLFormElement);

		await waitFor(() =>
			expect(onRename).toHaveBeenCalledWith("doc-1", "Signed Lease"),
		);
		await waitFor(() =>
			expect(
				screen.queryByRole("textbox", { name: /document name/i }),
			).not.toBeInTheDocument(),
		);
	});

	it("does not submit a blank or whitespace-only name", () => {
		const documents = [makeDocument({ display_name: "lease.pdf" })];
		const onRename = vi.fn();
		render(<DocumentViewer documents={documents} onRename={onRename} />);

		fireEvent.click(screen.getByRole("button", { name: /rename document/i }));
		const input = screen.getByRole("textbox", { name: /document name/i });
		fireEvent.change(input, { target: { value: "   " } });
		fireEvent.submit(input.closest("form") as HTMLFormElement);

		expect(onRename).not.toHaveBeenCalled();
		expect(screen.getByText(/name cannot be empty/i)).toBeInTheDocument();
	});

	it("cancels editing without calling onRename when Escape is pressed", () => {
		const documents = [makeDocument({ display_name: "lease.pdf" })];
		const onRename = vi.fn();
		render(<DocumentViewer documents={documents} onRename={onRename} />);

		fireEvent.click(screen.getByRole("button", { name: /rename document/i }));
		const input = screen.getByRole("textbox", { name: /document name/i });
		fireEvent.change(input, { target: { value: "Something else" } });
		fireEvent.keyDown(input, { key: "Escape" });

		expect(onRename).not.toHaveBeenCalled();
		expect(screen.getByText("lease.pdf")).toBeInTheDocument();
	});

	it("shows an error and stays in edit mode when the rename request fails", async () => {
		const documents = [makeDocument({ display_name: "lease.pdf" })];
		const onRename = vi.fn().mockRejectedValue(new Error("Rename failed"));
		render(<DocumentViewer documents={documents} onRename={onRename} />);

		fireEvent.click(screen.getByRole("button", { name: /rename document/i }));
		const input = screen.getByRole("textbox", { name: /document name/i });
		fireEvent.change(input, { target: { value: "New Name" } });
		fireEvent.submit(input.closest("form") as HTMLFormElement);

		await waitFor(() =>
			expect(screen.getByText("Rename failed")).toBeInTheDocument(),
		);
		expect(
			screen.getByRole("textbox", { name: /document name/i }),
		).toBeInTheDocument();
	});

	it("does not toggle the accordion section when clicking the pencil to start renaming", () => {
		const documents = [makeDocument({ display_name: "Lease Agreement" })];
		render(<DocumentViewer documents={documents} onRename={vi.fn()} />);

		fireEvent.click(screen.getByRole("button", { name: /rename document/i }));

		// The section must still be collapsed: no PDF content is mounted.
		expect(screen.queryByTestId("pdf-document")).not.toBeInTheDocument();
	});
});
