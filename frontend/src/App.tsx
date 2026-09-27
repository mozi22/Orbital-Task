import { useCallback } from "react";
import { ChatSidebar } from "./components/ChatSidebar";
import { ChatWindow } from "./components/ChatWindow";
import { DocumentViewer } from "./components/DocumentViewer";
import { TooltipProvider } from "./components/ui/tooltip";
import { useConversations } from "./hooks/use-conversations";
import { useDocuments } from "./hooks/use-documents";
import { useMessages } from "./hooks/use-messages";
import { MAX_DOCUMENTS_PER_CONVERSATION } from "./lib/api";

export default function App() {
	const {
		conversations,
		selectedId,
		loading: conversationsLoading,
		create,
		select,
		remove,
		refresh: refreshConversations,
	} = useConversations();

	const {
		messages,
		loading: messagesLoading,
		error: messagesError,
		streaming,
		streamingContent,
		send,
	} = useMessages(selectedId);

	const {
		documents,
		upload,
		rename,
		error: documentError,
		refresh: refreshDocuments,
	} = useDocuments(selectedId);

	const handleSend = useCallback(
		async (content: string) => {
			await send(content);
			refreshConversations();
		},
		[send, refreshConversations],
	);

	// `upload` throws on failure rather than swallowing it, so a failed
	// upload here propagates to the caller (DocumentUpload / ChatInput),
	// which is what lets a batch surface which specific files failed.
	const handleUpload = useCallback(
		async (file: File) => {
			await upload(file);
		},
		[upload],
	);

	// Reconcile document/conversation state exactly once per upload action —
	// once for a single ChatInput upload, once for an entire drag/drop batch —
	// rather than once per file. Refetching here (instead of trusting
	// whichever concurrent upload's `setDocuments` call happened to resolve
	// last) also keeps the final documents state deterministic regardless of
	// how a batch's uploads interleaved.
	const handleUploadSettled = useCallback(() => {
		refreshDocuments();
		refreshConversations();
	}, [refreshDocuments, refreshConversations]);

	const handleCreate = useCallback(async () => {
		await create();
	}, [create]);

	return (
		<TooltipProvider delayDuration={200}>
			<div className="flex h-screen bg-neutral-50">
				<ChatSidebar
					conversations={conversations}
					selectedId={selectedId}
					loading={conversationsLoading}
					onSelect={select}
					onCreate={handleCreate}
					onDelete={remove}
				/>

				<ChatWindow
					messages={messages}
					loading={messagesLoading}
					error={messagesError}
					streaming={streaming}
					streamingContent={streamingContent}
					documentCount={documents.length}
					maxDocuments={MAX_DOCUMENTS_PER_CONVERSATION}
					conversationId={selectedId}
					onSend={handleSend}
					onUpload={handleUpload}
					onUploadSettled={handleUploadSettled}
					documentError={documentError}
				/>

				<DocumentViewer documents={documents} onRename={rename} />
			</div>
		</TooltipProvider>
	);
}
