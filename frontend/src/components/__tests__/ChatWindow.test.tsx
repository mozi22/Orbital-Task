import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Message } from "../../types";
import { ChatWindow } from "../ChatWindow";
import { TooltipProvider } from "../ui/tooltip";

function baseProps(overrides: Partial<Parameters<typeof ChatWindow>[0]> = {}) {
	const messages: Message[] = [];
	return {
		messages,
		loading: false,
		error: null,
		streaming: false,
		streamingContent: "",
		documentCount: 0,
		maxDocuments: 5,
		conversationId: "conv-1",
		onSend: vi.fn(),
		onUpload: vi.fn(),
		...overrides,
	};
}

describe("ChatWindow", () => {
	afterEach(() => {
		vi.restoreAllMocks();
		cleanup();
	});

	function renderChatWindow(
		overrides: Partial<Parameters<typeof ChatWindow>[0]> = {},
	) {
		return render(
			<TooltipProvider>
				<ChatWindow {...baseProps(overrides)} />
			</TooltipProvider>,
		);
	}

	it("shows the upload dropzone when there are no documents yet", () => {
		renderChatWindow({ documentCount: 0 });
		expect(
			screen.getByText("Upload a document to get started"),
		).toBeInTheDocument();
	});

	it("shows the correct attached count below the cap once at least one document is attached", () => {
		renderChatWindow({ documentCount: 3 });
		expect(
			screen.getAllByText("3/5 documents attached").length,
		).toBeGreaterThan(0);
	});

	it('shows "5/5 documents attached" once the conversation is at the cap', () => {
		renderChatWindow({ documentCount: 5 });
		expect(
			screen.getAllByText("5/5 documents attached").length,
		).toBeGreaterThan(0);
	});
});
