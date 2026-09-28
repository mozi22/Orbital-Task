import { useCallback, useRef, useState } from "react";
import * as api from "../lib/api";

/**
 * Wraps the risk-review trigger endpoint
 * (`POST /api/conversations/{id}/risk-review`) for the "Run Risk Review"
 * button (see the Milestone 2 PRD, #36).
 *
 * `running` turns true as soon as the trigger call succeeds and — unlike
 * `useDocuments`'s `uploading`/`useMessages`'s `streaming` — is *not* reset
 * back to false once the request settles: the backend pipeline itself keeps
 * running in the background well after this call returns (see #35's stub
 * pipeline), and this ticket has no way yet to observe when it finishes.
 * A later ticket (#38's SSE progress events / #43's frontend consumption of
 * them) is expected to turn `running` back off once the pipeline actually
 * completes. It only resets to false here if the trigger call itself fails,
 * so the solicitor can retry.
 */
export function useRiskReview(conversationId: string | null) {
	const [running, setRunning] = useState(false);
	const [error, setError] = useState<string | null>(null);
	// Guards against a rapid double-click firing two trigger requests before
	// React has re-rendered with `running=true` — a plain `if (running) return`
	// check here would still race, since the state update from the first
	// call's `setRunning(true)` isn't visible to the second call until after
	// this render commits. A ref updates synchronously instead.
	const inFlightRef = useRef(false);

	const trigger = useCallback(async () => {
		if (!conversationId || inFlightRef.current) return;
		inFlightRef.current = true;
		try {
			setError(null);
			await api.triggerRiskReview(conversationId);
			setRunning(true);
		} catch (err) {
			const message =
				err instanceof Error ? err.message : "Failed to start risk review";
			setError(message);
			setRunning(false);
			inFlightRef.current = false;
			// Re-throw (rather than swallowing) so the caller (ChatInput) can
			// surface the failure, matching useDocuments'/useMessages' shape.
			throw err instanceof Error ? err : new Error(message);
		}
	}, [conversationId]);

	return { running, error, trigger };
}
