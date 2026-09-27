import {
	cleanup,
	fireEvent,
	render,
	screen,
	waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DocumentUpload } from "../DocumentUpload";

function makePdf(name: string): File {
	return new File(["%PDF-1.4"], name, { type: "application/pdf" });
}

function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((res) => {
		resolve = res;
	});
	return { promise, resolve };
}

function dropFiles(target: Element, files: File[]) {
	fireEvent.drop(target, {
		dataTransfer: { files },
	});
}

describe("DocumentUpload", () => {
	afterEach(() => {
		vi.restoreAllMocks();
		// This project's vite/vitest config runs with `globals: false`, so
		// Testing Library's automatic afterEach-based cleanup never registers
		// itself; without an explicit cleanup, DOM (and any role="alert" nodes)
		// from one test leaks into the next and getByRole throws "found
		// multiple elements".
		cleanup();
	});

	it("marks the file input as accepting multiple files", () => {
		const { container } = render(<DocumentUpload onUpload={vi.fn()} />);
		const input = container.querySelector("input[type=file]");
		expect(input).toHaveAttribute("multiple");
	});

	it("calls onUpload once per dropped PDF file", async () => {
		const onUpload = vi.fn().mockResolvedValue(undefined);
		const { container } = render(<DocumentUpload onUpload={onUpload} />);
		const dropzone = container.querySelector("button") as HTMLElement;

		dropFiles(dropzone, [makePdf("a.pdf"), makePdf("b.pdf"), makePdf("c.pdf")]);

		await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(3));
		const uploadedNames = onUpload.mock.calls.map(
			(call) => (call[0] as File).name,
		);
		expect(uploadedNames.sort()).toEqual(["a.pdf", "b.pdf", "c.pdf"]);
	});

	it("fails a non-PDF file independently with a distinct inline error, without blocking the valid PDF in the same batch", async () => {
		const onUpload = vi.fn().mockResolvedValue(undefined);
		const { container } = render(<DocumentUpload onUpload={onUpload} />);
		const dropzone = container.querySelector("button") as HTMLElement;
		const notPdf = new File(["hello"], "notes.txt", { type: "text/plain" });

		dropFiles(dropzone, [makePdf("a.pdf"), notPdf]);

		// The valid PDF still succeeds...
		await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(1));
		expect(onUpload).toHaveBeenCalledWith(
			expect.objectContaining({ name: "a.pdf" }),
		);
		// The invalid file is never sent to the upload endpoint at all...
		expect(onUpload).not.toHaveBeenCalledWith(
			expect.objectContaining({ name: "notes.txt" }),
		);
		// ...but it still surfaces a clear, distinct inline error naming it,
		// instead of silently vanishing from the batch.
		await waitFor(() =>
			expect(screen.getByRole("alert")).toHaveTextContent("notes.txt"),
		);
		expect(screen.getByRole("alert")).toHaveTextContent(/pdf/i);
		expect(screen.getByRole("alert")).not.toHaveTextContent("a.pdf");
	});

	it("partial-accepts a batch of 2 valid PDFs + 1 .txt: both PDFs succeed and the .txt shows a distinct error", async () => {
		const onUpload = vi.fn().mockResolvedValue(undefined);
		const { container } = render(<DocumentUpload onUpload={onUpload} />);
		const dropzone = container.querySelector("button") as HTMLElement;
		const notPdf = new File(["hello"], "notes.txt", { type: "text/plain" });

		dropFiles(dropzone, [makePdf("one.pdf"), makePdf("two.pdf"), notPdf]);

		await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(2));
		const uploadedNames = onUpload.mock.calls.map(
			(call) => (call[0] as File).name,
		);
		expect(uploadedNames.sort()).toEqual(["one.pdf", "two.pdf"]);

		await waitFor(() =>
			expect(screen.getByRole("alert")).toHaveTextContent("notes.txt"),
		);
		expect(screen.getByRole("alert")).not.toHaveTextContent("one.pdf");
		expect(screen.getByRole("alert")).not.toHaveTextContent("two.pdf");
	});

	it("shows a distinct inline error per invalid file when a batch is entirely invalid types", async () => {
		const onUpload = vi.fn().mockResolvedValue(undefined);
		const { container } = render(<DocumentUpload onUpload={onUpload} />);
		const dropzone = container.querySelector("button") as HTMLElement;
		const notPdfA = new File(["hello"], "one.txt", { type: "text/plain" });
		const notPdfB = new File(["hello"], "two.docx", {
			type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
		});

		dropFiles(dropzone, [notPdfA, notPdfB]);

		expect(onUpload).not.toHaveBeenCalled();
		await waitFor(() =>
			expect(screen.getByRole("alert")).toHaveTextContent("one.txt"),
		);
		expect(screen.getByRole("alert")).toHaveTextContent("two.docx");
	});

	it("never runs more than 3 uploads concurrently for a larger batch", async () => {
		const gates = Array.from({ length: 5 }, () => deferred<void>());
		let inFlight = 0;
		let maxInFlight = 0;
		const onUpload = vi.fn(async (file: File) => {
			inFlight += 1;
			maxInFlight = Math.max(maxInFlight, inFlight);
			const index = Number(file.name.match(/\d+/)?.[0]);
			await gates[index]?.promise;
			inFlight -= 1;
		});

		const { container } = render(<DocumentUpload onUpload={onUpload} />);
		const dropzone = container.querySelector("button") as HTMLElement;

		dropFiles(
			dropzone,
			gates.map((_, i) => makePdf(`file-${i}.pdf`)),
		);

		await waitFor(() => expect(inFlight).toBe(3));
		expect(maxInFlight).toBeLessThanOrEqual(3);

		for (const gate of gates) gate.resolve();
		await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(5));
	});

	it("surfaces a visible error for files that fail to upload without silently dropping them", async () => {
		const onUpload = vi.fn(async (file: File) => {
			if (file.name === "bad.pdf") {
				throw new Error("409: document already exists");
			}
		});
		const { container } = render(<DocumentUpload onUpload={onUpload} />);
		const dropzone = container.querySelector("button") as HTMLElement;

		dropFiles(dropzone, [makePdf("good.pdf"), makePdf("bad.pdf")]);

		await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(2));
		await waitFor(() =>
			expect(screen.getByRole("alert")).toHaveTextContent(
				"409: document already exists",
			),
		);
		expect(screen.getByRole("alert")).toHaveTextContent("bad.pdf");
	});

	it("calls onBatchSettled exactly once after a batch finishes, regardless of per-file outcome", async () => {
		const onUpload = vi.fn(async (file: File) => {
			if (file.name === "bad.pdf") {
				throw new Error("boom");
			}
		});
		const onBatchSettled = vi.fn();
		const { container } = render(
			<DocumentUpload onUpload={onUpload} onBatchSettled={onBatchSettled} />,
		);
		const dropzone = container.querySelector("button") as HTMLElement;

		dropFiles(dropzone, [
			makePdf("good.pdf"),
			makePdf("bad.pdf"),
			makePdf("also-good.pdf"),
		]);

		await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(3));
		await waitFor(() => expect(onBatchSettled).toHaveBeenCalledTimes(1));
	});

	it("shows a busy/uploading state while a batch is in flight", async () => {
		const gate = deferred<void>();
		const onUpload = vi.fn().mockReturnValue(gate.promise);
		const { container } = render(<DocumentUpload onUpload={onUpload} />);
		const dropzone = container.querySelector("button") as HTMLElement;

		dropFiles(dropzone, [makePdf("a.pdf")]);

		await waitFor(() =>
			expect(screen.getByText(/uploading/i)).toBeInTheDocument(),
		);

		gate.resolve();
		await waitFor(() =>
			expect(screen.queryByText(/uploading/i)).not.toBeInTheDocument(),
		);
	});
});
