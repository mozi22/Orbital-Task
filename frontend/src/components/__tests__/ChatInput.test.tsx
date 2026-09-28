import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatInput } from "../ChatInput";
import { TooltipProvider } from "../ui/tooltip";

function renderChatInput(props: Partial<Parameters<typeof ChatInput>[0]>) {
	return render(
		<TooltipProvider>
			<ChatInput
				onSend={vi.fn()}
				onUpload={vi.fn()}
				onRunRiskReview={vi.fn()}
				riskReviewRunning={false}
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

	describe("Run Risk Review button", () => {
		it("is disabled when the conversation has no documents attached", () => {
			renderChatInput({ documentCount: 0 });

			expect(
				screen.getByRole("button", { name: /run risk review/i }),
			).toBeDisabled();
		});

		it("is enabled once at least one document is attached", () => {
			renderChatInput({ documentCount: 1 });

			expect(
				screen.getByRole("button", { name: /run risk review/i }),
			).toBeEnabled();
		});

		it("calls onRunRiskReview when clicked", () => {
			const onRunRiskReview = vi.fn();
			renderChatInput({ documentCount: 2, onRunRiskReview });

			fireEvent.click(screen.getByRole("button", { name: /run risk review/i }));

			expect(onRunRiskReview).toHaveBeenCalledTimes(1);
		});

		it("shows a loading/running state and disables the button while a review is in flight", () => {
			renderChatInput({ documentCount: 2, riskReviewRunning: true });

			const button = screen.getByRole("button", { name: /running/i });
			expect(button).toBeDisabled();
		});

		it("does not show the running state once no review is in flight", () => {
			renderChatInput({ documentCount: 2, riskReviewRunning: false });

			expect(
				screen.getByRole("button", { name: /run risk review/i }),
			).toBeInTheDocument();
			expect(
				screen.queryByRole("button", { name: /running/i }),
			).not.toBeInTheDocument();
		});
	});
});
