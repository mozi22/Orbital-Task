import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatInput } from "../ChatInput";
import { TooltipProvider } from "../ui/tooltip";

function renderChatInput(props: Partial<Parameters<typeof ChatInput>[0]>) {
	return render(
		<TooltipProvider>
			<ChatInput
				onSend={vi.fn()}
				onUpload={vi.fn()}
				disabled={false}
				documentCount={0}
				maxDocuments={5}
				{...props}
			/>
		</TooltipProvider>,
	);
}

describe("ChatInput", () => {
	afterEach(() => {
		vi.restoreAllMocks();
		cleanup();
	});

	it("shows the correct count and keeps the upload control enabled below the cap", () => {
		renderChatInput({ documentCount: 3, maxDocuments: 5 });

		expect(screen.getByText("3/5 documents attached")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: /attach/i })).toBeEnabled();
	});

	it('shows "5/5 documents attached" and disables the upload control once the cap is reached', () => {
		renderChatInput({ documentCount: 5, maxDocuments: 5 });

		expect(screen.getByText("5/5 documents attached")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: /attach/i })).toBeDisabled();
	});

	it("shows 0/5 documents attached when no documents are attached yet", () => {
		renderChatInput({ documentCount: 0, maxDocuments: 5 });

		expect(screen.getByText("0/5 documents attached")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: /attach/i })).toBeEnabled();
	});
});
