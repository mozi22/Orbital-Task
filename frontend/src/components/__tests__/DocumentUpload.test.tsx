import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

	it("ignores non-PDF files dropped alongside valid ones", async () => {
		const onUpload = vi.fn().mockResolvedValue(undefined);
		const { container } = render(<DocumentUpload onUpload={onUpload} />);
		const dropzone = container.querySelector("button") as HTMLElement;
		const notPdf = new File(["hello"], "notes.txt", { type: "text/plain" });

		dropFiles(dropzone, [makePdf("a.pdf"), notPdf]);

		await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(1));
		expect(onUpload).toHaveBeenCalledWith(
			expect.objectContaining({ name: "a.pdf" }),
		);
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
