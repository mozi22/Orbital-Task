/**
 * Runs `task` over `items` with at most `limit` tasks in flight at once.
 *
 * Used for batch file uploads: dropping/selecting several files at once should
 * fire them at the existing single-file endpoint with limited concurrency
 * (not fully serial, not all-at-once).
 *
 * A rejected task never stops the pool from processing the remaining items —
 * per-item error handling/surfacing is the caller's responsibility.
 */
export async function runWithConcurrency<T>(
	items: T[],
	limit: number,
	task: (item: T, index: number) => Promise<void>,
): Promise<void> {
	if (items.length === 0) return;

	const concurrency = Math.max(1, Math.min(limit, items.length));
	let nextIndex = 0;

	async function worker(): Promise<void> {
		while (nextIndex < items.length) {
			const currentIndex = nextIndex;
			nextIndex += 1;
			const item = items[currentIndex];
			if (item === undefined) continue;
			try {
				await task(item, currentIndex);
			} catch {
				// Swallow: one failing item must never halt the rest of the batch.
			}
		}
	}

	await Promise.all(Array.from({ length: concurrency }, () => worker()));
}
