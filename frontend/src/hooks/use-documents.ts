import { useCallback, useEffect, useState } from "react";
import * as api from "../lib/api";
import type { Document } from "../types";

export function useDocuments(conversationId: string | null) {
	const [documents, setDocuments] = useState<Document[]>([]);
	const [uploading, setUploading] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const refresh = useCallback(async () => {
		if (!conversationId) {
			setDocuments([]);
			return;
		}
		try {
			setError(null);
			const detail = await api.fetchConversation(conversationId);
			setDocuments(detail.documents);
		} catch (err) {
			setError(err instanceof Error ? err.message : "Failed to load documents");
		}
	}, [conversationId]);

	useEffect(() => {
		refresh();
	}, [refresh]);

	const upload = useCallback(
		async (file: File) => {
			if (!conversationId) return null;
			try {
				setUploading(true);
				setError(null);
				const doc = await api.uploadDocument(conversationId, file);
				setDocuments((prev) => [...prev, doc]);
				return doc;
			} catch (err) {
				const message =
					err instanceof Error ? err.message : "Failed to upload document";
				setError(message);
				// Re-throw (rather than swallowing and returning null) so batch
				// callers can tell success from failure per file and surface it,
				// instead of the failure disappearing silently.
				throw err instanceof Error ? err : new Error(message);
			} finally {
				setUploading(false);
			}
		},
		[conversationId],
	);

	const rename = useCallback(
		async (documentId: string, displayName: string) => {
			try {
				setError(null);
				const updated = await api.renameDocument(documentId, displayName);
				setDocuments((prev) =>
					prev.map((doc) => (doc.id === documentId ? updated : doc)),
				);
				return updated;
			} catch (err) {
				const message =
					err instanceof Error ? err.message : "Failed to rename document";
				setError(message);
				// Re-throw (rather than swallowing) so the caller (the inline rename
				// UI) can keep editing open and show the failure, instead of it
				// silently reverting to the old name with no explanation.
				throw err instanceof Error ? err : new Error(message);
			}
		},
		[],
	);

	return {
		documents,
		uploading,
		error,
		upload,
		rename,
		refresh,
	};
}
