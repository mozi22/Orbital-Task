import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, renameDocument, uploadDocument } from "../api";

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

describe("renameDocument", () => {
	afterEach(() => {
		vi.restoreAllMocks();
	});

	it("PATCHes the document with the new display_name and returns the updated document", async () => {
		const fetchMock = vi.fn().mockResolvedValue(
			jsonResponse(200, {
				id: "doc-1",
				conversation_id: "conv-1",
				filename: "lease.pdf",
				display_name: "Signed Lease",
				page_count: 3,
				uploaded_at: "2026-01-01T00:00:00Z",
			}),
		);
		vi.stubGlobal("fetch", fetchMock);

		const result = await renameDocument("doc-1", "Signed Lease");

		expect(fetchMock).toHaveBeenCalledWith(
			"/api/documents/doc-1",
			expect.objectContaining({
				method: "PATCH",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ display_name: "Signed Lease" }),
			}),
		);
		expect(result.display_name).toBe("Signed Lease");
	});

	it("throws an ApiError carrying the backend's code on an invalid display name", async () => {
		vi.stubGlobal(
			"fetch",
			vi.fn().mockResolvedValue(
				jsonResponse(400, {
					detail: {
						code: "invalid_display_name",
						message: "display_name must not be empty or blank.",
					},
				}),
			),
		);

		await expect(renameDocument("doc-1", "")).rejects.toMatchObject({
			code: "invalid_display_name",
			message: "display_name must not be empty or blank.",
			status: 400,
		});
		await expect(renameDocument("doc-1", "")).rejects.toBeInstanceOf(ApiError);
	});
});
