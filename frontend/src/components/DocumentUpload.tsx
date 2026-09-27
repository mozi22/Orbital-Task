import { Loader2, Upload } from "lucide-react";
import { type DragEvent, useCallback, useRef, useState } from "react";
import { ApiError, DOCUMENT_LIMIT_EXCEEDED_CODE } from "../lib/api";
import { runWithConcurrency } from "../lib/concurrency";

// Batch uploads go through the existing single-file endpoint, one call per
// file, with at most this many in flight at once (limited concurrency, not
// fully serial and not all-at-once).
const MAX_CONCURRENT_UPLOADS = 3;

interface DocumentUploadProps {
	onUpload: (file: File) => void | Promise<void>;
	/**
	 * Called exactly once after every file in a batch has settled (whether it
	 * succeeded or failed), never once per file. Used by callers to reconcile
	 * state (e.g. refetch the document/conversation) a single time instead of
	 * racing per-upload updates against each other.
	 */
	onBatchSettled?: () => void;
	uploading?: boolean;
}

interface BatchProgress {
	completed: number;
	total: number;
}

interface FileUploadError {
	fileName: string;
	message: string;
}

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : "Upload failed";
}

// Cap-exceeded failures get their own distinct, clearly-labeled message
// instead of the raw upload-service error text, so a file that didn't fit
// under the 5-document cap reads unambiguously differently from a wrong-type
// or oversized-file failure in the same batch.
function uploadFailureMessage(error: unknown): string {
	if (
		error instanceof ApiError &&
		error.code === DOCUMENT_LIMIT_EXCEEDED_CODE
	) {
		return `Document limit reached: ${error.message}`;
	}
	return errorMessage(error);
}

function isPdf(file: File): boolean {
	return (
		file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf")
	);
}

export function DocumentUpload({
	onUpload,
	onBatchSettled,
	uploading = false,
}: DocumentUploadProps) {
	const [dragOver, setDragOver] = useState(false);
	const [batchProgress, setBatchProgress] = useState<BatchProgress | null>(
		null,
	);
	const [uploadErrors, setUploadErrors] = useState<FileUploadError[]>([]);
	const fileInputRef = useRef<HTMLInputElement>(null);

	const processFiles = useCallback(
		async (files: File[]) => {
			if (files.length === 0) return;

			// Wrong-type files fail independently right here, before ever
			// touching the upload endpoint, with a clear per-file error — one
			// bad file (e.g. a .txt dropped alongside PDFs) must never look
			// like it silently vanished, and must never block the PDFs in the
			// same batch from uploading.
			const pdfFiles = files.filter(isPdf);
			const invalidTypeErrors: FileUploadError[] = files
				.filter((file) => !isPdf(file))
				.map((file) => ({
					fileName: file.name,
					message: "Only PDF files are supported.",
				}));

			setUploadErrors(invalidTypeErrors);

			if (pdfFiles.length === 0) return;

			let completed = 0;
			setBatchProgress({ completed, total: pdfFiles.length });

			const results = await runWithConcurrency(
				pdfFiles,
				MAX_CONCURRENT_UPLOADS,
				async (file) => {
					try {
						await onUpload(file);
					} finally {
						completed += 1;
						setBatchProgress({ completed, total: pdfFiles.length });
					}
				},
			);

			setBatchProgress(null);

			// Surface every failure visibly instead of letting it disappear —
			// dropping a batch's worth of files must never look like every one
			// of them silently succeeded.
			const uploadFailures = results
				.filter((result) => result.status === "rejected")
				.map((result) => ({
					fileName: result.item.name,
					message: uploadFailureMessage(result.error),
				}));
			setUploadErrors([...invalidTypeErrors, ...uploadFailures]);

			// Fire once for the whole batch, not once per file, so callers can
			// reconcile state (e.g. refetch) a single deterministic time.
			onBatchSettled?.();
		},
		[onUpload, onBatchSettled],
	);

	const handleDragOver = useCallback((e: DragEvent) => {
		e.preventDefault();
		setDragOver(true);
	}, []);

	const handleDragLeave = useCallback((e: DragEvent) => {
		e.preventDefault();
		setDragOver(false);
	}, []);

	const handleDrop = useCallback(
		(e: DragEvent) => {
			e.preventDefault();
			setDragOver(false);
			processFiles(Array.from(e.dataTransfer.files));
		},
		[processFiles],
	);

	const handleClick = useCallback(() => {
		fileInputRef.current?.click();
	}, []);

	const handleFileChange = useCallback(
		(e: React.ChangeEvent<HTMLInputElement>) => {
			processFiles(Array.from(e.target.files ?? []));
			if (fileInputRef.current) {
				fileInputRef.current.value = "";
			}
		},
		[processFiles],
	);

	const isBusy = uploading || batchProgress !== null;

	return (
		<div className="flex w-full max-w-md flex-col gap-2">
			<button
				type="button"
				className={`w-full cursor-pointer rounded-xl border-2 border-dashed px-8 py-10 text-center transition-colors ${
					dragOver
						? "border-neutral-400 bg-neutral-100"
						: "border-neutral-200 bg-white hover:border-neutral-300 hover:bg-neutral-50"
				}`}
				onDragOver={handleDragOver}
				onDragLeave={handleDragLeave}
				onDrop={handleDrop}
				onClick={handleClick}
			>
				<input
					ref={fileInputRef}
					type="file"
					accept=".pdf"
					multiple
					className="hidden"
					onChange={handleFileChange}
				/>

				{isBusy ? (
					<div className="flex flex-col items-center">
						<Loader2 className="mb-3 h-10 w-10 animate-spin text-neutral-400" />
						<p className="text-sm font-medium text-neutral-600">
							{batchProgress && batchProgress.total > 1
								? `Uploading document ${Math.min(
										batchProgress.completed + 1,
										batchProgress.total,
									)} of ${batchProgress.total}...`
								: "Uploading document..."}
						</p>
					</div>
				) : (
					<div className="flex flex-col items-center">
						<Upload className="mb-3 h-10 w-10 text-neutral-400" />
						<p className="text-sm font-medium text-neutral-600">
							Upload PDF documents
						</p>
						<p className="mt-1 text-xs text-neutral-400">
							Click or drag and drop one or more files
						</p>
					</div>
				)}
			</button>

			{uploadErrors.length > 0 && (
				<div
					role="alert"
					className="rounded-lg bg-red-50 px-3 py-2 text-left text-xs text-red-600"
				>
					{uploadErrors.map((fileError) => (
						<p key={fileError.fileName}>
							<span className="font-medium">{fileError.fileName}</span>:{" "}
							{fileError.message}
						</p>
					))}
				</div>
			)}
		</div>
	);
}
