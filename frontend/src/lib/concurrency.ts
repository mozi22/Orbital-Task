/** Outcome of a single item processed by {@link runWithConcurrency}. */
export type ConcurrencyResult<T> =
	| { item: T; index: number; status: "fulfilled" }
	| { item: T; index: number; status: "rejected"; error: unknown };

/**
 * Runs `task` over `items` with at most `limit` tasks in flight at once.
 *
 * Used for batch file uploads: dropping/selecting several files at once should
 * fire them at the existing single-file endpoint with limited concurrency
 * (not fully serial, not all-at-once).
 *
 * A rejected task never stops the pool from processing the remaining items,
 * but its failure is never discarded either: every item's outcome (success or
 * the thrown error) is returned to the caller so failures can be surfaced
 * instead of silently swallowed.
 */
export async function runWithConcurrency<T>(
	items: T[],
	limit: number,
	task: (item: T, index: number) => Promise<void>,
): Promise<ConcurrencyResult<T>[]> {
	if (items.length === 0) return [];

	const concurrency = Math.max(1, Math.min(limit, items.length));
	let nextIndex = 0;
	const results: ConcurrencyResult<T>[] = new Array(items.length);

	async function worker(): Promise<void> {
		while (nextIndex < items.length) {
			const currentIndex = nextIndex;
			nextIndex += 1;
			const item = items[currentIndex];
			if (item === undefined) continue;
			try {
				await task(item, currentIndex);
				results[currentIndex] = {
					item,
					index: currentIndex,
					status: "fulfilled",
				};
			} catch (error) {
				// Never halt the rest of the batch, but never discard the failure
				// either — record it so the caller can surface it.
				results[currentIndex] = {
					item,
					index: currentIndex,
					status: "rejected",
					error,
				};
			}
		}
	}

	await Promise.all(Array.from({ length: concurrency }, () => worker()));

	return results;
}
