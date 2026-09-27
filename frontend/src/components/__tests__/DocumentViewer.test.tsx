import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Document } from "../../types";
import { DocumentViewer } from "../DocumentViewer";

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

describe("DocumentViewer rename", () => {
	afterEach(() => {
		vi.restoreAllMocks();
		cleanup();
	});

	it("renders nothing rename-related when there is no document", () => {
		render(<DocumentViewer document={null} onRename={vi.fn()} />);
		expect(
			screen.queryByRole("button", { name: /rename document/i }),
		).not.toBeInTheDocument();
	});

	it("shows the document's display_name as the label, not its raw filename", () => {
		const document = makeDocument({
			filename: "raw-upload-name.pdf",
			display_name: "Signed Lease",
		});
		render(<DocumentViewer document={document} onRename={vi.fn()} />);
		expect(screen.getByText("Signed Lease")).toBeInTheDocument();
		expect(screen.queryByText("raw-upload-name.pdf")).not.toBeInTheDocument();
	});

	it("opens inline edit mode with the current display_name pre-filled when the pencil icon is clicked", () => {
		const document = makeDocument({ display_name: "Signed Lease" });
		render(<DocumentViewer document={document} onRename={vi.fn()} />);

		fireEvent.click(screen.getByRole("button", { name: /rename document/i }));

		const input = screen.getByRole("textbox", {
			name: /document name/i,
		}) as HTMLInputElement;
		expect(input.value).toBe("Signed Lease");
	});

	it("calls onRename with the document id and trimmed new name on submit, then exits edit mode", async () => {
		const document = makeDocument({ id: "doc-1", display_name: "lease.pdf" });
		const onRename = vi.fn().mockResolvedValue(undefined);
		render(<DocumentViewer document={document} onRename={onRename} />);

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
		const document = makeDocument({ display_name: "lease.pdf" });
		const onRename = vi.fn();
		render(<DocumentViewer document={document} onRename={onRename} />);

		fireEvent.click(screen.getByRole("button", { name: /rename document/i }));
		const input = screen.getByRole("textbox", { name: /document name/i });
		fireEvent.change(input, { target: { value: "   " } });
		fireEvent.submit(input.closest("form") as HTMLFormElement);

		expect(onRename).not.toHaveBeenCalled();
		expect(screen.getByText(/name cannot be empty/i)).toBeInTheDocument();
	});

	it("cancels editing without calling onRename when Escape is pressed", () => {
		const document = makeDocument({ display_name: "lease.pdf" });
		const onRename = vi.fn();
		render(<DocumentViewer document={document} onRename={onRename} />);

		fireEvent.click(screen.getByRole("button", { name: /rename document/i }));
		const input = screen.getByRole("textbox", { name: /document name/i });
		fireEvent.change(input, { target: { value: "Something else" } });
		fireEvent.keyDown(input, { key: "Escape" });

		expect(onRename).not.toHaveBeenCalled();
		expect(screen.getByText("lease.pdf")).toBeInTheDocument();
	});

	it("shows an error and stays in edit mode when the rename request fails", async () => {
		const document = makeDocument({ display_name: "lease.pdf" });
		const onRename = vi.fn().mockRejectedValue(new Error("Rename failed"));
		render(<DocumentViewer document={document} onRename={onRename} />);

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
});
