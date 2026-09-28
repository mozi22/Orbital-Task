interface ErrorBannerProps {
	message: string;
}

/**
 * Shared inline error banner used by `ChatWindow` for its various error
 * sources (message send failures, document upload failures, risk-review
 * trigger failures) — previously each was a near-identical inline JSX block
 * repeated per error source per render branch.
 */
export function ErrorBanner({ message }: ErrorBannerProps) {
	return (
		<div className="mx-4 mt-2 rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">
			{message}
		</div>
	);
}
