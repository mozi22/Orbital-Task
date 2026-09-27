import { describe, expect, it, vi } from "vitest";
import { runWithConcurrency } from "../concurrency";

function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((res) => {
		resolve = res;
	});
	return { promise, resolve };
}

describe("runWithConcurrency", () => {
	it("resolves immediately for an empty list without calling the task", async () => {
		const task = vi.fn();
		await runWithConcurrency([], 3, task);
		expect(task).not.toHaveBeenCalled();
	});

	it("runs every item exactly once", async () => {
		const seen: number[] = [];
		await runWithConcurrency([1, 2, 3, 4, 5], 2, async (item) => {
			seen.push(item);
		});
		expect(seen.sort()).toEqual([1, 2, 3, 4, 5]);
	});

	it("never exceeds the concurrency limit at any point in time", async () => {
		const items = Array.from({ length: 6 }, (_, i) => i);
		let inFlight = 0;
		let maxInFlight = 0;
		const gates = items.map(() => deferred<void>());

		const runPromise = runWithConcurrency(items, 3, async (item) => {
			inFlight += 1;
			maxInFlight = Math.max(maxInFlight, inFlight);
			await gates[item]?.promise;
			inFlight -= 1;
		});

		// Let the first wave of tasks start.
		await Promise.resolve();
		await Promise.resolve();

		// Exactly 3 should be in flight (the concurrency limit), not all 6.
		expect(inFlight).toBe(3);

		// Release all gates so the pool can drain.
		for (const gate of gates) gate.resolve();
		await runPromise;

		expect(maxInFlight).toBe(3);
	});

	it("keeps processing remaining items when one task rejects", async () => {
		const processed: number[] = [];
		await runWithConcurrency([1, 2, 3], 2, async (item) => {
			if (item === 2) {
				throw new Error("boom");
			}
			processed.push(item);
		});
		expect(processed.sort()).toEqual([1, 3]);
	});

	it("returns per-item settled results instead of discarding failures", async () => {
		const results = await runWithConcurrency([1, 2, 3], 2, async (item) => {
			if (item === 2) {
				throw new Error("boom");
			}
		});

		expect(results).toHaveLength(3);
		const byItem = new Map(results.map((r) => [r.item, r]));
		expect(byItem.get(1)).toMatchObject({ status: "fulfilled" });
		expect(byItem.get(3)).toMatchObject({ status: "fulfilled" });
		const failed = byItem.get(2);
		expect(failed?.status).toBe("rejected");
		if (failed?.status === "rejected") {
			expect(failed.error).toBeInstanceOf(Error);
			expect((failed.error as Error).message).toBe("boom");
		}
	});

	it("caps effective concurrency at the number of items when limit is larger", async () => {
		const task = vi.fn(async () => {});
		await runWithConcurrency([1, 2], 10, task);
		expect(task).toHaveBeenCalledTimes(2);
	});
});
