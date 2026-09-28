import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../../lib/api";
import { useRiskReview } from "../use-risk-review";

describe("useRiskReview", () => {
	afterEach(() => {
		vi.restoreAllMocks();
		cleanup();
	});

	it("starts not running with no error", () => {
		const { result } = renderHook(() => useRiskReview("conv-1"));

		expect(result.current.running).toBe(false);
		expect(result.current.error).toBeNull();
	});

	it("does nothing when no conversation is selected", async () => {
		vi.spyOn(api, "triggerRiskReview");
		const { result } = renderHook(() => useRiskReview(null));

		await result.current.trigger();

		expect(api.triggerRiskReview).not.toHaveBeenCalled();
		expect(result.current.running).toBe(false);
	});

	it("sets running=true once the trigger call succeeds, and keeps it true (no completion signal exists yet)", async () => {
		vi.spyOn(api, "triggerRiskReview").mockResolvedValue({
			run_id: "matter-1",
			status: "running",
		});

		const { result } = renderHook(() => useRiskReview("conv-1"));

		await result.current.trigger();

		await waitFor(() => expect(result.current.running).toBe(true));
		expect(api.triggerRiskReview).toHaveBeenCalledWith("conv-1");
		expect(result.current.error).toBeNull();
	});

	it("ignores a second trigger call while the first is still in flight (guards a rapid double-click)", async () => {
		let resolveTrigger!: (value: {
			run_id: string;
			status: "running";
		}) => void;
		const pending = new Promise<{ run_id: string; status: "running" }>(
			(resolve) => {
				resolveTrigger = resolve;
			},
		);
		vi.spyOn(api, "triggerRiskReview").mockReturnValue(pending);

		const { result } = renderHook(() => useRiskReview("conv-1"));

		const first = result.current.trigger();
		const second = result.current.trigger();

		resolveTrigger({ run_id: "matter-1", status: "running" });
		await Promise.all([first, second]);

		expect(api.triggerRiskReview).toHaveBeenCalledTimes(1);
		await waitFor(() => expect(result.current.running).toBe(true));
	});

	it("resets running to false and surfaces an error message when the trigger call fails", async () => {
		vi.spyOn(api, "triggerRiskReview").mockRejectedValue(
			new Error("409: risk review already running"),
		);

		const { result } = renderHook(() => useRiskReview("conv-1"));

		await expect(result.current.trigger()).rejects.toThrow(
			"409: risk review already running",
		);

		await waitFor(() => expect(result.current.running).toBe(false));
		expect(result.current.error).toBe("409: risk review already running");
	});
});
