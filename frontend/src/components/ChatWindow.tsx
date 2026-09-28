import { Loader2 } from "lucide-react";
import { useEffect, useRef } from "react";
import type { Message } from "../types";
import { ChatInput } from "./ChatInput";
import { EmptyState } from "./EmptyState";
import { ErrorBanner } from "./ErrorBanner";
import { MessageBubble, StreamingBubble } from "./MessageBubble";

interface ChatWindowProps {
	messages: Message[];
	loading: boolean;
	error: string | null;
	documentError?: string | null;
	/** Surfaced when `onRunRiskReview` rejects — mirrors `documentError`'s shape. */
	riskReviewError?: string | null;
	streaming: boolean;
	streamingContent: string;
	/** Number of documents currently attached to this conversation. */
	documentCount: number;
	/** The conversation-wide document cap (mirrors the backend's limit). */
	maxDocuments: number;
	conversationId: string | null;
	onSend: (content: string) => void;
	onUpload: (file: File) => void | Promise<void>;
	/**
	 * Called exactly once per user-initiated upload action once it fully
	 * settles — once for a single attach-button upload, and once for an
	 * entire drag/drop batch, never once per file within a batch.
	 */
	onUploadSettled?: () => void;
	/** Triggers a risk-review run — see `ChatInput`'s own prop for details. */
	onRunRiskReview: () => void | Promise<void>;
	/** True while a risk-review run is in flight — see `ChatInput`'s own prop. */
	riskReviewRunning: boolean;
}

export function ChatWindow({
	messages,
	loading,
	error,
	documentError,
	riskReviewError,
	streaming,
	streamingContent,
	documentCount,
	maxDocuments,
	conversationId,
	onSend,
	onUpload,
	onUploadSettled,
	onRunRiskReview,
	riskReviewRunning,
}: ChatWindowProps) {
	const scrollRef = useRef<HTMLDivElement>(null);
	const hasDocument = documentCount > 0;

	// Auto-scroll to bottom when new messages arrive or during streaming
	const messagesLength = messages.length;
	// biome-ignore lint/correctness/useExhaustiveDependencies: messages and streamingContent are intentional triggers for auto-scroll
	useEffect(() => {
		if (scrollRef.current) {
			scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
		}
	}, [messagesLength, streamingContent]);

	// No conversation selected
	if (!conversationId) {
		return (
			<div className="flex flex-1 items-center justify-center bg-neutral-50">
				<div className="text-center">
					<p className="text-sm text-neutral-400">
						Select a conversation or create a new one
					</p>
				</div>
			</div>
		);
	}

	// Loading messages
	if (loading) {
		return (
			<div className="flex flex-1 items-center justify-center bg-white">
				<Loader2 className="h-6 w-6 animate-spin text-neutral-400" />
			</div>
		);
	}

	// Empty conversation - show upload prompt
	if (messages.length === 0 && !streaming) {
		return (
			<div className="flex flex-1 flex-col bg-white">
				{documentError && <ErrorBanner message={documentError} />}
				{riskReviewError && <ErrorBanner message={riskReviewError} />}
				<div className="flex flex-1 items-center justify-center">
					{hasDocument ? (
						<div className="text-center">
							<p className="text-sm text-neutral-500">
								<span className="font-medium">
									{documentCount}/{maxDocuments} documents attached
								</span>
								. Ask a question to get started.
							</p>
						</div>
					) : (
						<EmptyState onUpload={onUpload} onBatchSettled={onUploadSettled} />
					)}
				</div>
				<ChatInput
					onSend={onSend}
					onUpload={onUpload}
					onUploadSettled={onUploadSettled}
					onRunRiskReview={onRunRiskReview}
					riskReviewRunning={riskReviewRunning}
					disabled={streaming}
					documentCount={documentCount}
					maxDocuments={maxDocuments}
				/>
			</div>
		);
	}

	return (
		<div className="flex flex-1 flex-col bg-white">
			{error && <ErrorBanner message={error} />}
			{documentError && <ErrorBanner message={documentError} />}
			{riskReviewError && <ErrorBanner message={riskReviewError} />}

			<div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-4">
				<div className="mx-auto max-w-2xl space-y-1">
					{messages.map((message) => (
						<MessageBubble key={message.id} message={message} />
					))}
					{streaming && <StreamingBubble content={streamingContent} />}
				</div>
			</div>

			<ChatInput
				onSend={onSend}
				onUpload={onUpload}
				onUploadSettled={onUploadSettled}
				onRunRiskReview={onRunRiskReview}
				riskReviewRunning={riskReviewRunning}
				disabled={streaming}
				documentCount={documentCount}
				maxDocuments={maxDocuments}
			/>
		</div>
	);
}
