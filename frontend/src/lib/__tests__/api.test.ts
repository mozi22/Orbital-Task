import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, uploadDocument } from "../api";

function jsonResponse(status: number, body: unknown): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { "Content-Type": "application/json" },
	});
}

describe("uploadDocument error handling", () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	it("throws an ApiError carrying the backend's code and clean message on a structured error body", async () => {
		vi.stubGlobal(
			"fetch",
			vi.fn().mockResolvedValue(
				jsonResponse(409, {
					detail: {
						code: "document_limit_exceeded",
						message:
							"Conversation already has the maximum of 5 documents allowed.",
					},
				}),
			),
		);

		const file = new File(["%PDF-1.4"], "f.pdf", { type: "application/pdf" });
		await expect(uploadDocument("conv-1", file)).rejects.toMatchObject({
			code: "document_limit_exceeded",
			message: "Conversation already has the maximum of 5 documents allowed.",
			status: 409,
		});
		await expect(uploadDocument("conv-1", file)).rejects.toBeInstanceOf(
			ApiError,
		);
	});

	it("falls back to a plain message when the error body has no structured code", async () => {
		vi.stubGlobal(
			"fetch",
			vi
				.fn()
				.mockResolvedValue(
					jsonResponse(404, { detail: "Conversation not found" }),
				),
		);

		const file = new File(["%PDF-1.4"], "f.pdf", { type: "application/pdf" });
		await expect(uploadDocument("conv-1", file)).rejects.toMatchObject({
			message: "Conversation not found",
			code: undefined,
			status: 404,
		});
	});

	it("falls back to raw text when the error body isn't JSON at all", async () => {
		vi.stubGlobal(
			"fetch",
			vi
				.fn()
				.mockResolvedValue(
					new Response("Internal Server Error", { status: 500 }),
				),
		);

		const file = new File(["%PDF-1.4"], "f.pdf", { type: "application/pdf" });
		await expect(uploadDocument("conv-1", file)).rejects.toMatchObject({
			message: "Internal Server Error",
			status: 500,
		});
	});
});
